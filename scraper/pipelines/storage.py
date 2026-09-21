"""
scraper/pipelines/storage.py
Database storage pipeline for airfare observations.

Responsibilities:
  1. Get or create Source / Route / Airline records (upsert pattern).
  2. Detect duplicate observations using the unique key:
     (source_id, flight_number, travel_date, fare_class, collection_date).
  3. Write valid observations to the DB.
  4. Update CollectionRun stats (status, saved, rejected, blocked, captcha).
  5. Write rejected observations with status="rejected" for audit trail.
"""
import logging
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import List, Optional, Tuple
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from backend.app.models.airfare import Airline, AirfareObservation, Route, Source
from backend.app.models.collection import CollectionRun
from backend.app.schemas.airfare import AirfareObservationCreate

logger = logging.getLogger(__name__)

KOLKATA_TZ = ZoneInfo("Asia/Kolkata")


def _get_or_create_source(session: Session, name: str, base_url: Optional[str] = None) -> Source:
    """Return existing Source or create a new one."""
    source = session.query(Source).filter_by(name=name).first()
    if not source:
        source = Source(name=name, base_url=base_url, is_active=True)
        session.add(source)
        session.flush()
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


def _is_duplicate(
    session: Session,
    source_id: int,
    flight_number: Optional[str],
    travel_date: date,
    fare_class: str,
    collection_date: date,
) -> bool:
    """
    Check if an identical observation already exists in the DB using the unique key:
    (source_id, flight_number, travel_date, fare_class, collection_date).
    """
    query = session.query(AirfareObservation).filter(
        AirfareObservation.source_id == source_id,
        AirfareObservation.travel_date == travel_date,
        AirfareObservation.fare_class == fare_class,
        AirfareObservation.collection_date == collection_date,
        AirfareObservation.status != "duplicate",
    )
    if flight_number is not None:
        query = query.filter(AirfareObservation.flight_number == flight_number)

    return query.first() is not None


def create_collection_run(
    session: Session,
    source: Source,
    route: Optional[Route] = None,
) -> CollectionRun:
    """Create and persist a new CollectionRun record."""
    run = CollectionRun(
        id=uuid.uuid4(),
        source_id=source.id,
        route_id=route.id if route else None,
        status="running",
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
    blocked_count: int = 0,
    captcha_count: int = 0,
    status: str = "completed",
    error_message: Optional[str] = None,
) -> None:
    """Update a CollectionRun with completion statistics."""
    run.end_time = datetime.now(timezone.utc)
    run.records_found = records_found
    run.records_saved = records_saved
    run.records_rejected = records_rejected
    run.blocked_count = blocked_count
    run.captcha_count = captcha_count
    run.status = status if not error_message else "failed"
    run.error_message = error_message
    session.flush()
    logger.info(
        f"Collection run {run.id} finished: status={run.status} "
        f"found={records_found} saved={records_saved} rejected={records_rejected}"
    )


def store_observations(
    session: Session,
    observations: List[AirfareObservationCreate],
    rejected: List[Tuple[AirfareObservationCreate, str]],
    run: CollectionRun,
) -> Tuple[int, int, int]:
    """
    Persist validated observations and rejected records to the database.

    Returns:
        (saved_count, rejected_count, duplicate_count)
    """
    saved_count = 0
    rejected_count = 0
    duplicate_count = 0

    source_id = run.source_id

    # --- Store valid observations ---
    for obs in observations:
        airline = _get_or_create_airline(session, obs.airline_name, obs.airline_iata)
        route = _get_or_create_route(session, obs.origin, obs.destination)
        collection_date = obs.collection_date or obs.collection_timestamp.astimezone(KOLKATA_TZ).date()

        # Duplicate check against unique constraint
        if _is_duplicate(
            session,
            source_id=source_id,
            flight_number=obs.flight_number,
            travel_date=obs.travel_date,
            fare_class=obs.fare_class,
            collection_date=collection_date,
        ):
            duplicate_count += 1
            logger.debug(f"Duplicate observation skipped: {obs.airline_name} {obs.flight_number} {obs.travel_date}")
            continue

        db_obs = AirfareObservation(
            id=uuid.uuid4(),
            collection_run_id=run.id,
            collection_timestamp=obs.collection_timestamp,
            collection_date=collection_date,
            source_id=source_id,
            route_id=route.id,
            airline_id=airline.id,
            flight_number=obs.flight_number,
            travel_date=obs.travel_date,
            lead_days=obs.lead_days,
            fare_class=obs.fare_class,
            base_fare=obs.base_fare,
            taxes=obs.taxes,
            udf_psf=obs.udf_psf,
            convenience_fee=obs.convenience_fee,
            other_fees=obs.other_fees,
            total_fare=obs.total_fare,
            currency=obs.currency,
            dep_time=obs.dep_time,
            dep_band=obs.dep_band,
            stops=obs.stops,
            duration_min=obs.duration_min,
            is_sold_out=obs.is_sold_out,
            seats_left=obs.seats_left,
            is_synthetic=obs.is_synthetic,
            target_lead_window=obs.target_lead_window,
            is_outlier=obs.is_outlier,
            is_imputed=obs.is_imputed,
            availability=obs.availability,
            status="valid",
            raw_reference=obs.raw_reference,
        )
        session.add(db_obs)
        saved_count += 1

    # --- Store rejected observations (never silently discard) ---
    for obs, reason in rejected:
        collection_date = obs.collection_date or obs.collection_timestamp.astimezone(KOLKATA_TZ).date()

        # Duplicate check against unique constraint
        if _is_duplicate(
            session,
            source_id,
            obs.flight_number,
            obs.travel_date,
            obs.fare_class or "Economy",
            collection_date,
        ):
            duplicate_count += 1
            logger.debug(
                f"Duplicate rejected observation skipped: {obs.flight_number} {obs.travel_date} "
                f"{obs.fare_class} on {collection_date}"
            )
            continue

        airline = _get_or_create_airline(session, obs.airline_name, obs.airline_iata)
        route = _get_or_create_route(session, obs.origin, obs.destination)

        rej_record = AirfareObservation(
            id=uuid.uuid4(),
            collection_run_id=run.id,
            collection_timestamp=obs.collection_timestamp,
            collection_date=collection_date,
            source_id=source_id,
            route_id=route.id,
            airline_id=airline.id,
            flight_number=obs.flight_number,
            travel_date=obs.travel_date,
            lead_days=obs.lead_days or 0,
            fare_class=obs.fare_class or "Unknown",
            base_fare=obs.base_fare,
            taxes=obs.taxes,
            udf_psf=obs.udf_psf,
            convenience_fee=obs.convenience_fee,
            other_fees=obs.other_fees,
            total_fare=obs.total_fare if (obs.total_fare is not None and obs.total_fare > 0) else Decimal("1.00"),
            currency=obs.currency or "INR",
            dep_time=obs.dep_time,
            dep_band=obs.dep_band,
            stops=obs.stops,
            duration_min=obs.duration_min,
            is_sold_out=obs.is_sold_out,
            seats_left=obs.seats_left,
            is_synthetic=obs.is_synthetic,
            target_lead_window=obs.target_lead_window,
            is_outlier=obs.is_outlier,
            is_imputed=obs.is_imputed,
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
