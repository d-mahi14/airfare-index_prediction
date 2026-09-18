"""
scraper/pipelines/storage.py
Database storage pipeline for airfare observations.

Responsibilities:
  1. Get or create Source / Route / Airline records (upsert pattern).
  2. Detect duplicate observations using a deterministic hash.
  3. Write valid observations to the DB.
  4. Update CollectionRun stats.
  5. Write rejected observations with status="rejected" for audit trail.

Duplicate detection strategy:
  A duplicate is defined as an observation with the same:
    (source_id, route_id, airline_id, travel_date, fare_class,
     collection_timestamp_date, flight_number)

  We use a DB query rather than a hash to avoid cross-session state issues.
  This is O(n) per collection run — acceptable for MVP batch sizes.

IMPORTANT: This module is the only place that writes to the DB.
           Collectors and validators never touch the DB directly.
"""
import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from backend.app.models.airfare import Airline, AirfareObservation, Route, Source
from backend.app.models.collection import CollectionRun
from backend.app.schemas.airfare import AirfareObservationCreate

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helper: upsert lookup tables
# ---------------------------------------------------------------------------

def _get_or_create_source(session: Session, name: str, base_url: Optional[str] = None) -> Source:
    """Return existing Source or create a new one."""
    source = session.query(Source).filter_by(name=name).first()
    if not source:
        source = Source(name=name, base_url=base_url, is_active=True)
        session.add(source)
        session.flush()  # get the id without committing
        logger.debug(f"Created new source: {name}")
    return source


def _get_or_create_route(session: Session, origin: str, destination: str) -> Route:
    """Return existing Route or create a new one."""
    route_code = f"{origin}-{destination}"
    route = session.query(Route).filter_by(route_code=route_code).first()
    if not route:
        route = Route(
            origin=origin,
            destination=destination,
            route_code=route_code,
            is_active=True,
        )
        session.add(route)
        session.flush()
        logger.debug(f"Created new route: {route_code}")
    return route


def _get_or_create_airline(
    session: Session,
    name: str,
    iata_code: Optional[str] = None,
) -> Airline:
    """Return existing Airline or create a new one."""
    airline = session.query(Airline).filter_by(name=name).first()
    if not airline:
        airline = Airline(name=name, iata_code=iata_code, is_active=True)
        session.add(airline)
        session.flush()
        logger.debug(f"Created new airline: {name}")
    return airline


# ---------------------------------------------------------------------------
# Duplicate detection
# ---------------------------------------------------------------------------

def _is_duplicate(
    session: Session,
    source_id: int,
    route_id: int,
    airline_id: Optional[int],
    travel_date,
    fare_class: str,
    flight_number: Optional[str],
    collection_date,
) -> bool:
    """
    Check if an identical observation already exists in the DB.

    Matching criteria:
      - same source + route + airline + travel_date + fare_class
      - same flight_number (if available)
      - collected on the same calendar date
    """
    query = session.query(AirfareObservation).filter(
        AirfareObservation.source_id == source_id,
        AirfareObservation.route_id == route_id,
        AirfareObservation.travel_date == travel_date,
        AirfareObservation.fare_class == fare_class,
        AirfareObservation.status != "duplicate",  # don't compare against old duplicates
    )
    if airline_id is not None:
        query = query.filter(AirfareObservation.airline_id == airline_id)
    if flight_number:
        query = query.filter(AirfareObservation.flight_number == flight_number)

    # Check if same-day observation exists
    existing = query.filter(
        AirfareObservation.collection_timestamp >= datetime.combine(
            collection_date, datetime.min.time()
        ).replace(tzinfo=timezone.utc)
    ).first()

    return existing is not None


# ---------------------------------------------------------------------------
# Collection run management
# ---------------------------------------------------------------------------

def create_collection_run(
    session: Session,
    source: Source,
    route: Route,
) -> CollectionRun:
    """Create and persist a new CollectionRun record."""
    run = CollectionRun(
        id=uuid.uuid4(),
        source_id=source.id,
        route_id=route.id,
        start_time=datetime.now(timezone.utc),
    )
    session.add(run)
    session.flush()
    logger.info(f"Collection run started: {run.id}")
    return run


def finish_collection_run(
    session: Session,
    run: CollectionRun,
    records_found: int,
    records_saved: int,
    records_rejected: int,
    error_message: Optional[str] = None,
) -> None:
    """Update a CollectionRun with completion statistics."""
    run.end_time = datetime.now(timezone.utc)
    run.records_found = records_found
    run.records_saved = records_saved
    run.records_rejected = records_rejected
    run.error_message = error_message
    session.flush()
    logger.info(
        f"Collection run {run.id} finished: "
        f"found={records_found} saved={records_saved} rejected={records_rejected}"
    )


# ---------------------------------------------------------------------------
# Main storage function
# ---------------------------------------------------------------------------

def store_observations(
    session: Session,
    observations: List[AirfareObservationCreate],
    rejected: List[Tuple[AirfareObservationCreate, str]],
    run: CollectionRun,
) -> Tuple[int, int, int]:
    """
    Persist validated observations and rejected records to the database.

    Valid observations → status="valid"
    Rejected observations → status="rejected" with rejection_reason
    Duplicates → status="duplicate"

    Returns:
        (saved_count, rejected_count, duplicate_count)
    """
    saved_count = 0
    rejected_count = 0
    duplicate_count = 0

    source_id = run.source_id
    route_id = run.route_id

    # --- Store valid observations ---
    for obs in observations:
        airline = _get_or_create_airline(session, obs.airline_name, obs.airline_iata)
        collection_date = obs.collection_timestamp.date()

        # Duplicate check
        if _is_duplicate(
            session,
            source_id=source_id,
            route_id=route_id,
            airline_id=airline.id,
            travel_date=obs.travel_date,
            fare_class=obs.fare_class,
            flight_number=obs.flight_number,
            collection_date=collection_date,
        ):
            # Store as duplicate for audit trail
            dup_record = AirfareObservation(
                id=uuid.uuid4(),
                collection_run_id=run.id,
                collection_timestamp=obs.collection_timestamp,
                source_id=source_id,
                route_id=route_id,
                airline_id=airline.id,
                flight_number=obs.flight_number,
                travel_date=obs.travel_date,
                lead_days=obs.lead_days,
                fare_class=obs.fare_class,
                base_fare=obs.base_fare,
                taxes=obs.taxes,
                fees=obs.fees,
                total_fare=obs.total_fare,
                currency=obs.currency,
                availability=obs.availability,
                status="duplicate",
                rejection_reason="duplicate_same_day_observation",
                raw_reference=obs.raw_reference,
            )
            session.add(dup_record)
            duplicate_count += 1
            logger.debug(f"Duplicate observation: {obs.airline_name} {obs.travel_date}")
            continue

        db_obs = AirfareObservation(
            id=uuid.uuid4(),
            collection_run_id=run.id,
            collection_timestamp=obs.collection_timestamp,
            source_id=source_id,
            route_id=route_id,
            airline_id=airline.id,
            flight_number=obs.flight_number,
            travel_date=obs.travel_date,
            lead_days=obs.lead_days,
            fare_class=obs.fare_class,
            base_fare=obs.base_fare,
            taxes=obs.taxes,
            fees=obs.fees,
            total_fare=obs.total_fare,
            currency=obs.currency,
            availability=obs.availability,
            status="valid",
            raw_reference=obs.raw_reference,
        )
        session.add(db_obs)
        saved_count += 1

    # --- Store rejected observations (never silently discard) ---
    for obs, reason in rejected:
        airline = _get_or_create_airline(session, obs.airline_name, obs.airline_iata)
        rej_record = AirfareObservation(
            id=uuid.uuid4(),
            collection_run_id=run.id,
            collection_timestamp=obs.collection_timestamp,
            source_id=source_id,
            route_id=route_id,
            airline_id=airline.id,
            flight_number=obs.flight_number,
            travel_date=obs.travel_date,
            lead_days=obs.lead_days or 0,
            fare_class=obs.fare_class or "Unknown",
            total_fare=obs.total_fare or Decimal("0"),
            currency=obs.currency or "INR",
            status="rejected",
            rejection_reason=reason,
            raw_reference=obs.raw_reference,
        )
        session.add(rej_record)
        rejected_count += 1

    session.flush()
    logger.info(
        f"Storage: saved={saved_count} rejected={rejected_count} "
        f"duplicates={duplicate_count}"
    )
    return saved_count, rejected_count, duplicate_count
