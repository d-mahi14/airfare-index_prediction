"""
processing/cleaning.py
Composable, tested data cleaning and quality pipeline for domestic airfare price index.

Operations:
  1. Synthetic data filtering (operates on non-synthetic data by default; flag to include synthetic).
  2. Deduplication on unique key: (source_name, flight_number, travel_date, fare_class, collection_date),
     keeping the latest scrape timestamp.
  3. Fare decomposition consistency check (base_fare + taxes + udf_psf + convenience_fee + other_fees == total_fare).
  4. Sold-out & cancellation tracking: retained with flags, excluded from price index stats, route-level shares reported.
  5. Outlier flagging per (route, target_lead_window, carrier) using median +/- k*MAD (k configurable) plus hard floor/cap.
     Outliers are flagged (is_outlier=True) and never deleted.
  6. Missing grid cells: carry forward max 2 days, then impute from the cell historical median/mean;
     sets is_imputed=True on every imputed record.
  7. Output: Produces clean_fares dataset/view and a per-run DataQualityReport (JSON + Markdown).
"""
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
import json
import logging
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple
from zoneinfo import ZoneInfo

from backend.app.schemas.airfare import AirfareObservationCreate

logger = logging.getLogger(__name__)
KOLKATA_TZ = ZoneInfo("Asia/Kolkata")


# ---------------------------------------------------------------------------
# Configuration & Report Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class CleaningConfig:
    """Configuration options for data cleaning and imputation pipeline."""
    include_synthetic: bool = False
    k_mad: float = 3.0
    min_fare_floor: Decimal = Decimal("500.00")
    max_fare_cap: Decimal = Decimal("150000.00")
    max_carry_forward_days: int = 2
    fee_tolerance: Decimal = Decimal("0.05")
    target_lead_windows: List[int] = field(default_factory=lambda: [1, 7, 15, 30, 45])


@dataclass
class DataQualityReport:
    """Detailed audit report metrics produced per cleaning run."""
    run_timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    target_collection_date: Optional[str] = None
    include_synthetic: bool = False
    total_input_records: int = 0
    synthetic_records_filtered: int = 0
    candidate_records: int = 0
    dedup_duplicates_dropped: int = 0
    fare_inconsistencies_flagged: int = 0
    sold_out_count: int = 0
    cancelled_count: int = 0
    outliers_flagged: int = 0
    cells_attempted: int = 0
    cells_present: int = 0
    cells_missing: int = 0
    cells_carried_forward: int = 0
    cells_imputed_fallback: int = 0
    cells_unimputed_exceeded_limit: int = 0
    clean_fares_count: int = 0
    route_sold_out_stats: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    counts_per_step: Dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert quality report to dictionary."""
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        """Serialize quality report to formatted JSON string."""
        return json.dumps(self.to_dict(), indent=indent, default=str)

    def to_markdown(self) -> str:
        """Format quality report as GitHub Markdown document."""
        lines = [
            "# APIx Data Quality & Cleaning Audit Report",
            "",
            f"> **Run Timestamp**: `{self.run_timestamp}`  ",
            f"> **Collection Date**: `{self.target_collection_date or 'N/A'}`  ",
            f"> **Mode**: `{'Includes Synthetic' if self.include_synthetic else 'Real/Non-Synthetic Only'}`  ",
            "",
            "---",
            "",
            "## 1. Pipeline Execution Step Summary",
            "",
            "| Pipeline Step | Metric Description | Count / Value |",
            "| :--- | :--- | :--- |",
            f"| **1. Input** | Total Input Records Received | `{self.total_input_records}` |",
            f"| **2. Synthetic Filter** | Synthetic Records Filtered Out | `{self.synthetic_records_filtered}` |",
            f"| **3. Deduplication** | Duplicate Observations Dropped | `{self.dedup_duplicates_dropped}` |",
            f"| **4. Fare Decomposition** | Fee Breakdown Inconsistencies | `{self.fare_inconsistencies_flagged}` |",
            f"| **5. Availability Tracking** | Sold-Out Quotes Retained | `{self.sold_out_count}` |",
            f"| | Cancelled Quotes Retained | `{self.cancelled_count}` |",
            f"| **6. Outlier Detection** | Statistical Outliers Flagged (MAD/Bounds) | `{self.outliers_flagged}` |",
            f"| **7. Imputation** | Grid Cells Attempted | `{self.cells_attempted}` |",
            f"| | Grid Cells Populated Directly | `{self.cells_present}` |",
            f"| | Grid Cells Missing | `{self.cells_missing}` |",
            f"| | Missing Cells Carried Forward (≤2 days) | `{self.cells_carried_forward}` |",
            f"| | Missing Cells Imputed via Fallback (>2 days) | `{self.cells_imputed_fallback}` |",
            f"| **8. Clean Fares** | **Final Usable Clean Fares for Price Index** | **`{self.clean_fares_count}`** |",
            "",
            "---",
            "",
            "## 2. Route Sold-Out & Availability Statistics",
            "",
            "| Route | Total Quotes | Available | Sold Out | Cancelled | Sold-Out Share |",
            "| :--- | :--- | :--- | :--- | :--- | :--- |",
        ]

        if not self.route_sold_out_stats:
            lines.append("| *No route data* | - | - | - | - | 0.0% |")
        else:
            for route, stats in sorted(self.route_sold_out_stats.items()):
                tot = stats.get("total", 0)
                avail = stats.get("available", 0)
                sold = stats.get("sold_out", 0)
                canc = stats.get("cancelled", 0)
                share = stats.get("sold_out_share", 0.0)
                lines.append(f"| **{route}** | {tot} | {avail} | {sold} | {canc} | **{share:.1%}** |")

        lines.extend([
            "",
            "---",
            "",
            "> *Integrity Note: Outliers and sold-out quotes are preserved with boolean flags and never deleted from the underlying dataset.*",
        ])

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Generic Record Accessor Helpers
# ---------------------------------------------------------------------------

def _get_attr(item: Any, name: str, default: Any = None) -> Any:
    """Retrieve attribute or dict key seamlessly."""
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


def _set_attr(item: Any, name: str, value: Any) -> None:
    """Set attribute or dict key seamlessly."""
    if isinstance(item, dict):
        item[name] = value
    else:
        try:
            setattr(item, name, value)
        except Exception:
            pass


def _get_route_code(item: Any) -> str:
    """Extract canonical route code like 'BOM-DEL'."""
    rc = _get_attr(item, "route_code")
    if rc:
        return str(rc).strip().upper()
    origin = _get_attr(item, "origin", "")
    dest = _get_attr(item, "destination", "")
    if origin and dest:
        return f"{origin.strip().upper()}-{dest.strip().upper()}"
    return "UNKNOWN-ROUTE"


def _get_carrier_code(item: Any) -> str:
    """Extract carrier code or name."""
    iata = _get_attr(item, "airline_iata")
    if iata:
        return str(iata).strip().upper()
    name = _get_attr(item, "airline_name")
    if name:
        return str(name).strip()
    return "UNKNOWN-CARRIER"


def _to_decimal(val: Any) -> Optional[Decimal]:
    """Safely convert numeric/string value to Decimal."""
    if val is None:
        return None
    if isinstance(val, Decimal):
        return val
    try:
        return Decimal(str(val))
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Step 1: Synthetic Data Filter
# ---------------------------------------------------------------------------

def filter_synthetic(
    records: List[Any],
    include_synthetic: bool = False,
) -> Tuple[List[Any], int]:
    """
    Filter records by synthetic flag.
    By default (include_synthetic=False), operates strictly on non-synthetic data.
    Returns (filtered_records, filtered_out_count).
    """
    if include_synthetic:
        return list(records), 0

    retained = []
    filtered_count = 0
    for r in records:
        is_synth = bool(_get_attr(r, "is_synthetic", False))
        if is_synth:
            filtered_count += 1
        else:
            retained.append(r)

    return retained, filtered_count


# ---------------------------------------------------------------------------
# Step 2: Deduplication on Unique Key
# ---------------------------------------------------------------------------

def deduplicate_observations(
    records: List[Any],
) -> Tuple[List[Any], int]:
    """
    Deduplicate observations on the canonical 5-tuple unique key:
      (source_name, flight_number, travel_date, fare_class, collection_date)

    When duplicates are encountered, preserves the one with the latest collection_timestamp.
    Returns (deduped_records, dropped_duplicates_count).
    """
    seen: Dict[Tuple[str, Optional[str], date, str, date], Tuple[datetime, Any]] = {}
    dropped_count = 0

    for r in records:
        source_name = str(_get_attr(r, "source_name", "")).strip().lower()
        flight_number = _get_attr(r, "flight_number")
        flight_number = str(flight_number).strip().upper() if flight_number else None
        
        travel_dt = _get_attr(r, "travel_date")
        if isinstance(travel_dt, str):
            travel_dt = datetime.strptime(travel_dt, "%Y-%m-%d").date()

        fare_class = str(_get_attr(r, "fare_class", "Economy")).strip().capitalize()

        col_dt = _get_attr(r, "collection_date")
        if col_dt is None:
            ts = _get_attr(r, "collection_timestamp")
            if ts:
                col_dt = ts.astimezone(KOLKATA_TZ).date() if hasattr(ts, "astimezone") else ts.date()
            else:
                col_dt = date.today()
        elif isinstance(col_dt, str):
            col_dt = datetime.strptime(col_dt, "%Y-%m-%d").date()

        key = (source_name, flight_number, travel_dt, fare_class, col_dt)

        ts = _get_attr(r, "collection_timestamp") or datetime.min.replace(tzinfo=timezone.utc)
        if hasattr(ts, "tzinfo") and ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)

        if key in seen:
            prev_ts, prev_rec = seen[key]
            dropped_count += 1
            if ts >= prev_ts:
                seen[key] = (ts, r)
        else:
            seen[key] = (ts, r)

    deduped = [rec for ts, rec in seen.values()]
    return deduped, dropped_count


# ---------------------------------------------------------------------------
# Step 3: Fare Decomposition Consistency Check
# ---------------------------------------------------------------------------

def check_fare_decomposition(
    records: List[Any],
    tolerance: Decimal = Decimal("0.05"),
) -> Tuple[List[Any], int]:
    """
    Verify mathematical consistency:
      total_fare == base_fare + taxes + udf_psf + convenience_fee + other_fees (+/- tolerance)

    Flag inconsistencies in the data quality report.
    Returns (records, inconsistency_count).
    """
    inconsistent_count = 0

    for r in records:
        tot = _to_decimal(_get_attr(r, "total_fare"))
        base = _to_decimal(_get_attr(r, "base_fare"))
        taxes = _to_decimal(_get_attr(r, "taxes")) or Decimal("0.00")
        udf_psf = _to_decimal(_get_attr(r, "udf_psf")) or Decimal("0.00")
        conv = _to_decimal(_get_attr(r, "convenience_fee")) or Decimal("0.00")
        other = _to_decimal(_get_attr(r, "other_fees")) or Decimal("0.00")

        if tot is not None and base is not None:
            comp_sum = base + taxes + udf_psf + conv + other
            if abs(tot - comp_sum) > tolerance:
                inconsistent_count += 1
                logger.debug(
                    f"Fare decomposition mismatch for flight {_get_attr(r, 'flight_number')}: "
                    f"total={tot} != sum={comp_sum}"
                )

    return records, inconsistent_count


# ---------------------------------------------------------------------------
# Step 4: Sold-Out & Cancellation Tracking
# ---------------------------------------------------------------------------

def track_sold_out_and_cancelled(
    records: List[Any],
) -> Tuple[List[Any], int, int, Dict[str, Dict[str, Any]]]:
    """
    Detect and track sold-out and cancelled quotes.
    These observations are retained in the dataset with flags set,
    and route-level availability statistics are compiled.

    Returns (records, total_sold_out, total_cancelled, route_stats).
    """
    total_sold_out = 0
    total_cancelled = 0
    route_stats: Dict[str, Dict[str, int]] = {}

    for r in records:
        route = _get_route_code(r)
        if route not in route_stats:
            route_stats[route] = {
                "total": 0,
                "available": 0,
                "sold_out": 0,
                "cancelled": 0,
            }

        route_stats[route]["total"] += 1

        is_sold_out = bool(_get_attr(r, "is_sold_out", False))
        avail = str(_get_attr(r, "availability", "available")).strip().lower()

        if is_sold_out or avail == "sold_out":
            total_sold_out += 1
            route_stats[route]["sold_out"] += 1
            _set_attr(r, "is_sold_out", True)
            _set_attr(r, "availability", "sold_out")
        elif avail == "cancelled":
            total_cancelled += 1
            route_stats[route]["cancelled"] += 1
            _set_attr(r, "availability", "cancelled")
        else:
            route_stats[route]["available"] += 1

    # Compute shares
    compiled_route_stats: Dict[str, Dict[str, Any]] = {}
    for route, counts in route_stats.items():
        tot = counts["total"]
        sold = counts["sold_out"]
        canc = counts["cancelled"]
        avail = counts["available"]
        share = (sold / tot) if tot > 0 else 0.0
        compiled_route_stats[route] = {
            "total": tot,
            "available": avail,
            "sold_out": sold,
            "cancelled": canc,
            "sold_out_share": round(share, 4),
        }

    return records, total_sold_out, total_cancelled, compiled_route_stats


# ---------------------------------------------------------------------------
# Step 5: Outlier Flagging via Median Absolute Deviation (MAD)
# ---------------------------------------------------------------------------

def _compute_median(values: List[Decimal]) -> Decimal:
    """Compute exact median of a list of Decimals."""
    s = sorted(values)
    n = len(s)
    if n == 0:
        return Decimal("0.00")
    if n % 2 == 1:
        return s[n // 2]
    return (s[n // 2 - 1] + s[n // 2]) / Decimal("2.0")


def flag_outliers_mad(
    records: List[Any],
    k_mad: float = 3.0,
    min_fare_floor: Decimal = Decimal("500.00"),
    max_fare_cap: Decimal = Decimal("150000.00"),
) -> Tuple[List[Any], int]:
    """
    Outlier flagging per (route, target_lead_window, carrier) group using:
      [median - k*MAD, median + k*MAD] bounded by [min_fare_floor, max_fare_cap].

    Notes:
      - MAD = median(|x_i - median(X)|)
      - Fares outside the bounds have is_outlier set to True.
      - Outlier records are NEVER deleted.
      - Single observations (N=1) are checked against hard floor/cap.
      - If MAD == 0 (identical fares), only hard floor/cap bounds are applied.

    Returns (records, flagged_outliers_count).
    """
    # Group active candidate records by (route, target_lead_window, carrier)
    groups: Dict[Tuple[str, Optional[int], str], List[Any]] = {}

    for r in records:
        # Sold-out and cancelled quotes are excluded from outlier calculation
        is_sold_out = bool(_get_attr(r, "is_sold_out", False))
        avail = str(_get_attr(r, "availability", "available")).strip().lower()
        if is_sold_out or avail in ("sold_out", "cancelled"):
            continue

        route = _get_route_code(r)
        window = _get_attr(r, "target_lead_window")
        carrier = _get_carrier_code(r)
        key = (route, window, carrier)

        if key not in groups:
            groups[key] = []
        groups[key].append(r)

    flagged_count = 0
    k_dec = Decimal(str(k_mad))

    for key, group_records in groups.items():
        fares: List[Decimal] = []
        for r in group_records:
            f = _to_decimal(_get_attr(r, "total_fare"))
            if f is not None:
                fares.append(f)

        if not fares:
            continue

        # 1. Compute Median
        med = _compute_median(fares)

        # 2. Compute MAD
        abs_deviations = [abs(x - med) for x in fares]
        mad = _compute_median(abs_deviations)

        # 3. Calculate Bounds
        if mad > Decimal("0.00"):
            lower_bound = max(min_fare_floor, med - (k_dec * mad))
            upper_bound = min(max_fare_cap, med + (k_dec * mad))
        else:
            # Zero dispersion (e.g. N=1 or all identical fares)
            lower_bound = min_fare_floor
            upper_bound = max_fare_cap

        # 4. Apply Outlier Flags
        for r in group_records:
            fare = _to_decimal(_get_attr(r, "total_fare"))
            if fare is None:
                continue

            if fare < lower_bound or fare > upper_bound:
                _set_attr(r, "is_outlier", True)
                flagged_count += 1
            else:
                # Keep existing false or ensure false
                if _get_attr(r, "is_outlier") is None:
                    _set_attr(r, "is_outlier", False)

    return records, flagged_count


# ---------------------------------------------------------------------------
# Step 6: Missing Grid Cell Imputation (Carry Forward & Cell Fallback)
# ---------------------------------------------------------------------------

def _clone_record(
    record: Any,
    new_collection_date: date,
    new_timestamp: datetime,
) -> Any:
    """Create a clean copy of an observation with updated date and is_imputed=True."""
    if isinstance(record, AirfareObservationCreate):
        data = record.model_dump()
        data["collection_date"] = new_collection_date
        data["collection_timestamp"] = new_timestamp
        data["is_imputed"] = True
        data["lead_days"] = (data["travel_date"] - new_collection_date).days
        return AirfareObservationCreate(**data)
    elif isinstance(record, dict):
        d = deepcopy(record)
        d["collection_date"] = new_collection_date
        d["collection_timestamp"] = new_timestamp
        d["is_imputed"] = True
        travel_dt = d.get("travel_date")
        if isinstance(travel_dt, str):
            travel_dt = datetime.strptime(travel_dt, "%Y-%m-%d").date()
        if travel_dt:
            d["lead_days"] = (travel_dt - new_collection_date).days
        return d
    else:
        # Generic object / ORM model
        c = deepcopy(record)
        _set_attr(c, "collection_date", new_collection_date)
        _set_attr(c, "collection_timestamp", new_timestamp)
        _set_attr(c, "is_imputed", True)
        return c


def impute_missing_cells(
    current_records: List[Any],
    historical_records_by_date: Optional[Dict[date, List[Any]]],
    target_date: date,
    grid_cells: Optional[List[Tuple[str, int, str]]] = None,
    max_carry_forward_days: int = 2,
) -> Tuple[List[Any], int, int, int, int, int]:
    """
    Detect missing grid cells (route, target_lead_window, carrier) on target_date:
      1. Carry forward valid quotes from t-1 or t-2 (up to max_carry_forward_days=2).
      2. If missing for >2 days, impute from cell historical median/mean across earlier days.
      3. Sets is_imputed=True on every generated observation.

    Returns:
      (all_records_including_imputed, attempted, present, carried_forward, fallback_imputed, un_imputable)
    """
    history = historical_records_by_date or {}

    # Map current valid records to cells
    current_cell_map: Dict[Tuple[str, int, str], List[Any]] = {}
    for r in current_records:
        route = _get_route_code(r)
        window = _get_attr(r, "target_lead_window") or 1
        carrier = _get_carrier_code(r)
        cell_key = (route, window, carrier)

        if cell_key not in current_cell_map:
            current_cell_map[cell_key] = []
        current_cell_map[cell_key].append(r)

    # Determine universe of cells to audit
    target_cells: Set[Tuple[str, int, str]] = set()
    if grid_cells:
        target_cells.update(grid_cells)
    else:
        target_cells.update(current_cell_map.keys())
        for past_records in history.values():
            for r in past_records:
                target_cells.add((_get_route_code(r), _get_attr(r, "target_lead_window") or 1, _get_carrier_code(r)))

    cells_attempted = len(target_cells)
    cells_present = 0
    cells_carried_forward = 0
    cells_fallback_imputed = 0
    cells_unimputed = 0

    imputed_records: List[Any] = []
    now_ts = datetime.now(timezone.utc)

    for cell in sorted(target_cells):
        route, window, carrier = cell
        existing = current_cell_map.get(cell, [])

        # Check if cell has at least one valid, non-outlier quote today
        valid_today = [
            r for r in existing
            if not bool(_get_attr(r, "is_outlier", False)) and not bool(_get_attr(r, "is_sold_out", False))
        ]

        if valid_today:
            cells_present += 1
            continue

        # Cell is missing valid quote today -> attempt carry forward
        found_carry_forward = False

        for delta_days in range(1, max_carry_forward_days + 1):
            past_date = target_date - timedelta(days=delta_days)
            past_records = history.get(past_date, [])

            past_cell_records = [
                r for r in past_records
                if _get_route_code(r) == route
                and (_get_attr(r, "target_lead_window") or 1) == window
                and _get_carrier_code(r) == carrier
                and not bool(_get_attr(r, "is_outlier", False))
                and not bool(_get_attr(r, "is_sold_out", False))
            ]

            if past_cell_records:
                # Carry forward the best available record from past_date
                source_record = past_cell_records[0]
                cloned = _clone_record(source_record, target_date, now_ts)
                imputed_records.append(cloned)
                cells_carried_forward += 1
                found_carry_forward = True
                break

        if found_carry_forward:
            continue

        # If missing for > max_carry_forward_days, impute from cell historical median across earlier days
        all_past_fares: List[Decimal] = []
        sample_past_record = None

        for past_date, past_records in sorted(history.items()):
            for r in past_records:
                if (
                    _get_route_code(r) == route
                    and (_get_attr(r, "target_lead_window") or 1) == window
                    and _get_carrier_code(r) == carrier
                    and not bool(_get_attr(r, "is_outlier", False))
                ):
                    f = _to_decimal(_get_attr(r, "total_fare"))
                    if f is not None:
                        all_past_fares.append(f)
                    if sample_past_record is None:
                        sample_past_record = r

        if all_past_fares and sample_past_record is not None:
            imputed_fare = _compute_median(all_past_fares)
            cloned = _clone_record(sample_past_record, target_date, now_ts)
            _set_attr(cloned, "total_fare", imputed_fare)
            _set_attr(cloned, "base_fare", imputed_fare * Decimal("0.85"))
            _set_attr(cloned, "taxes", imputed_fare * Decimal("0.05"))
            _set_attr(cloned, "udf_psf", imputed_fare * Decimal("0.05"))
            _set_attr(cloned, "convenience_fee", imputed_fare * Decimal("0.05"))
            _set_attr(cloned, "other_fees", Decimal("0.00"))
            _set_attr(cloned, "is_imputed", True)
            imputed_records.append(cloned)
            cells_fallback_imputed += 1
        else:
            # Completely empty cell with zero prior history
            cells_unimputed += 1

    combined = list(current_records) + imputed_records
    return (
        combined,
        cells_attempted,
        cells_present,
        cells_carried_forward,
        cells_fallback_imputed,
        cells_unimputed,
    )


# ---------------------------------------------------------------------------
# High-Level Pipeline Orchestrator
# ---------------------------------------------------------------------------

def clean_airfare_dataset(
    records: List[Any],
    historical_records_by_date: Optional[Dict[date, List[Any]]] = None,
    target_date: Optional[date] = None,
    grid_cells: Optional[List[Tuple[str, int, str]]] = None,
    config: Optional[CleaningConfig] = None,
) -> Tuple[List[Any], List[Any], DataQualityReport]:
    """
    Execute complete end-to-end airfare data cleaning pipeline:
      Step 1: Synthetic filter (default: False)
      Step 2: Deduplication on unique key
      Step 3: Fare decomposition check
      Step 4: Sold-out & cancellation tracking (retention + route shares)
      Step 5: Outlier detection (median +/- k*MAD + hard floor/cap)
      Step 6: Missing cell imputation (carry-forward <=2 days, cell median fallback)
      Step 7: Clean fares dataset compilation & quality report generation

    Returns:
      (all_enriched_records, clean_fares, quality_report)
    """
    cfg = config or CleaningConfig()
    effective_date = target_date or date.today()

    total_input = len(records)

    # Step 1: Synthetic filter
    step1_records, synth_filtered = filter_synthetic(records, include_synthetic=cfg.include_synthetic)

    # Step 2: Deduplication
    step2_records, dups_dropped = deduplicate_observations(step1_records)

    # Step 3: Fare decomposition check
    step3_records, fare_inconsistencies = check_fare_decomposition(step2_records, tolerance=cfg.fee_tolerance)

    # Step 4: Sold-out & cancellation tracking
    step4_records, total_sold_out, total_cancelled, route_stats = track_sold_out_and_cancelled(step3_records)

    # Step 5: Outlier detection
    step5_records, outliers_flagged = flag_outliers_mad(
        step4_records,
        k_mad=cfg.k_mad,
        min_fare_floor=cfg.min_fare_floor,
        max_fare_cap=cfg.max_fare_cap,
    )

    # Step 6: Missing cell imputation
    (
        all_records,
        cells_attempted,
        cells_present,
        cells_cf,
        cells_fallback,
        cells_unimputed,
    ) = impute_missing_cells(
        current_records=step5_records,
        historical_records_by_date=historical_records_by_date,
        target_date=effective_date,
        grid_cells=grid_cells,
        max_carry_forward_days=cfg.max_carry_forward_days,
    )

    # Step 7: Compile Clean Fares (Valid, Non-Outlier, Non-Sold-Out, Available)
    clean_fares: List[Any] = []
    for r in all_records:
        is_outlier = bool(_get_attr(r, "is_outlier", False))
        is_sold_out = bool(_get_attr(r, "is_sold_out", False))
        avail = str(_get_attr(r, "availability", "available")).strip().lower()

        if not is_outlier and not is_sold_out and avail in ("available", ""):
            clean_fares.append(r)

    # Compile Quality Report
    report = DataQualityReport(
        target_collection_date=effective_date.isoformat(),
        include_synthetic=cfg.include_synthetic,
        total_input_records=total_input,
        synthetic_records_filtered=synth_filtered,
        candidate_records=len(step1_records),
        dedup_duplicates_dropped=dups_dropped,
        fare_inconsistencies_flagged=fare_inconsistencies,
        sold_out_count=total_sold_out,
        cancelled_count=total_cancelled,
        outliers_flagged=outliers_flagged,
        cells_attempted=cells_attempted,
        cells_present=cells_present,
        cells_missing=cells_attempted - cells_present if cells_attempted >= cells_present else 0,
        cells_carried_forward=cells_cf,
        cells_imputed_fallback=cells_fallback,
        cells_unimputed_exceeded_limit=cells_unimputed,
        clean_fares_count=len(clean_fares),
        route_sold_out_stats=route_stats,
        counts_per_step={
            "input": total_input,
            "after_synthetic_filter": len(step1_records),
            "after_dedup": len(step2_records),
            "sold_out": total_sold_out,
            "cancelled": total_cancelled,
            "outliers": outliers_flagged,
            "imputed_carried_forward": cells_cf,
            "imputed_fallback": cells_fallback,
            "clean_fares": len(clean_fares),
        },
    )

    return all_records, clean_fares, report


# ---------------------------------------------------------------------------
# Database View Helper
# ---------------------------------------------------------------------------

def create_clean_fares_db_view(session: Any) -> None:
    """
    Execute SQL statement to ensure the clean_fares database view exists in PostgreSQL.
    """
    import sqlalchemy as sa
    sql = """
    CREATE OR REPLACE VIEW clean_fares AS
    SELECT 
        obs.id,
        obs.collection_run_id,
        obs.collection_timestamp,
        obs.collection_date,
        obs.source_id,
        obs.route_id,
        obs.airline_id,
        obs.flight_number,
        obs.travel_date,
        obs.lead_days,
        obs.fare_class,
        obs.base_fare,
        obs.taxes,
        obs.udf_psf,
        obs.convenience_fee,
        obs.other_fees,
        obs.total_fare,
        obs.currency,
        obs.dep_time,
        obs.dep_band,
        obs.stops,
        obs.duration_min,
        obs.is_sold_out,
        obs.seats_left,
        obs.availability,
        obs.status,
        obs.is_synthetic,
        obs.target_lead_window,
        obs.is_outlier,
        obs.is_imputed,
        obs.created_at,
        r.route_code,
        r.origin,
        r.destination,
        a.name AS airline_name_resolved,
        a.iata_code AS airline_iata_resolved,
        s.name AS source_name_resolved
    FROM airfare_observations obs
    JOIN routes r ON obs.route_id = r.id
    LEFT JOIN airlines a ON obs.airline_id = a.id
    JOIN sources s ON obs.source_id = s.id
    WHERE obs.status = 'valid'
      AND obs.is_outlier = FALSE
      AND obs.is_sold_out = FALSE
      AND (obs.availability IS NULL OR obs.availability = 'available');
    """
    session.execute(sa.text(sql))
    session.commit()
    logger.info("clean_fares database view created or replaced successfully.")
