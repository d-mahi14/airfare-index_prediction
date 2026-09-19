"""
backend/tests/test_schemas.py
Tests for the AirfareObservationCreate Pydantic schema.

Covers:
  - Valid minimal observation
  - Missing required fields
  - Non-positive fares
  - total_fare < base_fare
  - Fee breakdown summation check (within 0.05 tolerance)
  - Invalid currency
  - Invalid fare class
  - IATA code normalization
  - Route-to-self rejection
  - Availability normalization
  - Departure band validation and auto-derivation
  - Target lead window validation
"""
import sys
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from backend.app.schemas.airfare import AirfareObservationCreate

# A future travel date we'll use across tests
_TODAY = datetime(2026, 9, 18, 10, 0, 0, tzinfo=timezone.utc)
_TRAVEL_DATE = date(2026, 9, 25)  # T+7


def _base_obs(**overrides) -> dict:
    """Minimal valid observation dict."""
    d = {
        "collection_timestamp": _TODAY,
        "source_name": "TestCollector",
        "origin": "BOM",
        "destination": "DEL",
        "airline_name": "IndiGo",
        "travel_date": _TRAVEL_DATE,
        "total_fare": Decimal("4900.00"),
    }
    d.update(overrides)
    return d


class TestValidObservation:
    def test_minimal_valid(self):
        obs = AirfareObservationCreate(**_base_obs())
        assert obs.origin == "BOM"
        assert obs.destination == "DEL"
        assert obs.lead_days == 7
        assert obs.currency == "INR"
        assert obs.fare_class == "Economy"
        assert obs.availability == "available"
        assert obs.is_synthetic is True

    def test_full_valid(self):
        obs = AirfareObservationCreate(
            **_base_obs(
                airline_iata="6E",
                flight_number="6E123",
                base_fare=Decimal("4200.00"),
                taxes=Decimal("200.00"),
                udf_psf=Decimal("300.00"),
                convenience_fee=Decimal("200.00"),
                other_fees=Decimal("0.00"),
                total_fare=Decimal("4900.00"),
                fare_class="Economy",
                dep_time=time(8, 30),
                target_lead_window=7,
                availability="available",
            )
        )
        assert obs.airline_iata == "6E"
        assert obs.flight_number == "6E123"
        assert obs.base_fare == Decimal("4200.00")
        assert obs.total_fare == Decimal("4900.00")
        assert obs.taxes == Decimal("200.00")
        assert obs.udf_psf == Decimal("300.00")
        assert obs.convenience_fee == Decimal("200.00")
        assert obs.dep_band == "morning"  # auto-derived from 08:30

    def test_iata_codes_uppercased(self):
        obs = AirfareObservationCreate(**_base_obs(origin="bom", destination="del"))
        assert obs.origin == "BOM"
        assert obs.destination == "DEL"

    def test_currency_uppercased(self):
        obs = AirfareObservationCreate(**_base_obs(currency="inr"))
        assert obs.currency == "INR"

    def test_fare_class_normalized(self):
        obs = AirfareObservationCreate(**_base_obs(fare_class="economy"))
        assert obs.fare_class == "Economy"

    def test_route_code_property(self):
        obs = AirfareObservationCreate(**_base_obs())
        assert obs.route_code == "BOM-DEL"


class TestMissingFields:
    def test_missing_origin_raises(self):
        d = _base_obs()
        del d["origin"]
        with pytest.raises(ValidationError):
            AirfareObservationCreate(**d)

    def test_missing_total_fare_raises(self):
        d = _base_obs()
        del d["total_fare"]
        with pytest.raises(ValidationError):
            AirfareObservationCreate(**d)

    def test_missing_airline_raises(self):
        d = _base_obs()
        del d["airline_name"]
        with pytest.raises(ValidationError):
            AirfareObservationCreate(**d)


class TestFareValidation:
    def test_negative_total_fare_raises(self):
        with pytest.raises(ValidationError):
            AirfareObservationCreate(**_base_obs(total_fare=Decimal("-100.00")))

    def test_zero_total_fare_raises(self):
        """Zero total fare is rejected by schema (fares must be > 0)."""
        with pytest.raises(ValidationError):
            AirfareObservationCreate(**_base_obs(total_fare=Decimal("0.00")))

    def test_total_less_than_base_raises(self):
        with pytest.raises(ValidationError, match="total_fare"):
            AirfareObservationCreate(
                **_base_obs(
                    base_fare=Decimal("5000.00"),
                    total_fare=Decimal("4000.00"),
                )
            )

    def test_base_equals_total_passes(self):
        """base_fare == total_fare is valid (no taxes/fees scenario)."""
        obs = AirfareObservationCreate(
            **_base_obs(
                base_fare=Decimal("4900.00"),
                taxes=Decimal("0.00"),
                udf_psf=Decimal("0.00"),
                convenience_fee=Decimal("0.00"),
                other_fees=Decimal("0.00"),
                total_fare=Decimal("4900.00"),
            )
        )
        assert obs.base_fare == obs.total_fare

    def test_fee_breakdown_mismatch_raises(self):
        """Mismatched sum of base + taxes + fees raises ValidationError."""
        with pytest.raises(ValidationError, match="must equal base_fare"):
            AirfareObservationCreate(
                **_base_obs(
                    base_fare=Decimal("4000.00"),
                    taxes=Decimal("500.00"),
                    udf_psf=Decimal("100.00"),
                    convenience_fee=Decimal("100.00"),
                    other_fees=Decimal("0.00"),
                    total_fare=Decimal("5000.00"),  # Expected 4700.00
                )
            )


class TestRouteValidation:
    def test_origin_equals_destination_raises(self):
        with pytest.raises(ValidationError, match="origin and destination must differ"):
            AirfareObservationCreate(**_base_obs(origin="BOM", destination="BOM"))


class TestCurrencyValidation:
    def test_invalid_currency_raises(self):
        with pytest.raises(ValidationError, match="Unsupported currency"):
            AirfareObservationCreate(**_base_obs(currency="USD"))


class TestFareClassValidation:
    def test_invalid_fare_class_raises(self):
        with pytest.raises(ValidationError, match="Invalid fare_class"):
            AirfareObservationCreate(**_base_obs(fare_class="TurboClass"))

    def test_business_class(self):
        obs = AirfareObservationCreate(**_base_obs(fare_class="Business"))
        assert obs.fare_class == "Business"

    def test_premium_economy(self):
        obs = AirfareObservationCreate(**_base_obs(fare_class="Premium Economy"))
        assert obs.fare_class == "Premium Economy"


class TestDepartureAndLeadValidation:
    def test_invalid_dep_band_raises(self):
        with pytest.raises(ValidationError, match="Invalid dep_band"):
            AirfareObservationCreate(**_base_obs(dep_band="midnight"))

    def test_invalid_target_lead_window_raises(self):
        with pytest.raises(ValidationError, match="Invalid target_lead_window"):
            AirfareObservationCreate(**_base_obs(target_lead_window=10))

    def test_valid_target_lead_windows(self):
        for w in [1, 7, 15, 30, 45]:
            obs = AirfareObservationCreate(**_base_obs(target_lead_window=w))
            assert obs.target_lead_window == w
