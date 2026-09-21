"""
scraper/parsers/makemytrip_parser.py
Parser for recorded MakeMyTrip flight search JSON payloads.

Extracts:
  - Multi-carrier flight options (IndiGo, Air India, Akasa Air, SpiceJet)
  - Full fare breakdown (baseFare, taxes, udfPsf, convenienceFee, total)
  - is_sold_out, seats_left, availability
  - is_synthetic flag (False for real captures) and raw_reference link
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
    """Parse time string like '07:00' into a datetime.time object."""
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


def parse_mmt_flight_item(
    item: Dict[str, Any],
    origin: str,
    destination: str,
    travel_date: date,
    collection_timestamp: Optional[datetime] = None,
    is_synthetic: bool = False,
    raw_reference: Optional[str] = None,
) -> AirfareObservationCreate:
    """
    Parse a single MakeMyTrip flight item dictionary.
    """
    ts = collection_timestamp or datetime.now(timezone.utc)
    collection_date_kolkata = ts.astimezone(KOLKATA_TZ).date()

    flight_origin = (item.get("origin") or origin).strip().upper()
    flight_dest = (item.get("destination") or destination).strip().upper()

    flight_number = item.get("flightNumber") or item.get("flight_number")
    airline_name = item.get("airline") or item.get("airline_name") or "Unknown Airline"
    airline_iata = item.get("airlineCode") or item.get("airline_iata")

    dep_time_val = _parse_time(item.get("departureTime") or item.get("dep_time"))
    stops = int(item.get("stops", 0))
    duration_min = int(item.get("duration") or item.get("duration_min") or 120)
    fare_class = normalize_fare_class(item.get("cabinClass", "Economy")) or "Economy"

    pricing = item.get("pricing") or item.get("fare_breakup") or {}
    base_fare = parse_fare(pricing.get("baseFare") or pricing.get("base_fare"))
    taxes = parse_fare(pricing.get("taxes")) or Decimal("0.00")
    udf_psf = parse_fare(pricing.get("udfPsf") or pricing.get("udf_psf")) or Decimal("0.00")
    convenience_fee = parse_fare(pricing.get("convenienceFee") or pricing.get("convenience_fee")) or Decimal("0.00")
    other_fees = parse_fare(pricing.get("otherFees") or pricing.get("other_fees")) or Decimal("0.00")
    total_fare = parse_fare(pricing.get("total") or pricing.get("total_fare"))

    if total_fare is None and base_fare is not None:
        total_fare = base_fare + taxes + udf_psf + convenience_fee + other_fees

    if total_fare is None:
        raise ValueError(f"Could not parse valid total_fare for flight {flight_number}")

    is_sold_out = bool(item.get("isSoldOut") or item.get("is_sold_out", False))
    seats_left_val = item.get("seatsLeft") if item.get("seatsLeft") is not None else item.get("seats_left")
    seats_left = int(seats_left_val) if seats_left_val is not None else None
    if seats_left is not None and seats_left == 0:
        is_sold_out = True

    availability = normalize_availability("sold_out" if is_sold_out else "available")

    lead_days = (travel_date - collection_date_kolkata).days
    target_lead_window = None
    for window in (1, 7, 15, 30, 45):
        if abs(window - lead_days) <= 7:
            target_lead_window = window
            break

    return AirfareObservationCreate(
        collection_timestamp=ts,
        collection_date=collection_date_kolkata,
        source_name="MakeMyTrip",
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


def parse_makemytrip_flight_search(
    raw_content_or_json: str | dict,
    origin: str,
    destination: str,
    travel_date: date,
    collection_timestamp: Optional[datetime] = None,
    is_synthetic: bool = False,
    raw_reference: Optional[str] = None,
) -> List[AirfareObservationCreate]:
    """
    Parse full MakeMyTrip search response payload.
    """
    if isinstance(raw_content_or_json, str):
        data = json.loads(raw_content_or_json)
    else:
        data = raw_content_or_json

    flight_list = data.get("flightList") or data.get("flights") or data.get("results") or []
    observations: List[AirfareObservationCreate] = []

    for item in flight_list:
        try:
            obs = parse_mmt_flight_item(
                item=item,
                origin=origin,
                destination=destination,
                travel_date=travel_date,
                collection_timestamp=collection_timestamp,
                is_synthetic=is_synthetic,
                raw_reference=raw_reference,
            )
            observations.append(obs)
        except Exception as exc:
            logger.warning(f"Error parsing MakeMyTrip item: {exc}")
            continue

    return observations
