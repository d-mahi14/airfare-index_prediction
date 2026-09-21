"""
scraper/parsers/indigo_parser.py
Parser for recorded IndiGo direct flight search JSON payloads.

Extracts all domain dimensions:
  - airline_name ("IndiGo"), airline_iata ("6E"), flight_number (e.g. "6E-2041")
  - origin, destination, travel_date
  - dep_time, stops, duration_min
  - base_fare, taxes, udf_psf, convenience_fee, other_fees, total_fare
  - is_sold_out, seats_left, availability
  - is_synthetic flag (False for real captures) and raw_reference disk link
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
    """Parse time string like '05:45' into a datetime.time object."""
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


def parse_indigo_journey(
    journey: Dict[str, Any],
    origin: str,
    destination: str,
    travel_date: date,
    collection_timestamp: Optional[datetime] = None,
    is_synthetic: bool = False,
    raw_reference: Optional[str] = None,
) -> AirfareObservationCreate:
    """
    Parse a single IndiGo journey dictionary into an AirfareObservationCreate schema.
    """
    ts = collection_timestamp or datetime.now(timezone.utc)
    collection_date_kolkata = ts.astimezone(KOLKATA_TZ).date()

    flight_origin = (journey.get("origin") or origin).strip().upper()
    flight_dest = (journey.get("destination") or destination).strip().upper()

    flight_number = journey.get("flight_number") or journey.get("flight_no")
    airline_name = journey.get("carrier") or "IndiGo"
    airline_iata = journey.get("carrier_code") or "6E"

    dep_time_val = _parse_time(journey.get("departure_time"))
    stops = int(journey.get("stops", 0))
    duration_min = int(journey.get("duration_minutes") or 120)
    fare_class = normalize_fare_class(journey.get("cabin_class", "Economy")) or "Economy"

    # Fare breakdown
    fare_details = journey.get("fare_details") or {}
    base_fare = parse_fare(fare_details.get("base_fare"))
    gst_tax = parse_fare(fare_details.get("gst") or fare_details.get("taxes")) or Decimal("0.00")
    
    psf = parse_fare(fare_details.get("passenger_service_fee")) or Decimal("0.00")
    udf = parse_fare(fare_details.get("user_development_fee")) or Decimal("0.00")
    udf_psf = psf + udf

    convenience_fee = parse_fare(fare_details.get("convenience_fee")) or Decimal("0.00")
    other_fees = parse_fare(fare_details.get("other_charges")) or Decimal("0.00")
    total_fare = parse_fare(fare_details.get("total_fare"))

    if total_fare is None and base_fare is not None:
        total_fare = base_fare + gst_tax + udf_psf + convenience_fee + other_fees

    if total_fare is None:
        raise ValueError(f"Could not parse valid total_fare for flight {flight_number}")

    # Availability & sold out detection
    avail_dict = journey.get("availability") or {}
    is_sold_out = bool(avail_dict.get("is_sold_out", False))
    seats_left = avail_dict.get("seats_remaining")
    if seats_left is not None:
        seats_left = int(seats_left)
        if seats_left == 0:
            is_sold_out = True

    raw_avail = avail_dict.get("status", "sold_out" if is_sold_out else "available")
    availability = normalize_availability(raw_avail)

    lead_days = (travel_date - collection_date_kolkata).days
    target_lead_window = None
    for window in (1, 7, 15, 30, 45):
        if abs(window - lead_days) <= 7:
            target_lead_window = window
            break

    return AirfareObservationCreate(
        collection_timestamp=ts,
        collection_date=collection_date_kolkata,
        source_name="IndiGo",
        origin=flight_origin,
        destination=flight_dest,
        airline_name=airline_name,
        airline_iata=airline_iata,
        flight_number=flight_number,
        travel_date=travel_date,
        lead_days=lead_days,
        fare_class=fare_class,
        base_fare=base_fare,
        taxes=gst_tax,
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


def parse_indigo_flight_search(
    raw_content_or_json: str | dict,
    origin: str,
    destination: str,
    travel_date: date,
    collection_timestamp: Optional[datetime] = None,
    is_synthetic: bool = False,
    raw_reference: Optional[str] = None,
) -> List[AirfareObservationCreate]:
    """
    Parse full IndiGo flight search response payload.
    """
    if isinstance(raw_content_or_json, str):
        data = json.loads(raw_content_or_json)
    else:
        data = raw_content_or_json

    journeys = data.get("journeys") or data.get("results") or data.get("flights") or []
    observations: List[AirfareObservationCreate] = []

    for j in journeys:
        try:
            obs = parse_indigo_journey(
                journey=j,
                origin=origin,
                destination=destination,
                travel_date=travel_date,
                collection_timestamp=collection_timestamp,
                is_synthetic=is_synthetic,
                raw_reference=raw_reference,
            )
            observations.append(obs)
        except Exception as exc:
            logger.warning(f"Error parsing IndiGo journey: {exc}")
            continue

    return observations
