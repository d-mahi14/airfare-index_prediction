"""
backend/tests/test_apix_index.py
Comprehensive test suite for APIx index calculation engine (pure math, service layer, and hypothesis property tests).
"""
import copy
from datetime import date
import random
import pytest
from hypothesis import given, settings, strategies as st

from index.apix import (
    APIxIndexService,
    aggregate_lead_times,
    aggregate_routes,
    chain_link,
    compute_apix,
    compute_elementary_jevons,
    extract_price,
    geometric_mean,
)


# ─── Fixtures & Helpers ────────────────────────────────────────────────────────

def create_sample_observations(price_mult: float = 1.0, is_synthetic: bool = False):
    """Generate a structured set of sample observations across 4 routes and 5 lead windows."""
    routes = ["BOM-DEL", "DEL-BOM", "DEL-BLR", "BOM-BLR"]
    leads = [1, 7, 15, 30, 45]
    carriers = [("6E", "IndiGo"), ("AI", "Air India"), ("QP", "Akasa Air"), ("SG", "SpiceJet")]
    bands = ["morning", "afternoon", "evening"]

    observations = []
    base_price = 4000.0

    for r in routes:
        orig, dest = r.split("-")
        for l in leads:
            # Lead premium / discount
            lead_factor = 1.6 if l == 1 else (1.2 if l == 7 else (1.0 if l == 15 else (0.85 if l == 30 else 0.75)))
            for code, name in carriers:
                for band in bands:
                    p = base_price * lead_factor * price_mult
                    base_p = round(p * 0.75, 2)
                    tax_p = round(p * 0.10, 2)
                    udf_p = round(p * 0.10, 2)
                    fee_p = round(p * 0.05, 2)
                    total_p = round(base_p + tax_p + udf_p + fee_p, 2)

                    observations.append({
                        "origin": orig,
                        "destination": dest,
                        "route_code": r,
                        "lead_days": l,
                        "target_lead_window": l,
                        "carrier_code": code,
                        "airline_iata": code,
                        "carrier": code,
                        "airline_name": name,
                        "flight_number": f"{code}-{random.randint(100, 999)}",
                        "dep_band": band,
                        "fare_class": "economy",
                        "base_fare": base_p,
                        "taxes": tax_p,
                        "udf_psf": udf_p,
                        "convenience_fee": fee_p,
                        "total_fare": total_p,
                        "is_synthetic": is_synthetic,
                    })

    return observations


@pytest.fixture
def sample_route_weights():
    return {
        "BOM-DEL": 0.35,
        "DEL-BOM": 0.35,
        "DEL-BLR": 0.15,
        "BOM-BLR": 0.15,
    }


@pytest.fixture
def sample_lead_weights():
    return {
        1: 0.20,
        7: 0.20,
        15: 0.20,
        30: 0.20,
        45: 0.20,
    }


# ─── Unit Tests for Pure Mathematical Functions ────────────────────────────────

class TestElementaryJevons:
    def test_constant_prices_give_100(self):
        base_obs = [
            {"carrier_code": "6E", "dep_band": "morning", "fare_class": "economy", "total_fare": 4000.0},
            {"carrier_code": "AI", "dep_band": "evening", "fare_class": "economy", "total_fare": 5000.0},
        ]
        curr_obs = copy.deepcopy(base_obs)

        idx, meta = compute_elementary_jevons(curr_obs, base_obs, variant="total_fare", base_value=100.0)
        assert idx is not None
        assert pytest.approx(idx, 1e-6) == 100.0
        assert meta["matched_strata_count"] == 2
        assert not meta["is_fallback"]

    def test_price_scaling_by_k(self):
        k = 1.35
        base_obs = [
            {"carrier_code": "6E", "dep_band": "morning", "fare_class": "economy", "total_fare": 4000.0},
            {"carrier_code": "AI", "dep_band": "evening", "fare_class": "economy", "total_fare": 5000.0},
        ]
        curr_obs = [
            {"carrier_code": "6E", "dep_band": "morning", "fare_class": "economy", "total_fare": 4000.0 * k},
            {"carrier_code": "AI", "dep_band": "evening", "fare_class": "economy", "total_fare": 5000.0 * k},
        ]

        idx, _ = compute_elementary_jevons(curr_obs, base_obs, variant="total_fare", base_value=100.0)
        assert idx is not None
        assert pytest.approx(idx, 1e-6) == 100.0 * k

    def test_unmatched_strata_fallback(self):
        # Base has 6E morning, Current has only SG evening
        base_obs = [
            {"carrier_code": "6E", "dep_band": "morning", "fare_class": "economy", "total_fare": 4000.0}
        ]
        curr_obs = [
            {"carrier_code": "SG", "dep_band": "evening", "fare_class": "economy", "total_fare": 6000.0}
        ]

        idx, meta = compute_elementary_jevons(curr_obs, base_obs, variant="total_fare", base_value=100.0)
        assert idx is not None
        assert pytest.approx(idx, 1e-6) == (6000.0 / 4000.0) * 100.0
        assert meta["is_fallback"] is True
        assert "fallback_reason" in meta

    def test_empty_observations_returns_none(self):
        idx, _ = compute_elementary_jevons([], [{"total_fare": 4000.0}])
        assert idx is None

        idx2, _ = compute_elementary_jevons([{"total_fare": 4000.0}], [])
        assert idx2 is None


class TestLeadTimeAggregation:
    def test_lead_weights_normalized_sum_to_one(self, sample_lead_weights):
        lead_indices = {1: 150.0, 7: 120.0, 15: 100.0, 30: 90.0, 45: 80.0}
        route_idx, meta = aggregate_lead_times(lead_indices, sample_lead_weights)
        assert route_idx is not None
        # Equal weights 0.2 each
        expected = 0.2 * (150 + 120 + 100 + 90 + 80)
        assert pytest.approx(route_idx, 1e-6) == expected
        assert meta["coverage"] == 1.0

    def test_missing_lead_window_reweighted_and_coverage(self, sample_lead_weights):
        # Only T+7, T+15, T+30 present (T+1 and T+45 missing)
        lead_indices = {1: None, 7: 120.0, 15: 100.0, 30: 90.0, 45: None}
        route_idx, meta = aggregate_lead_times(lead_indices, sample_lead_weights)
        assert route_idx is not None
        # Present weight = 0.2+0.2+0.2 = 0.6. Each gets 1/3 weight.
        expected = (120.0 + 100.0 + 90.0) / 3.0
        assert pytest.approx(route_idx, 1e-6) == expected
        assert meta["coverage"] == 0.6
        assert meta["present_lead_windows"] == [7, 15, 30]


class TestRouteAggregation:
    def test_route_weights_sum_to_one(self, sample_route_weights):
        assert pytest.approx(sum(sample_route_weights.values()), 1e-6) == 1.0

        route_indices = {
            "BOM-DEL": 110.0,
            "DEL-BOM": 105.0,
            "DEL-BLR": 100.0,
            "BOM-BLR": 95.0,
        }
        overall, meta = aggregate_routes(route_indices, sample_route_weights)
        expected = 0.35 * 110.0 + 0.35 * 105.0 + 0.15 * 100.0 + 0.15 * 95.0
        assert pytest.approx(overall, 1e-6) == expected
        assert meta["coverage"] == 1.0

    def test_missing_route_reweighted(self, sample_route_weights):
        # DEL-BLR missing
        route_indices = {
            "BOM-DEL": 110.0,
            "DEL-BOM": 105.0,
            "DEL-BLR": None,
            "BOM-BLR": 95.0,
        }
        overall, meta = aggregate_routes(route_indices, sample_route_weights)
        # Sum of active weights = 0.35 + 0.35 + 0.15 = 0.85
        expected = (0.35 * 110.0 + 0.35 * 105.0 + 0.15 * 95.0) / 0.85
        assert pytest.approx(overall, 1e-6) == expected
        assert meta["coverage"] == 0.75


class TestChainLinking:
    def test_chain_link_continuity(self):
        # Suppose previous chained index at T_link was 112.5.
        # Under new weights, index at T_link is 108.0, and at current t is 110.16 (2% growth).
        chained = chain_link(
            current_index_with_new_weights=110.16,
            link_period_index_with_new_weights=108.0,
            link_period_index_chained=112.5,
        )
        expected = 112.5 * (110.16 / 108.0)  # 112.5 * 1.02 = 114.75
        assert pytest.approx(chained, 1e-6) == 114.75


# ─── Top-Level APIx Pure Engine Tests ──────────────────────────────────────────

class TestComputeAPIxIntegration:
    def test_constant_prices_yields_exact_100(self, sample_route_weights, sample_lead_weights):
        base_obs = create_sample_observations(price_mult=1.0, is_synthetic=False)
        curr_obs = copy.deepcopy(base_obs)

        result = compute_apix(
            current_observations=curr_obs,
            base_observations=base_obs,
            route_weights=sample_route_weights,
            lead_weights=sample_lead_weights,
            index_date=date(2026, 9, 21),
            frequency="daily",
            variant="total_fare",
            base_value=100.0,
            allow_synthetic=False,
        )

        assert result.overall_apix is not None
        assert pytest.approx(result.overall_apix, 1e-6) == 100.0
        assert result.cell_coverage == 1.0
        assert result.variant == "total_fare"
        for r_code, r_idx in result.route_indices.items():
            assert pytest.approx(r_idx, 1e-6) == 100.0

    def test_scaling_all_prices_by_k_scales_index_by_k(self, sample_route_weights, sample_lead_weights):
        k = 1.185
        base_obs = create_sample_observations(price_mult=1.0, is_synthetic=False)
        curr_obs = create_sample_observations(price_mult=k, is_synthetic=False)

        result = compute_apix(
            current_observations=curr_obs,
            base_observations=base_obs,
            route_weights=sample_route_weights,
            lead_weights=sample_lead_weights,
            index_date=date(2026, 9, 21),
            variant="total_fare",
            base_value=100.0,
        )

        assert pytest.approx(result.overall_apix, 1e-5) == 100.0 * k

    def test_row_order_invariance(self, sample_route_weights, sample_lead_weights):
        base_obs = create_sample_observations(price_mult=1.0, is_synthetic=False)
        curr_obs = create_sample_observations(price_mult=1.12, is_synthetic=False)

        # Shuffle current and base observations
        shuffled_curr = copy.deepcopy(curr_obs)
        shuffled_base = copy.deepcopy(base_obs)
        random.seed(42)
        random.shuffle(shuffled_curr)
        random.shuffle(shuffled_base)

        res1 = compute_apix(
            current_observations=curr_obs,
            base_observations=base_obs,
            route_weights=sample_route_weights,
            lead_weights=sample_lead_weights,
            index_date=date(2026, 9, 21),
        )

        res2 = compute_apix(
            current_observations=shuffled_curr,
            base_observations=shuffled_base,
            route_weights=sample_route_weights,
            lead_weights=sample_lead_weights,
            index_date=date(2026, 9, 21),
        )

        assert pytest.approx(res1.overall_apix, 1e-8) == res2.overall_apix
        for r in sample_route_weights:
            assert pytest.approx(res1.route_indices[r], 1e-8) == res2.route_indices[r]

    def test_missing_cells_reflected_in_coverage(self, sample_route_weights, sample_lead_weights):
        base_obs = create_sample_observations(price_mult=1.0, is_synthetic=False)
        # Drop all BOM-BLR observations in current period (5 cells missing out of 20 total)
        curr_obs = [o for o in base_obs if o["route_code"] != "BOM-BLR"]

        result = compute_apix(
            current_observations=curr_obs,
            base_observations=base_obs,
            route_weights=sample_route_weights,
            lead_weights=sample_lead_weights,
            index_date=date(2026, 9, 21),
        )

        assert result.overall_apix is not None
        # 15 valid cells out of 20 = 75% coverage
        assert pytest.approx(result.cell_coverage, 1e-6) == 0.75
        assert result.route_indices["BOM-BLR"] is None

    def test_variants_extraction(self, sample_route_weights, sample_lead_weights):
        base_obs = create_sample_observations(price_mult=1.0, is_synthetic=False)
        curr_obs = create_sample_observations(price_mult=1.0, is_synthetic=False)

        for var in ["total_fare", "base_fare_only", "taxes_and_fees"]:
            res = compute_apix(
                current_observations=curr_obs,
                base_observations=base_obs,
                route_weights=sample_route_weights,
                lead_weights=sample_lead_weights,
                index_date=date(2026, 9, 21),
                variant=var,
            )
            assert res.overall_apix is not None
            assert pytest.approx(res.overall_apix, 1e-6) == 100.0

    def test_synthetic_data_refused_without_flag(self, sample_route_weights, sample_lead_weights):
        base_obs = create_sample_observations(price_mult=1.0, is_synthetic=False)
        curr_obs = create_sample_observations(price_mult=1.0, is_synthetic=True)  # Synthetic data

        with pytest.raises(ValueError, match="synthetic data"):
            compute_apix(
                current_observations=curr_obs,
                base_observations=base_obs,
                route_weights=sample_route_weights,
                lead_weights=sample_lead_weights,
                index_date=date(2026, 9, 21),
                allow_synthetic=False,
            )

    def test_synthetic_data_allowed_with_flag_and_suffix(self, sample_route_weights, sample_lead_weights):
        base_obs = create_sample_observations(price_mult=1.0, is_synthetic=True)
        curr_obs = create_sample_observations(price_mult=1.0, is_synthetic=True)

        res = compute_apix(
            current_observations=curr_obs,
            base_observations=base_obs,
            route_weights=sample_route_weights,
            lead_weights=sample_lead_weights,
            index_date=date(2026, 9, 21),
            variant="total_fare",
            allow_synthetic=True,
        )

        assert res.overall_apix is not None
        assert res.variant == "total_fare_synthetic"
        assert res.is_synthetic is True


# ─── Hypothesis Property-Based Testing ─────────────────────────────────────────

class TestHypothesisPropertyAxioms:
    @settings(max_examples=50)
    @given(
        st.lists(
            st.floats(min_value=500.0, max_value=25000.0, allow_nan=False, allow_infinity=False),
            min_size=2,
            max_size=10,
        ),
        st.floats(min_value=0.2, max_value=5.0, allow_nan=False, allow_infinity=False),
    )
    def test_property_proportionality_and_identity(self, base_prices, scalar_k):
        """
        Axiomatic Property: If all prices are multiplied by scalar k,
        the elementary index must equal k * base_value.
        """
        base_obs = [
            {"carrier_code": f"C{i}", "dep_band": "morning", "fare_class": "economy", "total_fare": p}
            for i, p in enumerate(base_prices)
        ]
        curr_obs = [
            {"carrier_code": f"C{i}", "dep_band": "morning", "fare_class": "economy", "total_fare": p * scalar_k}
            for i, p in enumerate(base_prices)
        ]

        idx, _ = compute_elementary_jevons(curr_obs, base_obs, base_value=100.0)
        assert idx is not None
        assert pytest.approx(idx, rel=1e-4) == 100.0 * scalar_k

    @settings(max_examples=50)
    @given(
        st.lists(
            st.floats(min_value=1000.0, max_value=15000.0, allow_nan=False, allow_infinity=False),
            min_size=3,
            max_size=8,
        )
    )
    def test_property_monotonicity(self, base_prices):
        """
        Axiomatic Property: If prices in period t2 are strictly higher than period t1,
        I(t2) must be strictly greater than I(t1).
        """
        base_obs = [
            {"carrier_code": f"C{i}", "dep_band": "morning", "fare_class": "economy", "total_fare": p}
            for i, p in enumerate(base_prices)
        ]
        curr_obs_1 = [
            {"carrier_code": f"C{i}", "dep_band": "morning", "fare_class": "economy", "total_fare": p * 1.1}
            for i, p in enumerate(base_prices)
        ]
        curr_obs_2 = [
            {"carrier_code": f"C{i}", "dep_band": "morning", "fare_class": "economy", "total_fare": p * 1.2}
            for i, p in enumerate(base_prices)
        ]

        idx1, _ = compute_elementary_jevons(curr_obs_1, base_obs, base_value=100.0)
        idx2, _ = compute_elementary_jevons(curr_obs_2, base_obs, base_value=100.0)

        assert idx1 is not None and idx2 is not None
        assert idx2 > idx1
