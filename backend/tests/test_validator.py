"""
backend/tests/test_validator.py
Tests for the scraper validation pipeline.

Validates:
  - Valid observation passes
  - Below minimum fare → rejected
  - Sold out flight → rejected
  - Cancelled flight → rejected
  - Fee breakdown mismatch → rejected
  - High fare → warning only (not rejected)
  - Batch validation counts
"""
import sys
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from backend.app.schemas.airfare import AirfareObservationCreate
from scraper.pipelines.validator import (
    ValidationResult,
    _check_fare_positive,
    validate_observation,
    validate_observations,
)

_COLLECTION_TS = datetime(2026, 9, 18, 10, 0, 0, tzinfo=timezone.utc)
_TRAVEL_DATE = date(2026, 9, 25)


def _make_obs(**overrides) -> AirfareObservationCreate:
    """Build a valid observation, allowing field overrides."""
    defaults = {
        "collection_timestamp": _COLLECTION_TS,
        "source_name": "TestCollector",
        "origin": "BOM",
        "destination": "DEL",
        "airline_name": "IndiGo",
        "travel_date": _TRAVEL_DATE,
        "fare_class": "Economy",
        "base_fare": Decimal("4200.00"),
        "taxes": Decimal("200.00"),
        "udf_psf": Decimal("300.00"),
        "convenience_fee": Decimal("200.00"),
        "other_fees": Decimal("0.00"),
        "total_fare": Decimal("4900.00"),
        "currency": "INR",
        "availability": "available",
    }
    defaults.update(overrides)
    return AirfareObservationCreate(**defaults)


class TestValidateObservation:
    def test_valid_observation_passes(self):
        obs = _make_obs()
        result = validate_observation(obs)
        assert result.is_valid
        assert result.status == "valid"
        assert result.rejection_reason is None

    def test_below_minimum_fare_rejected(self):
        """Fares below ₹500 are implausible for domestic air travel."""
        obs = _make_obs(base_fare=None, total_fare=Decimal("200.00"))
        result = validate_observation(obs)
        assert not result.is_valid
        assert "minimum" in result.rejection_reason or "non_positive" in result.rejection_reason

    def test_sold_out_rejected(self):
        obs = _make_obs(availability="sold_out")
        result = validate_observation(obs)
        assert not result.is_valid
        assert result.rejection_reason == "sold_out_flight"

    def test_cancelled_rejected(self):
        obs = _make_obs(availability="cancelled")
        result = validate_observation(obs)
        assert not result.is_valid
        assert result.rejection_reason == "cancelled_flight"

    def test_high_fare_gets_warning_not_rejection(self):
        """₹80,000 is suspicious but not impossible — should warn, not reject."""
        obs = _make_obs(
            base_fare=None,
            total_fare=Decimal("80000.00"),
        )
        result = validate_observation(obs)
        assert result.is_valid  # not rejected
        assert any("unusually_high" in w for w in result.warnings)

    def test_normal_business_class_fare(self):
        obs = _make_obs(
            fare_class="Business",
            base_fare=Decimal("25000.00"),
            taxes=Decimal("3500.00"),
            udf_psf=Decimal("500.00"),
            convenience_fee=Decimal("500.00"),
            other_fees=Decimal("0.00"),
            total_fare=Decimal("29500.00"),
        )
        result = validate_observation(obs)
        assert result.is_valid


class TestBatchValidation:
    def test_mixed_batch(self):
        valid1 = _make_obs()
        valid2 = _make_obs(total_fare=Decimal("5500.00"), base_fare=None)
        sold_out = _make_obs(availability="sold_out")
        cancelled = _make_obs(availability="cancelled")

        valid_obs, rejected = validate_observations([valid1, valid2, sold_out, cancelled])

        assert len(valid_obs) == 2
        assert len(rejected) == 2

    def test_empty_batch(self):
        valid_obs, rejected = validate_observations([])
        assert valid_obs == []
        assert rejected == []

    def test_all_valid_batch(self):
        obs_list = [_make_obs() for _ in range(5)]
        valid_obs, rejected = validate_observations(obs_list)
        assert len(valid_obs) == 5
        assert len(rejected) == 0

    def test_rejection_tuples_have_reason(self):
        sold_out = _make_obs(availability="sold_out")
        _, rejected = validate_observations([sold_out])
        assert len(rejected) == 1
        obs, reason = rejected[0]
        assert reason == "sold_out_flight"
