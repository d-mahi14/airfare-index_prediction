"""
backend/tests/test_cleaning_pipeline.py
Unit tests for data cleaning, outlier detection, sold-out tracking,
imputation, clean_fares view, and quality reporting (processing/cleaning.py).
"""
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
import json
from typing import Any, Optional

import pytest

from backend.app.schemas.airfare import AirfareObservationCreate
from processing.cleaning import (
    CleaningConfig,
    DataQualityReport,
    check_fare_decomposition,
    clean_airfare_dataset,
    deduplicate_observations,
    filter_synthetic,
    flag_outliers_mad,
    impute_missing_cells,
    track_sold_out_and_cancelled,
)


def _make_obs(
    flight_number: str = "6E-101",
    origin: str = "BOM",
    destination: str = "DEL",
    airline_name: str = "IndiGo",
    airline_iata: str = "6E",
    source_name: str = "IndiGo",
    total_fare: Decimal = Decimal("5000.00"),
    base_fare: Optional[Decimal] = None,
    taxes: Optional[Decimal] = None,
    udf_psf: Optional[Decimal] = None,
    convenience_fee: Optional[Decimal] = None,
    other_fees: Optional[Decimal] = None,
    travel_date: date = date(2026, 10, 15),
    collection_date: date = date(2026, 9, 21),
    collection_timestamp: datetime = datetime(2026, 9, 21, 10, 0, tzinfo=timezone.utc),
    target_lead_window: int = 15,
    fare_class: str = "Economy",
    is_sold_out: bool = False,
    availability: str = "available",
    is_synthetic: bool = False,
    is_outlier: bool = False,
    is_imputed: bool = False,
    as_dict: bool = False,
) -> Any:
    """Helper to construct an AirfareObservationCreate or dict record with consistent components."""
    if base_fare is None:
        other_fees = Decimal("0.00") if other_fees is None else other_fees
        convenience_fee = Decimal("300.00") if convenience_fee is None else convenience_fee
        taxes = (total_fare * Decimal("0.05")).quantize(Decimal("0.01")) if taxes is None else taxes
        udf_psf = (total_fare * Decimal("0.05")).quantize(Decimal("0.01")) if udf_psf is None else udf_psf
        base_fare = total_fare - taxes - udf_psf - convenience_fee - other_fees
    else:
        taxes = taxes if taxes is not None else Decimal("0.00")
        udf_psf = udf_psf if udf_psf is not None else Decimal("0.00")
        convenience_fee = convenience_fee if convenience_fee is not None else Decimal("0.00")
        other_fees = other_fees if other_fees is not None else Decimal("0.00")

    data = {
        "collection_timestamp": collection_timestamp,
        "collection_date": collection_date,
        "source_name": source_name,
        "origin": origin,
        "destination": destination,
        "airline_name": airline_name,
        "airline_iata": airline_iata,
        "flight_number": flight_number,
        "travel_date": travel_date,
        "lead_days": (travel_date - collection_date).days,
        "fare_class": fare_class,
        "base_fare": base_fare,
        "taxes": taxes,
        "udf_psf": udf_psf,
        "convenience_fee": convenience_fee,
        "other_fees": other_fees,
        "total_fare": total_fare,
        "currency": "INR",
        "dep_time": time(10, 30),
        "stops": 0,
        "duration_min": 135,
        "is_sold_out": is_sold_out,
        "availability": availability,
        "is_synthetic": is_synthetic,
        "target_lead_window": target_lead_window,
        "is_outlier": is_outlier,
        "is_imputed": is_imputed,
    }
    if as_dict:
        return data
    return AirfareObservationCreate(**data)


# ---------------------------------------------------------------------------
# 1. Synthetic Filtering Tests
# ---------------------------------------------------------------------------

class TestSyntheticFiltering:
    def test_exclude_synthetic_by_default(self):
        records = [
            _make_obs(flight_number="6E-1", is_synthetic=False),
            _make_obs(flight_number="MOCK-2", is_synthetic=True),
            _make_obs(flight_number="6E-3", is_synthetic=False),
        ]
        filtered, dropped = filter_synthetic(records, include_synthetic=False)
        assert len(filtered) == 2
        assert dropped == 1
        assert all(not r.is_synthetic for r in filtered)

    def test_include_synthetic_flag(self):
        records = [
            _make_obs(flight_number="6E-1", is_synthetic=False),
            _make_obs(flight_number="MOCK-2", is_synthetic=True),
        ]
        filtered, dropped = filter_synthetic(records, include_synthetic=True)
        assert len(filtered) == 2
        assert dropped == 0


# ---------------------------------------------------------------------------
# 2. Deduplication Tests
# ---------------------------------------------------------------------------

class TestDeduplication:
    def test_dedup_keeps_latest_scrape(self):
        t1 = datetime(2026, 9, 21, 6, 0, tzinfo=timezone.utc)
        t2 = datetime(2026, 9, 21, 14, 0, tzinfo=timezone.utc)  # later

        r1 = _make_obs(flight_number="6E-201", total_fare=Decimal("4500.00"), collection_timestamp=t1)
        r2 = _make_obs(flight_number="6E-201", total_fare=Decimal("4800.00"), collection_timestamp=t2)

        deduped, dropped = deduplicate_observations([r1, r2])
        assert len(deduped) == 1
        assert dropped == 1
        assert deduped[0].total_fare == Decimal("4800.00")
        assert deduped[0].collection_timestamp == t2

    def test_different_keys_are_preserved(self):
        r1 = _make_obs(flight_number="6E-201", travel_date=date(2026, 10, 10))
        r2 = _make_obs(flight_number="6E-201", travel_date=date(2026, 10, 11))
        r3 = _make_obs(flight_number="6E-202", travel_date=date(2026, 10, 10))

        deduped, dropped = deduplicate_observations([r1, r2, r3])
        assert len(deduped) == 3
        assert dropped == 0


# ---------------------------------------------------------------------------
# 3. Fare Decomposition Consistency Tests
# ---------------------------------------------------------------------------

class TestFareDecompositionCheck:
    def test_consistent_fare_passes(self):
        r = _make_obs(
            total_fare=Decimal("5000.00"),
            base_fare=Decimal("4000.00"),
            taxes=Decimal("200.00"),
            udf_psf=Decimal("500.00"),
            convenience_fee=Decimal("300.00"),
            other_fees=Decimal("0.00"),
        )
        _, inconsistent = check_fare_decomposition([r])
        assert inconsistent == 0

    def test_inconsistent_fare_flagged(self):
        r = _make_obs(
            total_fare=Decimal("6000.00"),  # mismatch
            base_fare=Decimal("4000.00"),
            taxes=Decimal("200.00"),
            udf_psf=Decimal("500.00"),
            convenience_fee=Decimal("300.00"),
            other_fees=Decimal("0.00"),
            as_dict=True,
        )
        _, inconsistent = check_fare_decomposition([r])
        assert inconsistent == 1


# ---------------------------------------------------------------------------
# 4. Sold-Out & Cancellation Tracking Tests
# ---------------------------------------------------------------------------

class TestSoldOutAndCancelled:
    def test_sold_out_retention_and_route_share(self):
        records = [
            _make_obs(flight_number="6E-1", origin="DEL", destination="BOM", is_sold_out=False, availability="available"),
            _make_obs(flight_number="6E-2", origin="DEL", destination="BOM", is_sold_out=True, availability="sold_out"),
            _make_obs(flight_number="6E-3", origin="DEL", destination="BOM", is_sold_out=False, availability="cancelled"),
            _make_obs(flight_number="AI-1", origin="BOM", destination="BLR", is_sold_out=False, availability="available"),
        ]

        updated, total_sold, total_canc, route_stats = track_sold_out_and_cancelled(records)
        assert len(updated) == 4
        assert total_sold == 1
        assert total_canc == 1

        del_bom = route_stats["DEL-BOM"]
        assert del_bom["total"] == 3
        assert del_bom["available"] == 1
        assert del_bom["sold_out"] == 1
        assert del_bom["cancelled"] == 1
        assert abs(del_bom["sold_out_share"] - 0.3333) < 0.001

        bom_blr = route_stats["BOM-BLR"]
        assert bom_blr["total"] == 1
        assert bom_blr["sold_out"] == 0
        assert bom_blr["sold_out_share"] == 0.0


# ---------------------------------------------------------------------------
# 5. Outlier Detection (MAD & Edge Cases)
# ---------------------------------------------------------------------------

class TestOutlierFlaggingMAD:
    def test_single_observation_cell(self):
        """Single observation cannot be outlier by MAD if within floor/cap."""
        r = _make_obs(total_fare=Decimal("4500.00"))
        records, flagged = flag_outliers_mad([r], k_mad=3.0)
        assert flagged == 0
        assert r.is_outlier is False

    def test_single_observation_outside_hard_bounds(self):
        """Single observation below floor or above cap is flagged as outlier."""
        r_low = _make_obs(flight_number="6E-LOW", total_fare=Decimal("100.00"), base_fare=Decimal("50.00"), as_dict=True)
        r_high = _make_obs(flight_number="6E-HIGH", total_fare=Decimal("200000.00"), base_fare=Decimal("180000.00"), as_dict=True)
        records, flagged = flag_outliers_mad([r_low, r_high], min_fare_floor=Decimal("500.00"), max_fare_cap=Decimal("150000.00"))
        assert flagged == 2
        assert r_low["is_outlier"] is True
        assert r_high["is_outlier"] is True

    def test_all_outlier_or_zero_dispersion_cell(self):
        """Identical fares (MAD=0) are not flagged as outliers when within floor/cap."""
        records = [
            _make_obs(flight_number=f"6E-{i}", total_fare=Decimal("5000.00"))
            for i in range(5)
        ]
        res, flagged = flag_outliers_mad(records, k_mad=3.0)
        assert flagged == 0
        assert all(not r.is_outlier for r in res)

    def test_mad_statistical_outlier_detection(self):
        """Normal fares with one extreme high fare flagged via MAD."""
        normal = [
            _make_obs(flight_number="6E-1", total_fare=Decimal("4000.00")),
            _make_obs(flight_number="6E-2", total_fare=Decimal("4200.00")),
            _make_obs(flight_number="6E-3", total_fare=Decimal("4100.00")),
            _make_obs(flight_number="6E-4", total_fare=Decimal("4300.00")),
            _make_obs(flight_number="6E-5", total_fare=Decimal("4150.00")),
        ]
        outlier = _make_obs(flight_number="6E-SPIKE", total_fare=Decimal("7500.00"))

        res, flagged = flag_outliers_mad(normal + [outlier], k_mad=3.0)
        assert flagged == 1
        assert outlier.is_outlier is True
        assert all(not r.is_outlier for r in normal)

    def test_outlier_never_deleted(self):
        """Verify outlier remains in the returned collection."""
        r_norm = _make_obs(flight_number="6E-1", total_fare=Decimal("4000.00"))
        r_out = _make_obs(flight_number="6E-2", total_fare=Decimal("200000.00"), as_dict=True)
        res, flagged = flag_outliers_mad([r_norm, r_out])
        assert len(res) == 2
        assert res[1]["is_outlier"] is True


# ---------------------------------------------------------------------------
# 6. Imputation Limits & Carry Forward Tests
# ---------------------------------------------------------------------------

class TestImputationLimits:
    def test_empty_cell_with_zero_history(self):
        """Empty cell with no current or past records is gracefully recorded as unimputable."""
        current = []
        target_date = date(2026, 9, 21)
        grid_cells = [("DEL-BOM", 7, "6E")]

        res, attempted, present, cf, fallback, unimputed = impute_missing_cells(
            current_records=current,
            historical_records_by_date={},
            target_date=target_date,
            grid_cells=grid_cells,
            max_carry_forward_days=2,
        )

        assert attempted == 1
        assert present == 0
        assert cf == 0
        assert fallback == 0
        assert unimputed == 1
        assert len(res) == 0

    def test_carry_forward_one_day_missing(self):
        """Cell missing on t is carried forward from t-1."""
        target_date = date(2026, 9, 21)
        yesterday = date(2026, 9, 20)

        hist_rec = _make_obs(
            flight_number="6E-101",
            origin="DEL",
            destination="BOM",
            total_fare=Decimal("4200.00"),
            collection_date=yesterday,
            target_lead_window=7,
        )

        history = {yesterday: [hist_rec]}
        grid_cells = [("DEL-BOM", 7, "6E")]

        res, attempted, present, cf, fallback, unimputed = impute_missing_cells(
            current_records=[],
            historical_records_by_date=history,
            target_date=target_date,
            grid_cells=grid_cells,
            max_carry_forward_days=2,
        )

        assert attempted == 1
        assert present == 0
        assert cf == 1
        assert fallback == 0
        assert len(res) == 1

        imputed = res[0]
        assert imputed.is_imputed is True
        assert imputed.collection_date == target_date
        assert imputed.total_fare == Decimal("4200.00")

    def test_carry_forward_two_days_missing(self):
        """Cell missing on t and t-1 is carried forward from t-2."""
        target_date = date(2026, 9, 21)
        two_days_ago = date(2026, 9, 19)

        hist_rec = _make_obs(
            flight_number="6E-101",
            origin="DEL",
            destination="BOM",
            total_fare=Decimal("4100.00"),
            collection_date=two_days_ago,
            target_lead_window=7,
        )

        history = {two_days_ago: [hist_rec]}
        grid_cells = [("DEL-BOM", 7, "6E")]

        res, attempted, present, cf, fallback, unimputed = impute_missing_cells(
            current_records=[],
            historical_records_by_date=history,
            target_date=target_date,
            grid_cells=grid_cells,
            max_carry_forward_days=2,
        )

        assert cf == 1
        assert len(res) == 1
        assert res[0].is_imputed is True

    def test_missing_beyond_two_days_uses_cell_median_fallback(self):
        """Cell missing for >2 days (e.g. 3 days ago) uses cell historical median fallback."""
        target_date = date(2026, 9, 21)
        three_days_ago = date(2026, 9, 18)  # Delta = 3 > max_carry_forward_days (2)

        hist_rec1 = _make_obs(flight_number="6E-101", total_fare=Decimal("4000.00"), collection_date=three_days_ago, target_lead_window=7)
        hist_rec2 = _make_obs(flight_number="6E-102", total_fare=Decimal("4600.00"), collection_date=three_days_ago, target_lead_window=7)

        history = {three_days_ago: [hist_rec1, hist_rec2]}
        grid_cells = [("BOM-DEL", 7, "6E")]

        res, attempted, present, cf, fallback, unimputed = impute_missing_cells(
            current_records=[],
            historical_records_by_date=history,
            target_date=target_date,
            grid_cells=grid_cells,
            max_carry_forward_days=2,
        )

        assert cf == 0  # Not carried forward because > 2 days
        assert fallback == 1
        assert len(res) == 1
        assert res[0].is_imputed is True
        assert res[0].total_fare == Decimal("4300.00")  # Median of 4000 and 4600


# ---------------------------------------------------------------------------
# 7. End-to-End Pipeline & DataQualityReport Tests
# ---------------------------------------------------------------------------

class TestEndToEndCleaningPipeline:
    def test_full_pipeline_execution(self):
        today = date(2026, 9, 21)
        yesterday = date(2026, 9, 20)

        # Input raw observations
        obs1_clean = _make_obs(flight_number="6E-1", total_fare=Decimal("4000.00"), collection_date=today)
        obs2_clean = _make_obs(flight_number="6E-2", total_fare=Decimal("4200.00"), collection_date=today)
        obs3_dup = _make_obs(flight_number="6E-1", total_fare=Decimal("4000.00"), collection_date=today)  # duplicate of obs1
        obs4_synth = _make_obs(flight_number="MOCK-1", is_synthetic=True, collection_date=today)
        obs5_sold = _make_obs(flight_number="6E-SOLD", total_fare=Decimal("5500.00"), is_sold_out=True, collection_date=today)
        obs6_outlier = _make_obs(flight_number="6E-OUT", total_fare=Decimal("180000.00"), collection_date=today, as_dict=True)

        # Missing cell on today to be carried forward from yesterday
        hist_rec = _make_obs(flight_number="AI-500", origin="DEL", destination="BLR", airline_name="Air India", airline_iata="AI", total_fare=Decimal("6000.00"), collection_date=yesterday, target_lead_window=15)
        history = {yesterday: [hist_rec]}

        grid_cells = [
            ("BOM-DEL", 15, "6E"),
            ("DEL-BLR", 15, "AI"),
        ]

        all_records, clean_fares, report = clean_airfare_dataset(
            records=[obs1_clean, obs2_clean, obs3_dup, obs4_synth, obs5_sold, obs6_outlier],
            historical_records_by_date=history,
            target_date=today,
            grid_cells=grid_cells,
            config=CleaningConfig(include_synthetic=False, k_mad=3.0),
        )

        # 1. Check counts
        assert report.total_input_records == 6
        assert report.synthetic_records_filtered == 1
        assert report.dedup_duplicates_dropped == 1
        assert report.sold_out_count == 1
        assert report.outliers_flagged == 1
        assert report.cells_carried_forward == 1

        # 2. Check clean fares dataset
        # Eligible: obs1, obs2, and imputed AI-500
        assert report.clean_fares_count == 3
        assert len(clean_fares) == 3
        clean_flights = {_make_clean_id(r) for r in clean_fares}
        assert "6E-1" in clean_flights
        assert "6E-2" in clean_flights
        assert "AI-500" in clean_flights
        assert "6E-SOLD" not in clean_flights
        assert "6E-OUT" not in clean_flights

        # 3. Check JSON & Markdown reports
        report_json = report.to_json()
        assert "total_input_records" in report_json
        parsed_dict = json.loads(report_json)
        assert parsed_dict["clean_fares_count"] == 3

        report_md = report.to_markdown()
        assert "# APIx Data Quality & Cleaning Audit Report" in report_md
        assert "Total Input Records Received" in report_md
        assert "Route Sold-Out & Availability Statistics" in report_md


def _make_clean_id(rec: Any) -> str:
    if isinstance(rec, dict):
        return rec.get("flight_number")
    return getattr(rec, "flight_number", "")
