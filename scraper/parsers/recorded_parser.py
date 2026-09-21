"""
scraper/parsers/recorded_parser.py
Parser for recorded JSON flight responses and partner flight search fixtures.

Extracts all required airfare dimensions:
  - airline, flight_number, origin, destination
  - dep_time (and auto-derived dep_band), stops, duration_min
  - base_fare, taxes, udf_psf, convenience_fee, other_fees, total_fare
  - is_sold_out, seats_left, availability
  - is_synthetic flag (False for real captured fixtures, True for synthetic mock)
  - raw_reference linking to raw response file on disk
"""
from datetime import date, datetime, time, timezone
from decimal import Decimal
import json
import logging
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from backend.app.schemas.airfare import AirfareObservationCreate
from scraper.parsers.fare_parser import normalize_availability, normalize_fare_class, parse_fare

logger = logging.getLogger(__name__)

KOLKATA_TZ = ZoneInfo("Asia/Kolkata")


def _parse_time(raw_time: Any) -> Optional[time]:
    """Parse time string like '06:00' or '06:00:00' into a datetime.time object."""
    if not raw_time:
        return None
    if isinstance(raw_time, time):
        return raw_time
    time_str = str(raw_time).strip()
    for fmt in ("%H:%M:%S", "%H:%M", "%I:%M %p", "%I:%M%p"):
        try:
            return datetime.strptime(time_str, fmt).time()
        except ValueError:
            continue
    return None


def parse_flight_item(
    item: Dict[str, Any],
    origin: str,
    destination: str,
    travel_date: date,
    collection_timestamp: Optional[datetime] = None,
    source_name: str = "EaseMyTrip",
    is_synthetic: bool = False,
    raw_reference: Optional[str] = None,
) -> AirfareObservationCreate:
    """
    Parse a single flight result dictionary into a validated AirfareObservationCreate schema.
    """
    ts = collection_timestamp or datetime.now(timezone.utc)
    collection_date_kolkata = ts.astimezone(KOLKATA_TZ).date()

    airline_name = item.get("airline") or item.get("airline_name") or "Unknown Airline"
    airline_iata = item.get("airline_code") or item.get("airline_iata")
    flight_number = item.get("flight_number") or item.get("flight_no")

    flight_origin = (item.get("origin") or origin).strip().upper()
    flight_dest = (item.get("destination") or destination).strip().upper()

    dep_time_val = _parse_time(item.get("departure_time") or item.get("dep_time"))
    stops = int(item.get("stops", 0))
    duration_min = int(item.get("duration_minutes") or item.get("duration_min") or 120)

    fare_class = normalize_fare_class(item.get("fare_class", "Economy")) or "Economy"

    # Fare breakup extraction
    breakup = item.get("fare_breakup") or {}
    base_fare = parse_fare(breakup.get("base_fare") or item.get("base_fare"))
    taxes = parse_fare(breakup.get("taxes") or item.get("taxes")) or Decimal("0.00")
    udf_psf = parse_fare(breakup.get("udf_psf") or item.get("udf_psf")) or Decimal("0.00")
    convenience_fee = parse_fare(breakup.get("convenience_fee") or item.get("convenience_fee")) or Decimal("0.00")
    other_fees = parse_fare(breakup.get("other_fees") or item.get("other_fees")) or Decimal("0.00")
    total_fare = parse_fare(breakup.get("total_fare") or item.get("total_fare"))

    if total_fare is None and base_fare is not None:
        total_fare = base_fare + taxes + udf_psf + convenience_fee + other_fees

    if total_fare is None:
        raise ValueError(f"Could not parse valid total_fare for flight {flight_number}")

    # Sold out / availability
    is_sold_out = bool(item.get("is_sold_out", False))
    seats_left = item.get("seats_left")
    if seats_left is not None:
        seats_left = int(seats_left)
        if seats_left == 0:
            is_sold_out = True

    availability = normalize_availability(item.get("availability", "sold_out" if is_sold_out else "available"))

    # Lead days & target lead window
    lead_days = (travel_date - collection_date_kolkata).days
    target_lead_window = None
    for window in (1, 7, 15, 30, 45):
        if abs(window - lead_days) <= 7:
            target_lead_window = window
            break

    return AirfareObservationCreate(
        collection_timestamp=ts,
        collection_date=collection_date_kolkata,
        source_name=source_name,
        origin=flight_origin,
        destination=flight_dest,
        airline_name=airline_name,
        airline_iata=airline_iata,
        flight_number=flight_number,
        travel_date=travel_date,
        lead_days=lead_days,
        fare_class=fare_class,
        base_fare=base_fare,
        taxes=taxes,
        udf_psf=udf_psf,
        convenience_fee=convenience_fee,
        other_fees=other_fees,
        total_fare=total_fare,
        currency="INR",
        dep_time=dep_time_val,
        stops=stops,
        duration_min=duration_min,
        is_sold_out=is_sold_out,
        seats_left=seats_left,
        availability=availability,
        is_synthetic=is_synthetic,
        target_lead_window=target_lead_window,
        raw_reference=raw_reference,
    )


def parse_recorded_flight_search(
    raw_content_or_json: str | dict,
    origin: str,
    destination: str,
    travel_date: date,
    collection_timestamp: Optional[datetime] = None,
    source_name: str = "EaseMyTrip",
    is_synthetic: bool = False,
    raw_reference: Optional[str] = None,
) -> List[AirfareObservationCreate]:
    """
    Parse a recorded flight search payload (JSON string or dict).
    """
    if isinstance(raw_content_or_json, str):
        data = json.loads(raw_content_or_json)
    else:
        data = raw_content_or_json

    flight_list = data.get("flight_results") or data.get("flights") or data.get("results") or []
    observations: List[AirfareObservationCreate] = []

    for item in flight_list:
        try:
            obs = parse_flight_item(
                item=item,
                origin=origin,
                destination=destination,
                travel_date=travel_date,
                collection_timestamp=collection_timestamp,
                source_name=source_name,
                is_synthetic=is_synthetic,
                raw_reference=raw_reference,
            )
            observations.append(obs)
        except Exception as exc:
            logger.warning(f"Error parsing flight item: {exc}")
            continue

    return observations
