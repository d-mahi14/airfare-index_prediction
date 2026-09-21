"""
serving/validation.py
Serve-time fare validation gate for real-time API query responses.

Applies strict per-fare checks:
  1. Synthetic data check (non-synthetic only by default; allowed in demo mode).
  2. Maximum age check (age <= max_age_hours).
  3. Fare decomposition consistency (base_fare + taxes + udf_psf + convenience_fee + other_fees == total_fare).
  4. Plausible price band per (route x lead_window).
  5. Sold-out and cancellation rejection (sold out fares hidden from active quotes).
  6. Cross-source price agreement across sources quoting the same flight/date.
  7. Minimum observation support.

Produces structured FareGateResult:
  - status: "ok" | "flagged" | "hidden"
  - confidence: "high" | "medium" | "low"
  - age_minutes: int
  - warnings: List[str]
"""
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
import yaml

logger = logging.getLogger(__name__)

DEFAULT_SERVING_YAML = Path(__file__).parent.parent / "config" / "serving.yaml"


@dataclass
class FareGateResult:
    """Evaluation result returned by FareGate for a single fare observation."""
    status: str  # "ok" | "flagged" | "hidden"
    confidence: str  # "high" | "medium" | "low"
    age_minutes: int
    warnings: List[str] = field(default_factory=list)
    is_synthetic: bool = False
    is_estimated: bool = False
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class FareGateConfig:
    """Configurable thresholds for serve-time validation gate."""
    max_age_hours: float = 36.0
    fee_tolerance: Decimal = Decimal("0.05")
    cross_source_tolerance_pct: float = 0.10
    cross_source_tolerance_abs: Decimal = Decimal("500.00")
    default_plausible_min: Decimal = Decimal("1500.00")
    default_plausible_max: Decimal = Decimal("40000.00")
    min_recent_observations: int = 1
    allow_synthetic: bool = False
    route_plausible_bands: Dict[str, Dict[str, float]] = field(default_factory=dict)

    @classmethod
    def from_yaml(cls, yaml_path: Optional[Path | str] = None, allow_synthetic: bool = False) -> "FareGateConfig":
        """Load configuration from config/serving.yaml."""
        p = Path(yaml_path) if yaml_path else DEFAULT_SERVING_YAML
        if not p.exists():
            return cls(allow_synthetic=allow_synthetic)

        try:
            with open(p, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            gate_data = data.get("gate", {})
            demo_data = data.get("demo", {})

            allow_synth = allow_synthetic or bool(demo_data.get("allow_synthetic_default", False))

            return cls(
                max_age_hours=float(gate_data.get("max_age_hours", 36.0)),
                fee_tolerance=Decimal(str(gate_data.get("fee_tolerance", 0.05))),
                cross_source_tolerance_pct=float(gate_data.get("cross_source_tolerance_pct", 0.10)),
                cross_source_tolerance_abs=Decimal(str(gate_data.get("cross_source_tolerance_abs", 500.0))),
                default_plausible_min=Decimal(str(gate_data.get("default_plausible_min", 1500.0))),
                default_plausible_max=Decimal(str(gate_data.get("default_plausible_max", 40000.0))),
                min_recent_observations=int(gate_data.get("min_recent_observations", 1)),
                allow_synthetic=allow_synth,
                route_plausible_bands=gate_data.get("route_plausible_bands", {}),
            )
        except Exception as exc:
            logger.warning(f"Error loading FareGateConfig from {p}: {exc}")
            return cls(allow_synthetic=allow_synthetic)


class FareGate:
    """
    Serve-time validation gate evaluating raw or cleaned fare quotes before serving.
    """

    def __init__(self, config: Optional[FareGateConfig] = None):
        self.config = config or FareGateConfig()

    def _get_attr(self, item: Any, key: str, default: Any = None) -> Any:
        if isinstance(item, dict):
            return item.get(key, default)
        return getattr(item, key, default)

    def _to_decimal(self, val: Any) -> Optional[Decimal]:
        if val is None:
            return None
        if isinstance(val, Decimal):
            return val
        try:
            return Decimal(str(val))
        except Exception:
            return None

    def _get_plausible_band(self, route_code: str) -> Tuple[Decimal, Decimal]:
        """Get plausible price range [min, max] for route."""
        route_upper = route_code.strip().upper()
        if route_upper in self.config.route_plausible_bands:
            b = self.config.route_plausible_bands[route_upper]
            return (
                Decimal(str(b.get("min", self.config.default_plausible_min))),
                Decimal(str(b.get("max", self.config.default_plausible_max))),
            )
        return (self.config.default_plausible_min, self.config.default_plausible_max)

    def build_cross_source_map(self, fares: List[Any]) -> Dict[Tuple[str, str, date], List[Tuple[str, Decimal]]]:
        """
        Group fares by (carrier, flight_number, travel_date) -> [(source_name, total_fare), ...].
        """
        mapping: Dict[Tuple[str, str, date], List[Tuple[str, Decimal]]] = {}
        for f in fares:
            carrier = str(self._get_attr(f, "airline_iata") or self._get_attr(f, "airline_name") or "").strip().upper()
            flight_no = str(self._get_attr(f, "flight_number") or "").strip().upper()
            travel_dt = self._get_attr(f, "travel_date")
            if isinstance(travel_dt, str):
                travel_dt = datetime.strptime(travel_dt, "%Y-%m-%d").date()
            tot = self._to_decimal(self._get_attr(f, "total_fare"))
            src = str(self._get_attr(f, "source_name") or "unknown")

            if carrier and flight_no and travel_dt and tot is not None:
                key = (carrier, flight_no, travel_dt)
                if key not in mapping:
                    mapping[key] = []
                mapping[key].append((src, tot))
        return mapping

    def evaluate_fare(
        self,
        fare: Any,
        cross_source_quotes: Optional[List[Tuple[str, Decimal]]] = None,
        total_recent_observations: int = 1,
        now_utc: Optional[datetime] = None,
        allow_synthetic_override: Optional[bool] = None,
    ) -> FareGateResult:
        """
        Evaluate a single fare observation and return its validation status and confidence.
        """
        now = now_utc or datetime.now(timezone.utc)
        allow_synthetic = (
            allow_synthetic_override if allow_synthetic_override is not None else self.config.allow_synthetic
        )

        warnings: List[str] = []
        is_synthetic = bool(self._get_attr(fare, "is_synthetic", False))
        is_sold_out = bool(self._get_attr(fare, "is_sold_out", False))
        avail = str(self._get_attr(fare, "availability", "available")).strip().lower()

        # 1. Synthetic Data Check
        if is_synthetic and not allow_synthetic:
            warnings.append("synthetic_data")
            return FareGateResult(
                status="hidden",
                confidence="low",
                age_minutes=0,
                warnings=warnings,
                is_synthetic=True,
                details={"reason": "Synthetic data excluded by policy"},
            )
        elif is_synthetic:
            warnings.append("synthetic_demo_data")

        # 2. Sold-Out / Cancellation Check
        if is_sold_out or avail in ("sold_out", "cancelled"):
            warnings.append("sold_out" if is_sold_out or avail == "sold_out" else "cancelled")
            return FareGateResult(
                status="hidden",
                confidence="low",
                age_minutes=0,
                warnings=warnings,
                is_synthetic=is_synthetic,
                details={"reason": "Flight is sold out or cancelled"},
            )

        # 3. Age / Staleness Check
        ts = self._get_attr(fare, "collection_timestamp")
        if ts is not None:
            if hasattr(ts, "tzinfo") and ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            age_delta = now - ts
            age_minutes = max(0, int(age_delta.total_seconds() / 60.0))
        else:
            age_minutes = 0

        max_age_minutes = int(self.config.max_age_hours * 60)
        if age_minutes > max_age_minutes:
            warnings.append("stale_data")
            return FareGateResult(
                status="hidden",
                confidence="low",
                age_minutes=age_minutes,
                warnings=warnings,
                is_synthetic=is_synthetic,
                details={"reason": f"Quote age {age_minutes}m exceeds max {max_age_minutes}m"},
            )

        # 4. Fare Decomposition Consistency Check
        total_fare = self._to_decimal(self._get_attr(fare, "total_fare"))
        base_fare = self._to_decimal(self._get_attr(fare, "base_fare"))
        taxes = self._to_decimal(self._get_attr(fare, "taxes")) or Decimal("0.00")
        udf_psf = self._to_decimal(self._get_attr(fare, "udf_psf")) or Decimal("0.00")
        conv = self._to_decimal(self._get_attr(fare, "convenience_fee")) or Decimal("0.00")
        other = self._to_decimal(self._get_attr(fare, "other_fees")) or Decimal("0.00")

        if total_fare is None or total_fare <= Decimal("0.00"):
            warnings.append("invalid_total_fare")
            return FareGateResult(
                status="hidden",
                confidence="low",
                age_minutes=age_minutes,
                warnings=warnings,
                is_synthetic=is_synthetic,
                details={"reason": "Missing or non-positive total fare"},
            )

        if base_fare is not None:
            comp_sum = base_fare + taxes + udf_psf + conv + other
            if abs(total_fare - comp_sum) > self.config.fee_tolerance:
                warnings.append("breakup_mismatch")
                return FareGateResult(
                    status="hidden",
                    confidence="low",
                    age_minutes=age_minutes,
                    warnings=warnings,
                    is_synthetic=is_synthetic,
                    details={"reason": f"Component sum {comp_sum} != total {total_fare}"},
                )

        # 5. Plausible Price Band Check
        origin = str(self._get_attr(fare, "origin") or "").strip().upper()
        dest = str(self._get_attr(fare, "destination") or "").strip().upper()
        route_code = str(self._get_attr(fare, "route_code") or f"{origin}-{dest}")

        plausible_min, plausible_max = self._get_plausible_band(route_code)
        is_unusual_price = False

        if total_fare < plausible_min or total_fare > plausible_max:
            is_unusual_price = True
            warnings.append("unusual_price")

        # 6. Cross-Source Price Agreement Check
        has_cross_source_disagreement = False
        if cross_source_quotes and len(cross_source_quotes) > 1:
            quote_fares = [q[1] for q in cross_source_quotes]
            min_q = min(quote_fares)
            max_q = max(quote_fares)
            spread = max_q - min_q
            rel_spread = float(spread / min_q) if min_q > 0 else 0.0

            if rel_spread > self.config.cross_source_tolerance_pct and spread > self.config.cross_source_tolerance_abs:
                has_cross_source_disagreement = True
                warnings.append("cross_source_disagreement")

        # 7. Observation Support Check
        low_support = total_recent_observations < self.config.min_recent_observations
        if low_support:
            warnings.append("low_observation_support")

        # Determine Final Status & Confidence
        if is_unusual_price or has_cross_source_disagreement:
            status = "flagged"
        else:
            status = "ok"

        if has_cross_source_disagreement or is_unusual_price:
            confidence = "medium" if not (has_cross_source_disagreement and is_unusual_price) else "low"
        elif low_support:
            confidence = "medium"
        else:
            confidence = "high"

        return FareGateResult(
            status=status,
            confidence=confidence,
            age_minutes=age_minutes,
            warnings=warnings,
            is_synthetic=is_synthetic,
            details={
                "plausible_band": [float(plausible_min), float(plausible_max)],
                "cross_source_quotes_count": len(cross_source_quotes) if cross_source_quotes else 1,
            },
        )
