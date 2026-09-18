"""
backend/tests/test_mock_collector.py
Tests for the MockCollector.

Does NOT make any network requests.
Validates that the MockCollector produces structurally valid observations.
"""
import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from scraper.collectors.mock_collector import MockCollector


@pytest.fixture
def collector(tmp_path):
    """MockCollector with seed=42 writing to a temp directory."""
    return MockCollector(raw_data_dir=str(tmp_path), seed=42)


class TestMockCollector:
    def test_collect_returns_observations(self, collector):
        travel = date.today() + timedelta(days=7)
        obs = collector.collect("BOM", "DEL", travel)
        assert len(obs) >= 1

    def test_all_observations_valid_pydantic(self, collector):
        """Every returned object should be a valid AirfareObservationCreate."""
        from backend.app.schemas.airfare import AirfareObservationCreate
        travel = date.today() + timedelta(days=7)
        obs = collector.collect("BOM", "DEL", travel)
        for o in obs:
            assert isinstance(o, AirfareObservationCreate)

    def test_origin_destination_correct(self, collector):
        travel = date.today() + timedelta(days=7)
        obs = collector.collect("BOM", "DEL", travel)
        for o in obs:
            assert o.origin == "BOM"
            assert o.destination == "DEL"

    def test_travel_date_correct(self, collector):
        travel = date.today() + timedelta(days=7)
        obs = collector.collect("BOM", "DEL", travel)
        for o in obs:
            assert o.travel_date == travel

    def test_lead_days_correct(self, collector):
        travel = date.today() + timedelta(days=7)
        obs = collector.collect("BOM", "DEL", travel)
        for o in obs:
            assert o.lead_days == 7

    def test_total_fare_gt_base_fare(self, collector):
        travel = date.today() + timedelta(days=7)
        obs = collector.collect("BOM", "DEL", travel)
        for o in obs:
            if o.base_fare is not None:
                assert o.total_fare >= o.base_fare

    def test_fares_positive(self, collector):
        travel = date.today() + timedelta(days=7)
        obs = collector.collect("BOM", "DEL", travel)
        for o in obs:
            assert o.total_fare > Decimal("0")

    def test_currency_inr(self, collector):
        travel = date.today() + timedelta(days=7)
        obs = collector.collect("BOM", "DEL", travel)
        for o in obs:
            assert o.currency == "INR"

    def test_source_name_correct(self, collector):
        travel = date.today() + timedelta(days=7)
        obs = collector.collect("BOM", "DEL", travel)
        for o in obs:
            assert o.source_name == "MockCollector"

    def test_raw_reference_saved(self, collector, tmp_path):
        travel = date.today() + timedelta(days=7)
        obs = collector.collect("BOM", "DEL", travel)
        for o in obs:
            assert o.raw_reference is not None
            assert Path(o.raw_reference).exists()

    def test_past_travel_date_returns_empty(self, collector):
        past = date.today() - timedelta(days=1)
        obs = collector.collect("BOM", "DEL", past)
        assert obs == []

    def test_seeded_reproducible(self, tmp_path):
        """Same seed → same observations."""
        c1 = MockCollector(raw_data_dir=str(tmp_path), seed=99)
        c2 = MockCollector(raw_data_dir=str(tmp_path), seed=99)
        travel = date.today() + timedelta(days=7)
        obs1 = c1.collect("BOM", "DEL", travel)
        obs2 = c2.collect("BOM", "DEL", travel)
        fares1 = [o.total_fare for o in obs1]
        fares2 = [o.total_fare for o in obs2]
        assert fares1 == fares2

    def test_different_seeds_may_differ(self, tmp_path):
        """Different seeds → likely different fares."""
        c1 = MockCollector(raw_data_dir=str(tmp_path), seed=1)
        c2 = MockCollector(raw_data_dir=str(tmp_path), seed=999)
        travel = date.today() + timedelta(days=7)
        obs1 = c1.collect("BOM", "DEL", travel)
        obs2 = c2.collect("BOM", "DEL", travel)
        # At least one fare should differ (with high probability for different seeds)
        fares1 = set(o.total_fare for o in obs1)
        fares2 = set(o.total_fare for o in obs2)
        # This test is probabilistic but seeds 1 vs 999 will almost certainly differ
        assert fares1 != fares2 or len(obs1) != len(obs2)
