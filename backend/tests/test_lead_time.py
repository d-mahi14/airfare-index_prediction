"""
backend/tests/test_lead_time.py
Tests for lead-time calculation logic.

Validates that lead_days is correctly computed from (collection_date, travel_date)
and that the schema properly enforces the constraint.
"""
import sys
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from backend.app.schemas.airfare import AirfareObservationCreate, _compute_lead_days


def _make_obs(**overrides) -> dict:
    """Helper to build a minimal valid observation dict."""
    today = date.today()
    base = {
        "source_name": "TestCollector",
        "origin": "BOM",
        "destination": "DEL",
        "airline_name": "IndiGo",
        "travel_date": today.replace(day=today.day),  # same day override below
        "total_fare": Decimal("4900.00"),
        "base_fare": Decimal("4200.00"),
        "taxes": Decimal("700.00"),
    }
    base.update(overrides)
    return base


class TestLeadDaysComputation:
    """Test the _compute_lead_days helper function directly."""

    def test_7_days(self):
        collection = datetime(2026, 9, 18, 10, 30, 0, tzinfo=timezone.utc)
        travel = date(2026, 9, 25)
        assert _compute_lead_days(collection, travel) == 7

    def test_1_day(self):
        collection = datetime(2026, 9, 18, 10, 30, 0, tzinfo=timezone.utc)
        travel = date(2026, 9, 19)
        assert _compute_lead_days(collection, travel) == 1

    def test_same_day_zero(self):
        collection = datetime(2026, 9, 18, 10, 30, 0, tzinfo=timezone.utc)
        travel = date(2026, 9, 18)
        assert _compute_lead_days(collection, travel) == 0

    def test_30_days(self):
        collection = datetime(2026, 9, 18, 0, 0, 0, tzinfo=timezone.utc)
        travel = date(2026, 10, 18)
        assert _compute_lead_days(collection, travel) == 30

    def test_45_days(self):
        collection = datetime(2026, 9, 18, 0, 0, 0, tzinfo=timezone.utc)
        travel = date(2026, 11, 2)
        assert _compute_lead_days(collection, travel) == 45

    def test_15_days(self):
        collection = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)
        travel = date(2026, 9, 16)
        assert _compute_lead_days(collection, travel) == 15

    def test_month_boundary(self):
        """Lead days across month boundary."""
        collection = datetime(2026, 1, 31, 0, 0, 0, tzinfo=timezone.utc)
        travel = date(2026, 3, 2)
        assert _compute_lead_days(collection, travel) == 30

    def test_year_boundary(self):
        collection = datetime(2025, 12, 25, 0, 0, 0, tzinfo=timezone.utc)
        travel = date(2026, 1, 1)
        assert _compute_lead_days(collection, travel) == 7


class TestLeadDaysSchema:
    """Test lead_days computation and validation in the Pydantic schema."""

    def test_auto_computed_when_not_provided(self):
        collection = datetime(2026, 9, 18, 10, 0, 0, tzinfo=timezone.utc)
        travel = date(2026, 9, 25)
        obs = AirfareObservationCreate(
            collection_timestamp=collection,
            source_name="TestCollector",
            origin="BOM",
            destination="DEL",
            airline_name="IndiGo",
            travel_date=travel,
            total_fare=Decimal("4900.00"),
        )
        assert obs.lead_days == 7

    def test_provided_correctly_passes(self):
        collection = datetime(2026, 9, 18, 10, 0, 0, tzinfo=timezone.utc)
        travel = date(2026, 9, 25)
        obs = AirfareObservationCreate(
            collection_timestamp=collection,
            source_name="TestCollector",
            origin="BOM",
            destination="DEL",
            airline_name="IndiGo",
            travel_date=travel,
            lead_days=7,  # matches computed
            total_fare=Decimal("4900.00"),
        )
        assert obs.lead_days == 7

    def test_wrong_lead_days_raises(self):
        collection = datetime(2026, 9, 18, 10, 0, 0, tzinfo=timezone.utc)
        travel = date(2026, 9, 25)
        with pytest.raises(ValueError, match="does not match computed"):
            AirfareObservationCreate(
                collection_timestamp=collection,
                source_name="TestCollector",
                origin="BOM",
                destination="DEL",
                airline_name="IndiGo",
                travel_date=travel,
                lead_days=10,  # wrong: should be 7
                total_fare=Decimal("4900.00"),
            )

    def test_past_travel_date_raises(self):
        collection = datetime(2026, 9, 18, 10, 0, 0, tzinfo=timezone.utc)
        travel = date(2026, 9, 17)  # yesterday
        with pytest.raises(ValueError, match="travel_date"):
            AirfareObservationCreate(
                collection_timestamp=collection,
                source_name="TestCollector",
                origin="BOM",
                destination="DEL",
                airline_name="IndiGo",
                travel_date=travel,
                total_fare=Decimal("4900.00"),
            )
