"""
index/apix.py
Pure mathematical functions and service layer for APIx Airfare Price Index calculation.

Methodology Overview:
1. Elementary Index per (route, target_lead_window):
   Jevons geometric mean of price relatives vs. base period on matched strata
   (carrier + dep_band + fare_class).
   Fallback: Geometric mean of observed strata divided by base strata geometric mean.
2. Lead-Time Aggregation:
   Normalized lead_time_weights across active lead horizons (T+1, T+7, T+15, T+30, T+45).
3. Route Aggregation:
   Normalized route_weights (DGCA city-pair passenger traffic) with chain-linking on weight updates.
4. Variants:
   total_fare, base_fare_only, taxes_and_fees.
5. Integrity & Synthetic Policy:
   Refuses synthetic data unless explicitly allowed, stamping '_synthetic' suffix.
"""
import argparse
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import logging
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union
import yaml

from sqlalchemy.orm import Session

from backend.app.database import get_db_session
from backend.app.models.airfare import AirfareObservation, Route
from backend.app.models.index import IndexValue, LeadTimeWeight, RouteWeight

logger = logging.getLogger("apix.index")

DEFAULT_BASE_VALUE = 100.0
DEFAULT_METHODOLOGY_VERSION = "v1.0"
EXPECTED_LEAD_DAYS = [1, 7, 15, 30, 45]
VARIANTS = ["total_fare", "base_fare_only", "taxes_and_fees"]
FREQUENCIES = ["daily", "weekly", "monthly"]


# ─── Price Extraction ──────────────────────────────────────────────────────────

def extract_price(obs: Union[Dict[str, Any], Any], variant: str = "total_fare") -> Optional[float]:
    """
    Extract relevant monetary price from observation dict or ORM object according to variant.
    Returns None if price is missing, non-positive, or invalid.
    """
    def _get(key: str, default: Any = None) -> Any:
        if isinstance(obs, dict):
            return obs.get(key, default)
        return getattr(obs, key, default)

    try:
        if variant == "total_fare":
            val = _get("total_fare")
            if val is None:
                return None
            p = float(val)
            return p if p > 0 else None

        elif variant == "base_fare_only":
            val = _get("base_fare")
            if val is None:
                return None
            p = float(val)
            return p if p > 0 else None

        elif variant == "taxes_and_fees":
            taxes = _get("taxes") or 0
            udf = _get("udf_psf") or 0
            conv = _get("convenience_fee") or 0
            p = float(taxes) + float(udf) + float(conv)
            return p if p > 0 else None

        else:
            raise ValueError(f"Unknown variant '{variant}'. Must be one of {VARIANTS}")
    except (TypeError, ValueError):
        return None


def get_stratum_key(obs: Union[Dict[str, Any], Any]) -> Tuple[str, str, str]:
    """
    Construct stratum key: (carrier, dep_band, fare_class).
    """
    def _get(key: str, default: Any = "") -> Any:
        if isinstance(obs, dict):
            return obs.get(key, default)
        return getattr(obs, key, default)

    carrier = str(_get("carrier_code") or _get("airline_iata") or _get("carrier") or _get("airline") or "UNKNOWN").upper().strip()
    dep_band = str(_get("dep_band") or "standard").lower().strip()
    fare_class = str(_get("fare_class") or "economy").lower().strip()
    return (carrier, dep_band, fare_class)


# ─── Pure Math Functions ───────────────────────────────────────────────────────

def geometric_mean(values: Sequence[float]) -> Optional[float]:
    """Calculate geometric mean of positive numbers using log-sum-exp."""
    valid = [v for v in values if v is not None and v > 0]
    if not valid:
        return None
    log_sum = sum(math.log(v) for v in valid)
    return math.exp(log_sum / len(valid))


def compute_elementary_jevons(
    current_obs: Sequence[Union[Dict[str, Any], Any]],
    base_obs: Sequence[Union[Dict[str, Any], Any]],
    variant: str = "total_fare",
    base_value: float = DEFAULT_BASE_VALUE,
) -> Tuple[Optional[float], Dict[str, Any]]:
    """
    Compute elementary Jevons price index for a specific (route, lead_window) cell.

    Stratum matching: carrier + dep_band + fare_class.
    1. Group observations in period t and base period 0 by stratum.
    2. Compute geometric mean price per stratum in period t and base period 0.
    3. For matched strata (present in both), compute price relatives: R_s = p_{s,t} / p_{s,0}.
    4. Elementary Jevons index: J = (prod R_s)^(1/k) * base_value.
    5. Fallback for unmatched strata: If no matched strata exist, compute:
       J_fallback = (geom_mean(p_{s,t})) / (geom_mean(p_{s,0})) * base_value.

    Returns:
        (index_value, metadata_dict)
    """
    meta = {
        "n_current_obs": len(current_obs),
        "n_base_obs": len(base_obs),
        "matched_strata_count": 0,
        "is_fallback": False,
        "matched_strata": [],
    }

    if not current_obs or not base_obs:
        return None, meta

    # Group prices by stratum
    curr_strata: Dict[Tuple[str, str, str], List[float]] = defaultdict(list)
    base_strata: Dict[Tuple[str, str, str], List[float]] = defaultdict(list)

    for o in current_obs:
        p = extract_price(o, variant=variant)
        if p is not None:
            curr_strata[get_stratum_key(o)].append(p)

    for o in base_obs:
        p = extract_price(o, variant=variant)
        if p is not None:
            base_strata[get_stratum_key(o)].append(p)

    if not curr_strata or not base_strata:
        return None, meta

    # Geometric mean per stratum
    curr_strata_means = {k: geometric_mean(v) for k, v in curr_strata.items() if geometric_mean(v) is not None}
    base_strata_means = {k: geometric_mean(v) for k, v in base_strata.items() if geometric_mean(v) is not None}

    # Find matched strata
    matched_keys = set(curr_strata_means.keys()) & set(base_strata_means.keys())

    if matched_keys:
        # Standard matched Jevons index
        price_relatives = [curr_strata_means[k] / base_strata_means[k] for k in matched_keys]
        jevons_ratio = geometric_mean(price_relatives)
        if jevons_ratio is None:
            return None, meta

        meta["matched_strata_count"] = len(matched_keys)
        meta["matched_strata"] = [f"{k[0]}:{k[1]}:{k[2]}" for k in sorted(matched_keys)]
        index_val = jevons_ratio * base_value
        return index_val, meta

    else:
        # Fallback for unmatched strata: ratio of cell geometric means
        curr_all = list(curr_strata_means.values())
        base_all = list(base_strata_means.values())
        curr_geom = geometric_mean(curr_all)
        base_geom = geometric_mean(base_all)

        if curr_geom is None or base_geom is None or base_geom == 0:
            return None, meta

        meta["is_fallback"] = True
        meta["fallback_reason"] = "No exact stratum match (carrier+band+class) between periods; using cell geometric mean ratio"
        index_val = (curr_geom / base_geom) * base_value
        return index_val, meta


def aggregate_lead_times(
    lead_indices: Dict[int, Optional[float]],
    lead_weights: Dict[int, float],
    base_value: float = DEFAULT_BASE_VALUE,
) -> Tuple[Optional[float], Dict[str, Any]]:
    """
    Aggregate elementary indices across lead-time booking windows for a given route.
    Normalizes active weights dynamically so sum(w_l*) == 1.0.
    """
    present_leads = [l for l, idx in lead_indices.items() if idx is not None and l in lead_weights and lead_weights[l] > 0]
    total_expected = len(lead_weights)
    coverage = len(present_leads) / total_expected if total_expected > 0 else 0.0

    meta = {
        "present_lead_windows": sorted(present_leads),
        "expected_lead_windows": sorted(list(lead_weights.keys())),
        "coverage": coverage,
    }

    if not present_leads:
        return None, meta

    total_weight = sum(lead_weights[l] for l in present_leads)
    if total_weight <= 0:
        return None, meta

    weighted_sum = sum((lead_weights[l] / total_weight) * lead_indices[l] for l in present_leads)
    return weighted_sum, meta


def aggregate_routes(
    route_indices: Dict[str, Optional[float]],
    route_weights: Dict[str, float],
    base_value: float = DEFAULT_BASE_VALUE,
) -> Tuple[Optional[float], Dict[str, Any]]:
    """
    Aggregate route-level indices into the national composite APIx using DGCA passenger weights.
    Normalizes active weights dynamically so sum(w_r*) == 1.0.
    """
    present_routes = [r for r, idx in route_indices.items() if idx is not None and r in route_weights and route_weights[r] > 0]
    total_expected = len(route_weights)
    coverage = len(present_routes) / total_expected if total_expected > 0 else 0.0

    meta = {
        "present_routes": sorted(present_routes),
        "expected_routes": sorted(list(route_weights.keys())),
        "coverage": coverage,
    }

    if not present_routes:
        return None, meta

    total_weight = sum(route_weights[r] for r in present_routes)
    if total_weight <= 0:
        return None, meta

    weighted_sum = sum((route_weights[r] / total_weight) * route_indices[r] for r in present_routes)
    return weighted_sum, meta


def chain_link(
    current_index_with_new_weights: float,
    link_period_index_with_new_weights: float,
    link_period_index_chained: float,
) -> float:
    """
    Apply annual / periodic chain-linking formula when weight schedule changes:
    I_t^{chained} = I_{T_link}^{chained} * (I_t^{(k)} / I_{T_link}^{(k)})
    """
    if link_period_index_with_new_weights <= 0:
        return current_index_with_new_weights
    growth_factor = current_index_with_new_weights / link_period_index_with_new_weights
    return link_period_index_chained * growth_factor


# ─── Top-Level Pure Computation Result ─────────────────────────────────────────

@dataclass
class IndexResult:
    index_date: date
    frequency: str
    variant: str
    overall_apix: Optional[float]
    route_indices: Dict[str, Optional[float]]
    lead_indices: Dict[int, Optional[float]]
    cell_indices: Dict[Tuple[str, int], Optional[float]]
    n_obs: int
    cell_coverage: float
    is_synthetic: bool
    methodology_version: str
    metadata: Dict[str, Any] = field(default_factory=dict)


def compute_apix(
    current_observations: Sequence[Union[Dict[str, Any], Any]],
    base_observations: Sequence[Union[Dict[str, Any], Any]],
    route_weights: Dict[str, float],
    lead_weights: Dict[int, float],
    index_date: date,
    frequency: str = "daily",
    variant: str = "total_fare",
    base_value: float = DEFAULT_BASE_VALUE,
    allow_synthetic: bool = False,
    methodology_version: str = DEFAULT_METHODOLOGY_VERSION,
) -> IndexResult:
    """
    Pure top-level coordinator to compute APIx index from observations and weights.

    Enforces non-synthetic policy: raises ValueError if any observation is synthetic
    unless allow_synthetic=True.
    """
    def _is_syn(obs: Any) -> bool:
        if isinstance(obs, dict):
            return bool(obs.get("is_synthetic", False))
        return bool(getattr(obs, "is_synthetic", False))

    has_synthetic = any(_is_syn(o) for o in current_observations) or any(_is_syn(o) for o in base_observations)

    if has_synthetic and not allow_synthetic:
        raise ValueError(
            "Airfare observations contain synthetic data (is_synthetic=True). "
            "Index computation refused to preserve data integrity. Pass allow_synthetic=True to override."
        )

    # Effective variant name (stamped with _synthetic if synthetic data is allowed and present)
    effective_variant = f"{variant}_synthetic" if (has_synthetic and allow_synthetic) else variant

    def _get_route(obs: Any) -> str:
        if isinstance(obs, dict):
            return str(obs.get("route_code") or f"{obs.get('origin')}-{obs.get('destination')}").upper()
        if hasattr(obs, "route") and obs.route:
            return obs.route.route_code
        if hasattr(obs, "route_code") and obs.route_code:
            return obs.route_code
        return f"{getattr(obs, 'origin', '')}-{getattr(obs, 'destination', '')}".upper()

    def _get_lead(obs: Any) -> int:
        if isinstance(obs, dict):
            return int(obs.get("lead_days") or obs.get("target_lead_window") or 15)
        return int(getattr(obs, "lead_days", None) or getattr(obs, "target_lead_window", None) or 15)

    # Group current and base observations by (route, lead)
    curr_cells: Dict[Tuple[str, int], List[Any]] = defaultdict(list)
    base_cells: Dict[Tuple[str, int], List[Any]] = defaultdict(list)

    for o in current_observations:
        curr_cells[(_get_route(o), _get_lead(o))].append(o)

    for o in base_observations:
        base_cells[(_get_route(o), _get_lead(o))].append(o)

    cell_indices: Dict[Tuple[str, int], Optional[float]] = {}
    total_valid_cells = 0
    total_expected_cells = len(route_weights) * len(lead_weights)

    # 1. Compute elementary Jevons index for each (route, lead) cell
    for r in route_weights.keys():
        for l in lead_weights.keys():
            c_obs = curr_cells.get((r, l), [])
            b_obs = base_cells.get((r, l), [])
            cell_idx, _ = compute_elementary_jevons(c_obs, b_obs, variant=variant, base_value=base_value)
            cell_indices[(r, l)] = cell_idx
            if cell_idx is not None:
                total_valid_cells += 1

    cell_coverage = (total_valid_cells / total_expected_cells) if total_expected_cells > 0 else 0.0

    # 2. Lead-time aggregation per route
    route_indices: Dict[str, Optional[float]] = {}
    for r in route_weights.keys():
        r_lead_indices = {l: cell_indices.get((r, l)) for l in lead_weights.keys()}
        r_idx, _ = aggregate_lead_times(r_lead_indices, lead_weights, base_value=base_value)
        route_indices[r] = r_idx

    # Per-lead index across all routes
    lead_indices: Dict[int, Optional[float]] = {}
    for l in lead_weights.keys():
        l_route_indices = {r: cell_indices.get((r, l)) for r in route_weights.keys()}
        l_idx, _ = aggregate_routes(l_route_indices, route_weights, base_value=base_value)
        lead_indices[l] = l_idx

    # 3. Route aggregation for overall composite APIx
    overall_apix, _ = aggregate_routes(route_indices, route_weights, base_value=base_value)

    return IndexResult(
        index_date=index_date,
        frequency=frequency,
        variant=effective_variant,
        overall_apix=overall_apix,
        route_indices=route_indices,
        lead_indices=lead_indices,
        cell_indices=cell_indices,
        n_obs=len(current_observations),
        cell_coverage=cell_coverage,
        is_synthetic=has_synthetic,
        methodology_version=methodology_version,
    )


# ─── Service Layer ─────────────────────────────────────────────────────────────

class APIxIndexService:
    """
    Database service layer for computing and persisting APIx indices.
    """

    def __init__(self, session: Session, base_year: int = 2024, methodology_version: str = DEFAULT_METHODOLOGY_VERSION):
        self.session = session
        self.base_year = base_year
        self.methodology_version = methodology_version

    def get_active_lead_weights(self, for_date: date) -> Dict[int, float]:
        """Load active lead-time weights for a given date from DB or fallback YAML."""
        weights = (
            self.session.query(LeadTimeWeight)
            .filter(
                LeadTimeWeight.is_active == True,
                LeadTimeWeight.valid_from <= for_date,
                (LeadTimeWeight.valid_to == None) | (LeadTimeWeight.valid_to >= for_date),
            )
            .all()
        )
        if weights:
            return {w.lead_days: float(w.weight) for w in weights}

        # Fallback to config file
        cfg_path = Path("config/lead_time_weights.yaml")
        if cfg_path.exists():
            with open(cfg_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                return {item["lead_days"]: float(item["weight"]) for item in data.get("lead_time_weights", [])}

        # Equal weights fallback
        return {1: 0.20, 7: 0.20, 15: 0.20, 30: 0.20, 45: 0.20}

    def get_active_route_weights(self, for_date: date) -> Dict[str, float]:
        """Load active route weights for a given date from DB or fallback CSV."""
        weights = (
            self.session.query(RouteWeight)
            .join(Route)
            .filter(
                RouteWeight.is_active == True,
                RouteWeight.valid_from <= for_date,
                (RouteWeight.valid_to == None) | (RouteWeight.valid_to >= for_date),
            )
            .all()
        )
        if weights:
            return {w.route.route_code: float(w.weight) for w in weights if w.route}

        # Fallback to reference CSV
        csv_path = Path("data/reference/dgca_city_pair_traffic.csv")
        if csv_path.exists():
            import pandas as pd
            df = pd.read_csv(csv_path)
            total_pax = df["annual_passengers"].sum()
            return {row["route_code"]: float(row["annual_passengers"] / total_pax) for _, row in df.iterrows()}

        return {
            "BOM-DEL": 0.25,
            "DEL-BOM": 0.25,
            "DEL-BLR": 0.25,
            "BOM-BLR": 0.25,
        }

    def load_observations_for_date(
        self,
        target_date: date,
        frequency: str = "daily",
        allow_synthetic: bool = False,
    ) -> List[AirfareObservation]:
        """Query validated observations from the database for the given period."""
        if frequency == "daily":
            start_date = target_date
            end_date = target_date
        elif frequency == "weekly":
            start_date = target_date - timedelta(days=6)
            end_date = target_date
        elif frequency == "monthly":
            start_date = target_date.replace(day=1)
            end_date = target_date
        else:
            raise ValueError(f"Unsupported frequency '{frequency}'")

        query = (
            self.session.query(AirfareObservation)
            .join(Route)
            .filter(
                AirfareObservation.status == "valid",
                AirfareObservation.travel_date >= start_date,
                AirfareObservation.travel_date <= end_date,
            )
        )

        if not allow_synthetic:
            query = query.filter(AirfareObservation.is_synthetic == False)

        return query.all()

    def load_base_observations(self, allow_synthetic: bool = False) -> List[AirfareObservation]:
        """
        Query baseline period observations.
        If no distinct base period exists, returns clean observations from base_year or earliest available date.
        """
        query = (
            self.session.query(AirfareObservation)
            .join(Route)
            .filter(AirfareObservation.status == "valid")
        )

        if not allow_synthetic:
            query = query.filter(AirfareObservation.is_synthetic == False)

        # Look for base year
        base_obs = query.filter(AirfareObservation.collection_date >= date(self.base_year, 1, 1)).limit(5000).all()
        if not base_obs:
            base_obs = query.limit(5000).all()
        return base_obs

    def compute_and_store(
        self,
        index_date: date,
        frequency: str = "daily",
        variant: str = "total_fare",
        allow_synthetic: bool = False,
        base_value: float = DEFAULT_BASE_VALUE,
    ) -> IndexResult:
        """
        Full service method to compute the APIx index and persist it to index_values table.
        """
        curr_obs = self.load_observations_for_date(index_date, frequency=frequency, allow_synthetic=allow_synthetic)
        base_obs = self.load_base_observations(allow_synthetic=allow_synthetic)

        route_weights = self.get_active_route_weights(index_date)
        lead_weights = self.get_active_lead_weights(index_date)

        result = compute_apix(
            current_observations=curr_obs,
            base_observations=base_obs,
            route_weights=route_weights,
            lead_weights=lead_weights,
            index_date=index_date,
            frequency=frequency,
            variant=variant,
            base_value=base_value,
            allow_synthetic=allow_synthetic,
            methodology_version=self.methodology_version,
        )

        # Store overall index value
        if result.overall_apix is not None:
            self._upsert_index_value(
                index_date=index_date,
                frequency=frequency,
                variant=result.variant,
                apix_value=result.overall_apix,
                n_obs=result.n_obs,
                coverage=result.cell_coverage,
            )

        # Store route-level variant indices
        for r_code, r_val in result.route_indices.items():
            if r_val is not None:
                r_variant = f"route_{r_code}"
                if result.is_synthetic and allow_synthetic:
                    r_variant += "_synthetic"
                self._upsert_index_value(
                    index_date=index_date,
                    frequency=frequency,
                    variant=r_variant,
                    apix_value=r_val,
                    n_obs=result.n_obs,
                    coverage=result.cell_coverage,
                )

        self.session.commit()
        return result

    def _upsert_index_value(
        self,
        index_date: date,
        frequency: str,
        variant: str,
        apix_value: float,
        n_obs: int,
        coverage: float,
    ) -> IndexValue:
        """Insert or update a row in index_values table."""
        existing = (
            self.session.query(IndexValue)
            .filter(
                IndexValue.index_date == index_date,
                IndexValue.frequency == frequency,
                IndexValue.variant == variant,
                IndexValue.methodology_version == self.methodology_version,
            )
            .first()
        )

        if existing:
            existing.apix_value = Decimal(str(round(apix_value, 4)))
            existing.n_obs = n_obs
            existing.coverage = Decimal(str(round(coverage, 4)))
            return existing
        else:
            row = IndexValue(
                index_date=index_date,
                frequency=frequency,
                variant=variant,
                apix_value=Decimal(str(round(apix_value, 4))),
                methodology_version=self.methodology_version,
                n_obs=n_obs,
                coverage=Decimal(str(round(coverage, 4))),
            )
            self.session.add(row)
            return row


# ─── CLI Entrypoint ───────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Compute APIx Airfare Price Index.")
    parser.add_argument("--date", type=str, default=datetime.now().strftime("%Y-%m-%d"), help="Index calculation date (YYYY-MM-DD)")
    parser.add_argument("--frequency", type=str, default="daily", choices=FREQUENCIES, help="Index frequency")
    parser.add_argument("--variant", type=str, default="total_fare", choices=VARIANTS, help="Fare decomposition variant")
    parser.add_argument("--allow-synthetic", action="store_true", help="Allow computation from synthetic observations (appends _synthetic suffix)")
    parser.add_argument("--base-value", type=float, default=DEFAULT_BASE_VALUE, help="Base index value (default 100.0)")
    parser.add_argument("--dry-run", action="store_true", help="Compute index without persisting to database")
    args = parser.parse_args()

    calc_date = datetime.strptime(args.date, "%Y-%m-%d").date()

    with get_db_session() as session:
        service = APIxIndexService(session)
        print(f"\n=======================================================")
        print(f" Computing APIx Price Index: {calc_date} ({args.frequency.upper()})")
        print(f" Variant: {args.variant} | Base: {args.base_value} | Allow Synthetic: {args.allow_synthetic}")
        print(f"=======================================================\n")

        if args.dry_run:
            curr_obs = service.load_observations_for_date(calc_date, frequency=args.frequency, allow_synthetic=args.allow_synthetic)
            base_obs = service.load_base_observations(allow_synthetic=args.allow_synthetic)
            route_weights = service.get_active_route_weights(calc_date)
            lead_weights = service.get_active_lead_weights(calc_date)

            res = compute_apix(
                current_observations=curr_obs,
                base_observations=base_obs,
                route_weights=route_weights,
                lead_weights=lead_weights,
                index_date=calc_date,
                frequency=args.frequency,
                variant=args.variant,
                base_value=args.base_value,
                allow_synthetic=args.allow_synthetic,
            )
        else:
            res = service.compute_and_store(
                index_date=calc_date,
                frequency=args.frequency,
                variant=args.variant,
                allow_synthetic=args.allow_synthetic,
                base_value=args.base_value,
            )

        print(f"Overall APIx Value: {res.overall_apix:.4f}" if res.overall_apix is not None else "Overall APIx Value: N/A (Insufficient Data)")
        print(f"Observations: {res.n_obs} | Cell Coverage: {res.cell_coverage * 100:.1f}%")
        print(f"Variant Stamped: '{res.variant}'")
        print("\nRoute Sub-Indices:")
        for r, val in sorted(res.route_indices.items()):
            print(f"  {r}: {val:.2f}" if val is not None else f"  {r}: N/A")
        print()


if __name__ == "__main__":
    main()
