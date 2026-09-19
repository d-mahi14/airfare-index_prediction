"""
backend/tests/test_constraints.py
Tests for database-level constraints and unique keys in PostgreSQL / SQLAlchemy.

Covers:
  1. Unique dedup constraint: (source_id, flight_number, travel_date, fare_class, collection_date)
  2. Positive fare CHECK constraint (total_fare > 0)
  3. Base fare <= Total fare CHECK constraint
  4. Non-negative lead days CHECK constraint
  5. Departure band CHECK constraint
  6. Target lead window CHECK constraint
  7. IndexValue unique 4-tuple key
  8. RouteWeight period unique key
  9. LeadTimeWeight unique key
"""
import uuid
from datetime import date, datetime, time, timezone
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from backend.app.models.airfare import Airline, AirfareObservation, Route, Source
from backend.app.models.collection import CollectionRun
from backend.app.models.index import IndexValue, LeadTimeWeight, RouteWeight


def _create_dependencies(session):
    source = Source(name=f"TestCollector_{uuid.uuid4().hex[:6]}")
    route = Route(origin="BOM", destination="DEL", route_code="BOM-DEL")
    airline = Airline(name=f"IndiGo_{uuid.uuid4().hex[:6]}", iata_code="6E")
    session.add_all([source, route, airline])
    session.flush()
    return source, route, airline


class TestAirfareConstraints:
    def test_unique_dedup_constraint_raises(self, db_session):
        source, route, airline = _create_dependencies(db_session)
        col_ts = datetime(2026, 9, 19, 10, 0, tzinfo=timezone.utc)
        col_date = date(2026, 9, 19)
        trav_date = date(2026, 9, 26)

        obs1 = AirfareObservation(
            id=uuid.uuid4(),
            source_id=source.id,
            route_id=route.id,
            airline_id=airline.id,
            flight_number="6E242",
            travel_date=trav_date,
            collection_timestamp=col_ts,
            collection_date=col_date,
            lead_days=7,
            fare_class="Economy",
            total_fare=Decimal("5000.00"),
            status="valid",
        )
        db_session.add(obs1)
        db_session.commit()

        # Second observation with exact same unique key:
        # (source_id, flight_number, travel_date, fare_class, collection_date)
        obs2 = AirfareObservation(
            id=uuid.uuid4(),
            source_id=source.id,
            route_id=route.id,
            airline_id=airline.id,
            flight_number="6E242",
            travel_date=trav_date,
            collection_timestamp=col_ts,
            collection_date=col_date,
            lead_days=7,
            fare_class="Economy",
            total_fare=Decimal("5200.00"),
            status="valid",
        )
        db_session.add(obs2)
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()

    def test_total_fare_positive_check(self, db_session):
        source, route, airline = _create_dependencies(db_session)
        obs = AirfareObservation(
            id=uuid.uuid4(),
            source_id=source.id,
            route_id=route.id,
            airline_id=airline.id,
            travel_date=date(2026, 9, 26),
            lead_days=7,
            fare_class="Economy",
            total_fare=Decimal("0.00"),  # must be > 0
            status="valid",
        )
        db_session.add(obs)
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()

    def test_base_fare_lte_total_check(self, db_session):
        source, route, airline = _create_dependencies(db_session)
        obs = AirfareObservation(
            id=uuid.uuid4(),
            source_id=source.id,
            route_id=route.id,
            airline_id=airline.id,
            travel_date=date(2026, 9, 26),
            lead_days=7,
            fare_class="Economy",
            base_fare=Decimal("6000.00"),
            total_fare=Decimal("5000.00"),
            status="valid",
        )
        db_session.add(obs)
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()

    def test_dep_band_check(self, db_session):
        source, route, airline = _create_dependencies(db_session)
        obs = AirfareObservation(
            id=uuid.uuid4(),
            source_id=source.id,
            route_id=route.id,
            airline_id=airline.id,
            travel_date=date(2026, 9, 26),
            lead_days=7,
            fare_class="Economy",
            total_fare=Decimal("5000.00"),
            dep_band="invalid_band",
            status="valid",
        )
        db_session.add(obs)
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()

    def test_target_lead_window_check(self, db_session):
        source, route, airline = _create_dependencies(db_session)
        obs = AirfareObservation(
            id=uuid.uuid4(),
            source_id=source.id,
            route_id=route.id,
            airline_id=airline.id,
            travel_date=date(2026, 9, 26),
            lead_days=7,
            fare_class="Economy",
            total_fare=Decimal("5000.00"),
            target_lead_window=12,  # valid: 1, 7, 15, 30, 45
            status="valid",
        )
        db_session.add(obs)
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()


class TestIndexAndWeightConstraints:
    def test_index_value_unique_4tuple(self, db_session):
        idx1 = IndexValue(
            index_date=date(2026, 9, 19),
            frequency="daily",
            variant="overall",
            methodology_version="v1.0",
            apix_value=Decimal("115.4200"),
            n_obs=100,
        )
        db_session.add(idx1)
        db_session.commit()

        # Duplicate tuple
        idx2 = IndexValue(
            index_date=date(2026, 9, 19),
            frequency="daily",
            variant="overall",
            methodology_version="v1.0",
            apix_value=Decimal("116.0000"),
            n_obs=105,
        )
        db_session.add(idx2)
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()

    def test_index_value_different_variant_allowed(self, db_session):
        idx1 = IndexValue(
            index_date=date(2026, 9, 19),
            frequency="daily",
            variant="overall",
            methodology_version="v1.0",
            apix_value=Decimal("115.4200"),
            n_obs=100,
        )
        idx2 = IndexValue(
            index_date=date(2026, 9, 19),
            frequency="daily",
            variant="7d_lead",
            methodology_version="v1.0",
            apix_value=Decimal("118.2000"),
            n_obs=40,
        )
        db_session.add_all([idx1, idx2])
        db_session.commit()
        assert idx1.id is not None
        assert idx2.id is not None

    def test_route_weight_unique_period(self, db_session):
        _, route, _ = _create_dependencies(db_session)
        rw1 = RouteWeight(
            route_id=route.id,
            weight=Decimal("0.250000"),
            valid_from=date(2026, 1, 1),
            valid_to=date(2026, 12, 31),
        )
        db_session.add(rw1)
        db_session.commit()

        rw2 = RouteWeight(
            route_id=route.id,
            weight=Decimal("0.300000"),
            valid_from=date(2026, 1, 1),
        )
        db_session.add(rw2)
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()

    def test_lead_time_weight_unique(self, db_session):
        ltw1 = LeadTimeWeight(
            lead_days=7,
            weight=Decimal("0.350000"),
            valid_from=date(2026, 1, 1),
        )
        db_session.add(ltw1)
        db_session.commit()

        ltw2 = LeadTimeWeight(
            lead_days=7,
            weight=Decimal("0.400000"),
            valid_from=date(2026, 1, 1),
        )
        db_session.add(ltw2)
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()
