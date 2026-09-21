"""
backend/tests/test_serving_and_validation.py
Comprehensive unit and API integration tests for serve-time validation gate,
/fares/search endpoint, route watchlist, and synthetic demo banner.
"""
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Set, Tuple
import uuid

from fastapi.testclient import TestClient
import pytest
from sqlalchemy.orm import Session

from backend.app.database import get_db_session
from backend.app.main import app
from backend.app.models.airfare import Airline, AirfareObservation, Route, Source
from backend.app.models.watchlist import RouteWatchlist
from scraper.watchlist_reader import evaluate_watchlist_collection_eligibility, get_watchlist_candidates
from serving.validation import FareGate, FareGateConfig, FareGateResult


# ---------------------------------------------------------------------------
# Test Helpers
# ---------------------------------------------------------------------------

def _create_mock_obs_dict(
    flight_number: str = "6E-501",
    airline_iata: str = "6E",
    airline_name: str = "IndiGo",
    source_name: str = "IndiGo",
    origin: str = "DEL",
    destination: str = "BOM",
    route_code: str = "DEL-BOM",
    travel_date: date = date(2026, 10, 15),
    collection_timestamp: Optional[datetime] = None,
    total_fare: Decimal = Decimal("5000.00"),
    base_fare: Optional[Decimal] = None,
    taxes: Optional[Decimal] = None,
    udf_psf: Optional[Decimal] = None,
    convenience_fee: Optional[Decimal] = None,
    other_fees: Optional[Decimal] = None,
    is_sold_out: bool = False,
    availability: str = "available",
    is_synthetic: bool = False,
    is_imputed: bool = False,
) -> dict:
    ts = collection_timestamp or datetime.now(timezone.utc)
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

    return {
        "flight_number": flight_number,
        "airline_iata": airline_iata,
        "airline_name": airline_name,
        "source_name": source_name,
        "origin": origin,
        "destination": destination,
        "route_code": route_code,
        "travel_date": travel_date,
        "collection_timestamp": ts,
        "total_fare": total_fare,
        "base_fare": base_fare,
        "taxes": taxes,
        "udf_psf": udf_psf,
        "convenience_fee": convenience_fee,
        "other_fees": other_fees,
        "is_sold_out": is_sold_out,
        "availability": availability,
        "is_synthetic": is_synthetic,
        "is_imputed": is_imputed,
    }


# ---------------------------------------------------------------------------
# 1. FareGate Unit Tests
# ---------------------------------------------------------------------------

class TestFareGateUnit:
    @pytest.fixture
    def gate(self):
        cfg = FareGateConfig(
            max_age_hours=36.0,
            fee_tolerance=Decimal("0.05"),
            cross_source_tolerance_pct=0.10,
            cross_source_tolerance_abs=Decimal("500.00"),
            default_plausible_min=Decimal("1500.00"),
            default_plausible_max=Decimal("40000.00"),
            allow_synthetic=False,
            route_plausible_bands={"DEL-BOM": {"min": 2000.0, "max": 35000.0}},
        )
        return FareGate(config=cfg)

    def test_valid_fare_passes(self, gate):
        fare = _create_mock_obs_dict(total_fare=Decimal("5000.00"))
        res = gate.evaluate_fare(fare)
        assert res.status == "ok"
        assert res.confidence == "high"
        assert res.warnings == []

    def test_stale_data_hidden(self, gate):
        old_ts = datetime.now(timezone.utc) - timedelta(hours=48)
        fare = _create_mock_obs_dict(collection_timestamp=old_ts)
        res = gate.evaluate_fare(fare)
        assert res.status == "hidden"
        assert "stale_data" in res.warnings

    def test_breakup_mismatch_hidden(self, gate):
        fare = _create_mock_obs_dict(
            total_fare=Decimal("6000.00"),  # Components sum to 5000
            base_fare=Decimal("4000.00"),
            taxes=Decimal("200.00"),
            udf_psf=Decimal("500.00"),
            convenience_fee=Decimal("300.00"),
        )
        res = gate.evaluate_fare(fare)
        assert res.status == "hidden"
        assert "breakup_mismatch" in res.warnings

    def test_sold_out_hidden(self, gate):
        fare = _create_mock_obs_dict(is_sold_out=True, availability="sold_out")
        res = gate.evaluate_fare(fare)
        assert res.status == "hidden"
        assert "sold_out" in res.warnings

    def test_unusual_price_flagged(self, gate):
        # DEL-BOM max plausible is 35000.00; test with 45000.00
        fare = _create_mock_obs_dict(
            total_fare=Decimal("45000.00"),
            base_fare=Decimal("40000.00"),
            taxes=Decimal("2500.00"),
            udf_psf=Decimal("2000.00"),
            convenience_fee=Decimal("500.00"),
        )
        res = gate.evaluate_fare(fare)
        assert res.status == "flagged"
        assert "unusual_price" in res.warnings
        assert res.confidence == "medium"

    def test_cross_source_disagreement_lowers_confidence(self, gate):
        fare1 = _create_mock_obs_dict(source_name="IndiGo", total_fare=Decimal("4000.00"))
        # Quote on same flight from OTA is 6000 (50% higher > 10% tolerance)
        cross_quotes = [("IndiGo", Decimal("4000.00")), ("MakeMyTrip", Decimal("6000.00"))]

        res = gate.evaluate_fare(fare1, cross_source_quotes=cross_quotes)
        assert res.status == "flagged"
        assert "cross_source_disagreement" in res.warnings
        assert res.confidence == "medium"

    def test_synthetic_data_hidden_by_default(self, gate):
        fare = _create_mock_obs_dict(is_synthetic=True)
        res = gate.evaluate_fare(fare, allow_synthetic_override=False)
        assert res.status == "hidden"
        assert "synthetic_data" in res.warnings

    def test_synthetic_data_allowed_when_demo_mode(self, gate):
        fare = _create_mock_obs_dict(is_synthetic=True)
        res = gate.evaluate_fare(fare, allow_synthetic_override=True)
        assert res.status == "ok"
        assert "synthetic_demo_data" in res.warnings


# ---------------------------------------------------------------------------
# 2. Search Endpoint & API Integration Tests
# ---------------------------------------------------------------------------

class TestSearchEndpoint:
    @pytest.fixture
    def client(self, db_session):
        def override_get_db():
            yield db_session

        from backend.app.database import get_db, get_db_session
        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_db_session] = override_get_db
        client = TestClient(app)
        yield client
        app.dependency_overrides.clear()

    @pytest.fixture
    def seeded_data(self, db_session: Session):
        # Create route
        route = db_session.query(Route).filter_by(route_code="DEL-BOM").first()
        if not route:
            route = Route(origin="DEL", destination="BOM", route_code="DEL-BOM", is_active=True)
            db_session.add(route)
            db_session.flush()

        # Clean existing observations on this route to ensure test isolation
        db_session.query(AirfareObservation).filter_by(route_id=route.id).delete()
        db_session.flush()

        # Create source
        src = db_session.query(Source).filter_by(name="IndiGo").first()
        if not src:
            src = Source(name="IndiGo", base_url="https://www.goindigo.in", is_active=True)
            db_session.add(src)
            db_session.flush()

        # Create airline
        airline = db_session.query(Airline).filter_by(iata_code="6E").first()
        if not airline:
            airline = Airline(name="IndiGo", iata_code="6E", is_active=True)
            db_session.add(airline)
            db_session.flush()

        # Create observations
        travel_dt = date(2026, 10, 15)
        now_ts = datetime.now(timezone.utc)
        obs1 = AirfareObservation(
            id=uuid.uuid4(),
            source_id=src.id,
            route_id=route.id,
            airline_id=airline.id,
            flight_number="6E-2041",
            travel_date=travel_dt,
            lead_days=24,
            fare_class="Economy",
            base_fare=Decimal("3800.00"),
            taxes=Decimal("190.00"),
            udf_psf=Decimal("440.00"),
            convenience_fee=Decimal("300.00"),
            other_fees=Decimal("0.00"),
            total_fare=Decimal("4730.00"),
            currency="INR",
            dep_time=time(5, 45),
            dep_band="early",
            stops=0,
            duration_min=170,
            is_sold_out=False,
            availability="available",
            status="valid",
            is_synthetic=False,
            collection_timestamp=now_ts,
            collection_date=now_ts.date(),
        )

        obs2_synth = AirfareObservation(
            id=uuid.uuid4(),
            source_id=src.id,
            route_id=route.id,
            airline_id=airline.id,
            flight_number="MOCK-999",
            travel_date=travel_dt,
            lead_days=24,
            fare_class="Economy",
            base_fare=Decimal("3000.00"),
            taxes=Decimal("150.00"),
            udf_psf=Decimal("300.00"),
            convenience_fee=Decimal("200.00"),
            other_fees=Decimal("0.00"),
            total_fare=Decimal("3650.00"),
            currency="INR",
            dep_time=time(14, 00),
            dep_band="afternoon",
            stops=0,
            duration_min=120,
            is_sold_out=False,
            availability="available",
            status="valid",
            is_synthetic=True,
            collection_timestamp=now_ts,
            collection_date=now_ts.date(),
        )

        db_session.add_all([obs1, obs2_synth])
        db_session.commit()
        return {"route": route, "obs_real": obs1, "obs_synth": obs2_synth, "travel_date": travel_dt}

    def test_auth_missing_or_invalid_key_returns_401(self, client):
        # Missing key
        resp = client.get("/fares/search?origin=DEL&destination=BOM&date=2026-10-15")
        assert resp.status_code == 401

        # Invalid key
        resp_invalid = client.get(
            "/fares/search?origin=DEL&destination=BOM&date=2026-10-15",
            headers={"X-API-Key": "invalid_unauthorized_key"},
        )
        assert resp_invalid.status_code == 401

    def test_valid_search_returns_flights_and_summary(self, client, seeded_data):
        travel_dt_str = seeded_data["travel_date"].isoformat()
        resp = client.get(
            f"/fares/search?origin=DEL&destination=BOM&date={travel_dt_str}",
            headers={"X-API-Key": "apix_dev_key_2024"},
        )
        assert resp.status_code == 200
        data = resp.json()

        assert data["route"]["route_code"] == "DEL-BOM"
        assert data["summary"]["n_flights"] == 1  # Only real observation by default
        assert data["summary"]["cheapest_fare"] == 4730.0

        flights = data["flights"]
        assert len(flights) == 1
        f1 = flights[0]
        assert f1["flight_number"] == "6E-2041"
        assert f1["pricing"]["total_fare"] == 4730.0
        assert f1["pricing"]["base_fare"] == 3800.0
        assert f1["is_synthetic"] is False
        assert f1["confidence"] == "high"
        assert f1["gate_status"] == "ok"
        assert data["coverage"]["is_covered"] is True

    def test_synthetic_data_excluded_by_default_and_allowed_in_demo_mode(self, client, seeded_data):
        travel_dt_str = seeded_data["travel_date"].isoformat()

        # 1. Non-demo mode
        resp_prod = client.get(
            f"/fares/search?origin=DEL&destination=BOM&date={travel_dt_str}&demo_mode=false",
            headers={"X-API-Key": "apix_dev_key_2024"},
        )
        assert resp_prod.status_code == 200
        data_prod = resp_prod.json()
        assert data_prod["summary"]["n_flights"] == 1
        assert "banner" not in data_prod

        # 2. Demo mode enabled
        resp_demo = client.get(
            f"/fares/search?origin=DEL&destination=BOM&date={travel_dt_str}&demo_mode=true",
            headers={"X-API-Key": "apix_dev_key_2024"},
        )
        assert resp_demo.status_code == 200
        data_demo = resp_demo.json()
        assert data_demo["summary"]["n_flights"] == 2  # Real + Synthetic
        assert data_demo.get("banner") == "SYNTHETIC DEMO DATA - NOT FOR PRODUCTION PRICE INDEX"
        assert data_demo.get("is_synthetic") is True

    def test_unknown_route_returns_not_covered_and_records_watchlist(self, client, db_session):
        resp = client.get(
            "/fares/search?origin=CCU&destination=GOI&date=2026-10-15",
            headers={"X-API-Key": "apix_dev_key_2024"},
        )
        assert resp.status_code == 404
        data = resp.json()["detail"]
        assert data["status"] == "not_covered"
        assert data["route_code"] == "CCU-GOI"
        assert data["watchlist_registered"] is True

        # Verify entry in database
        entry = db_session.query(RouteWatchlist).filter_by(route_code="CCU-GOI").first()
        assert entry is not None
        assert entry.origin == "CCU"
        assert entry.destination == "GOI"
        assert entry.request_count >= 1

    def test_watchlist_deduplication_and_rate_limiting(self, client, db_session):
        # Make multiple queries for same uncovered route
        for _ in range(3):
            client.get(
                "/fares/search?origin=IXC&destination=PAT&date=2026-10-15",
                headers={"X-API-Key": "apix_dev_key_2024"},
            )

        entries = db_session.query(RouteWatchlist).filter_by(route_code="IXC-PAT").all()
        assert len(entries) == 1
        assert entries[0].request_count == 3

    def test_search_estimated_nearest_window_fallback(self, client, seeded_data):
        # Query a date where no direct quotes exist (e.g. 2026-10-18 vs seeded 2026-10-15)
        resp = client.get(
            "/fares/search?origin=DEL&destination=BOM&date=2026-10-18",
            headers={"X-API-Key": "apix_dev_key_2024"},
        )
        assert resp.status_code == 200
        data = resp.json()

        assert data["lead_time_position"]["is_estimated"] is True
        assert "No direct observations collected for travel date" in data["lead_time_position"]["explanation"]
        assert len(data["flights"]) == 1
        assert data["flights"][0]["is_imputed"] is True
        assert "nearest_window_estimate" in data["flights"][0]["warnings"]


# ---------------------------------------------------------------------------
# 3. Watchlist Compliance Reader Tests
# ---------------------------------------------------------------------------

class TestWatchlistReaderCompliance:
    def test_evaluate_watchlist_compliance(self, db_session):
        res = evaluate_watchlist_collection_eligibility(session=db_session)
        assert "candidate_count" in res
        # Since all sources are in recorded_fixture mode per COMPLIANCE.md
        assert res["eligible_for_live_collection"] is False
        assert "recorded_fixture mode" in res["compliance_notice"]
