"""
backend/tests/test_storage.py
Tests for the DB storage pipeline using PostgreSQL test DB.

Validates:
  - Source/Route/Airline upsert (get-or-create)
  - Valid observation written with status="valid"
  - Rejected observation written with status="rejected"
  - Duplicate detection — second identical observation detected and duplicate count incremented
  - CollectionRun record created and updated correctly
"""
import sys
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from backend.app.models.airfare import Airline, AirfareObservation, Route, Source
from backend.app.models.collection import CollectionRun
from backend.app.schemas.airfare import AirfareObservationCreate
from scraper.pipelines.storage import (
    _get_or_create_airline,
    _get_or_create_route,
    _get_or_create_source,
    create_collection_run,
    finish_collection_run,
    store_observations,
)

_COLLECTION_TS = datetime(2026, 9, 18, 10, 0, 0, tzinfo=timezone.utc)
_TRAVEL_DATE = date(2026, 9, 25)


def _make_obs(**overrides) -> AirfareObservationCreate:
    defaults = {
        "collection_timestamp": _COLLECTION_TS,
        "source_name": "TestCollector",
        "origin": "BOM",
        "destination": "DEL",
        "airline_name": "IndiGo",
        "airline_iata": "6E",
        "flight_number": "6E123",
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


class TestGetOrCreate:
    def test_source_created(self, db_session):
        source = _get_or_create_source(db_session, "TestCollector")
        db_session.commit()
        assert source.id is not None
        assert source.name == "TestCollector"

    def test_source_idempotent(self, db_session):
        s1 = _get_or_create_source(db_session, "TestCollector")
        db_session.commit()
        s2 = _get_or_create_source(db_session, "TestCollector")
        db_session.commit()
        assert s1.id == s2.id

    def test_route_created(self, db_session):
        route = _get_or_create_route(db_session, "BOM", "DEL")
        db_session.commit()
        assert route.route_code == "BOM-DEL"
        assert route.origin == "BOM"
        assert route.destination == "DEL"

    def test_route_idempotent(self, db_session):
        r1 = _get_or_create_route(db_session, "BOM", "DEL")
        db_session.commit()
        r2 = _get_or_create_route(db_session, "BOM", "DEL")
        assert r1.id == r2.id

    def test_airline_created(self, db_session):
        airline = _get_or_create_airline(db_session, "IndiGo", "6E")
        db_session.commit()
        assert airline.name == "IndiGo"
        assert airline.iata_code == "6E"

    def test_airline_idempotent(self, db_session):
        a1 = _get_or_create_airline(db_session, "IndiGo", "6E")
        db_session.commit()
        a2 = _get_or_create_airline(db_session, "IndiGo")
        assert a1.id == a2.id


class TestCollectionRun:
    def test_collection_run_created(self, db_session):
        source = _get_or_create_source(db_session, "TestCollector")
        route = _get_or_create_route(db_session, "BOM", "DEL")
        db_session.commit()

        run = create_collection_run(db_session, source, route)
        db_session.commit()

        assert run.id is not None
        assert run.source_id == source.id
        assert run.route_id == route.id
        assert run.status == "running"
        assert run.end_time is None

    def test_collection_run_finished(self, db_session):
        source = _get_or_create_source(db_session, "TestCollector")
        route = _get_or_create_route(db_session, "BOM", "DEL")
        db_session.commit()

        run = create_collection_run(db_session, source, route)
        db_session.commit()

        finish_collection_run(db_session, run, 5, 4, 1, blocked_count=0, captcha_count=0)
        db_session.commit()

        assert run.end_time is not None
        assert run.status == "completed"
        assert run.records_found == 5
        assert run.records_saved == 4
        assert run.records_rejected == 1


class TestStoreObservations:
    def _setup_run(self, db_session) -> CollectionRun:
        source = _get_or_create_source(db_session, "TestCollector")
        route = _get_or_create_route(db_session, "BOM", "DEL")
        db_session.commit()
        run = create_collection_run(db_session, source, route)
        db_session.commit()
        return run

    def test_valid_observation_stored(self, db_session):
        run = self._setup_run(db_session)
        obs = _make_obs()

        saved, rejected, dupes = store_observations(db_session, [obs], [], run)
        db_session.commit()

        assert saved == 1
        assert rejected == 0
        assert dupes == 0

        stored = db_session.query(AirfareObservation).filter_by(status="valid").first()
        assert stored is not None
        assert stored.total_fare == Decimal("4900.00")
        assert stored.lead_days == 7
        assert stored.status == "valid"
        assert stored.is_synthetic is True

    def test_rejected_observation_stored(self, db_session):
        run = self._setup_run(db_session)
        obs = _make_obs()
        reason = "sold_out_flight"

        saved, rejected, dupes = store_observations(db_session, [], [(obs, reason)], run)
        db_session.commit()

        assert saved == 0
        assert rejected == 1

        stored = db_session.query(AirfareObservation).filter_by(status="rejected").first()
        assert stored is not None
        assert stored.rejection_reason == "sold_out_flight"

    def test_duplicate_detection(self, db_session):
        """Second identical observation in same session → detected and duplicate count incremented."""
        run = self._setup_run(db_session)
        obs1 = _make_obs()
        obs2 = _make_obs()  # exact same unique key

        # First insert
        saved, _, _ = store_observations(db_session, [obs1], [], run)
        db_session.commit()
        assert saved == 1

        # Second insert of identical observation
        saved2, _, dupes = store_observations(db_session, [obs2], [], run)
        db_session.commit()
        assert saved2 == 0
        assert dupes == 1

        all_obs = db_session.query(AirfareObservation).all()
        assert len(all_obs) == 1
        assert all_obs[0].status == "valid"

    def test_different_airlines_not_duplicate(self, db_session):
        """Different airline on same route+date → NOT a duplicate."""
        run = self._setup_run(db_session)
        obs1 = _make_obs(airline_name="IndiGo", flight_number="6E123")
        obs2 = _make_obs(airline_name="Air India", airline_iata="AI", flight_number="AI123")

        saved, _, dupes = store_observations(db_session, [obs1, obs2], [], run)
        db_session.commit()

        assert saved == 2
        assert dupes == 0
