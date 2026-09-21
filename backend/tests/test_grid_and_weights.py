"""
backend/tests/test_grid_and_weights.py
Tests for DGCA route weights, advance purchase lead weights, collection grid, and enhanced MockCollector.
"""
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from backend.app.models.index import LeadTimeWeight, RouteWeight
from backend.app.utils.weights import (
    load_dgca_route_weights,
    load_lead_time_weights,
    sync_lead_time_weights_to_db,
    sync_route_weights_to_db,
)
from scraper.collectors.mock_collector import MockCollector
from scraper.grid import CollectionGrid


class TestRouteWeights:
    def test_route_weights_sum_to_one(self):
        records = load_dgca_route_weights()
        assert len(records) == 20
        total_weight = sum(r["weight"] for r in records)
        assert total_weight == Decimal("1.000000")

    def test_all_20_routes_present(self):
        records = load_dgca_route_weights()
        route_codes = {r["route_code"] for r in records}
        expected_pairs = {
            "BOM-DEL", "DEL-BOM",
            "DEL-BLR", "BLR-DEL",
            "BOM-BLR", "BLR-BOM",
            "DEL-HYD", "HYD-DEL",
            "BOM-HYD", "HYD-BOM",
            "DEL-CCU", "CCU-DEL",
            "BOM-CCU", "CCU-BOM",
            "DEL-MAA", "MAA-DEL",
            "BOM-MAA", "MAA-BOM",
            "BLR-HYD", "HYD-BLR",
        }
        assert route_codes == expected_pairs

    def test_placeholder_flag(self):
        records = load_dgca_route_weights()
        assert all(r["placeholder"] is True for r in records)

    def test_sync_route_weights_to_db(self, db_session):
        count = sync_route_weights_to_db(db_session, valid_from=date(2024, 1, 1))
        assert count == 20

        weights = db_session.query(RouteWeight).filter(RouteWeight.valid_from == date(2024, 1, 1)).all()
        assert len(weights) == 20
        total_db_weight = sum(w.weight for w in weights)
        assert total_db_weight == Decimal("1.000000")


class TestLeadTimeWeights:
    def test_lead_time_weights_sum_to_one(self):
        records = load_lead_time_weights()
        assert len(records) == 5
        total_weight = sum(r["weight"] for r in records)
        assert total_weight == Decimal("1.000000")

    def test_all_5_lead_windows_present(self):
        records = load_lead_time_weights()
        lead_days = [r["lead_days"] for r in records]
        assert lead_days == [1, 7, 15, 30, 45]

    def test_sync_lead_time_weights_to_db(self, db_session):
        count = sync_lead_time_weights_to_db(db_session, valid_from=date(2024, 1, 1))
        assert count == 5

        weights = db_session.query(LeadTimeWeight).filter(LeadTimeWeight.valid_from == date(2024, 1, 1)).all()
        assert len(weights) == 5
        total_db_weight = sum(w.weight for w in weights)
        assert total_db_weight == Decimal("1.000000")


class TestCollectionGrid:
    def test_default_grid_generation(self):
        grid = CollectionGrid()
        cells = grid.generate_cells(collection_date=date(2026, 9, 20))
        # 20 active routes x 5 lead days = 100 cells
        assert len(cells) == 100
        assert grid.total_cells_count(collection_date=date(2026, 9, 20)) == 100

    def test_filtered_grid_generation(self):
        grid = CollectionGrid()
        cells = grid.generate_cells(
            collection_date=date(2026, 9, 20),
            routes=["BOM-DEL", "DEL-BLR"],
            lead_days=[1, 7],
        )
        assert len(cells) == 4
        assert {c.route_code for c in cells} == {"BOM-DEL", "DEL-BLR"}
        assert {c.lead_days for c in cells} == {1, 7}

    def test_cell_travel_date_calculation(self):
        grid = CollectionGrid()
        col_date = date(2026, 9, 20)
        cells = grid.generate_cells(
            collection_date=col_date,
            routes=["BOM-DEL"],
            lead_days=[1, 15],
        )
        for cell in cells:
            assert cell.travel_date == col_date + timedelta(days=cell.lead_days)


class TestMockCollectorAdvanced:
    def test_seed_reproducibility(self):
        c1 = MockCollector(seed=42)
        c2 = MockCollector(seed=42)
        travel_dt = date.today() + timedelta(days=7)

        obs1 = c1.collect("BOM", "DEL", travel_dt)
        obs2 = c2.collect("BOM", "DEL", travel_dt)

        assert len(obs1) == len(obs2)
        for o1, o2 in zip(obs1, obs2):
            assert o1.airline_name == o2.airline_name
            assert o1.flight_number == o2.flight_number
            assert o1.total_fare == o2.total_fare
            assert o1.base_fare == o2.base_fare
            assert o1.taxes == o2.taxes
            assert o1.udf_psf == o2.udf_psf
            assert o1.convenience_fee == o2.convenience_fee
            assert o1.is_sold_out == o2.is_sold_out

    def test_all_observations_synthetic(self):
        collector = MockCollector(seed=101)
        travel_dt = date.today() + timedelta(days=15)
        obs = collector.collect("DEL", "BLR", travel_dt)
        assert len(obs) > 0
        assert all(o.is_synthetic is True for o in obs)

    def test_sold_out_generation(self):
        # Sample across multiple short-lead flights to verify sold-out flag behavior
        collector = MockCollector(seed=999)
        sold_out_found = False
        travel_dt = date.today() + timedelta(days=1)

        for _ in range(20):
            obs_list = collector.collect("BOM", "DEL", travel_dt)
            for o in obs_list:
                if o.is_sold_out:
                    sold_out_found = True
                    assert o.availability == "sold_out"
                    assert o.seats_left == 0
                    break
            if sold_out_found:
                break

        assert sold_out_found, "Sold-out observation was generated in simulation"

    def test_lead_time_pricing_gradient(self):
        # Average fare at T+1 should be higher than T+45 on average
        fares_t1 = []
        fares_t45 = []

        for seed in range(10, 20):
            c = MockCollector(seed=seed)
            t1 = date.today() + timedelta(days=1)
            t45 = date.today() + timedelta(days=45)

            obs_t1 = c.collect("BOM", "DEL", t1)
            obs_t45 = c.collect("BOM", "DEL", t45)

            fares_t1.extend(float(o.total_fare) for o in obs_t1)
            fares_t45.extend(float(o.total_fare) for o in obs_t45)

        avg_t1 = sum(fares_t1) / len(fares_t1)
        avg_t45 = sum(fares_t45) / len(fares_t45)
        assert avg_t1 > avg_t45, f"Expected T+1 avg fare ({avg_t1}) > T+45 avg fare ({avg_t45})"

    def test_fee_breakdown_consistency(self):
        collector = MockCollector(seed=555)
        travel_dt = date.today() + timedelta(days=7)
        obs_list = collector.collect("DEL", "HYD", travel_dt)

        for obs in obs_list:
            expected_total = obs.base_fare + obs.taxes + obs.udf_psf + obs.convenience_fee + obs.other_fees
            assert obs.total_fare == expected_total
