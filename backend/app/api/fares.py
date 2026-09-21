"""
backend/app/api/fares.py
Fare search and serve-time validation endpoint.

Endpoints:
  - GET /fares/search
  - GET /api/fares/search

Guarantees:
  - Never scrapes live; reads strictly from verified stored database observations.
  - Excludes synthetic data by default; allows synthetic with prominent banner when demo_mode=True.
  - Applies FareGate validation per fare (age, decomposition, plausible bands, cross-source agreement).
  - Uncovered routes return a structured not-covered response and register in route_watchlist.
  - Missing dates fall back to the nearest collected lead-time window with estimated=True.
"""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import logging
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.app.database import get_db
from backend.app.models.airfare import Airline, AirfareObservation, Route, Source
from backend.app.models.watchlist import RouteWatchlist
from serving.validation import FareGate, FareGateConfig, FareGateResult

logger = logging.getLogger(__name__)
KOLKATA_TZ = ZoneInfo("Asia/Kolkata")

router = APIRouter(tags=["Fares"])


# ---------------------------------------------------------------------------
# Authentication Helper
# ---------------------------------------------------------------------------

def verify_api_key(
    request: Request,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    api_key: Optional[str] = Query(None),
) -> str:
    """
    Validate API key from header or query parameter against configured keys.
    """
    provided_key = x_api_key or api_key
    gate_cfg = FareGateConfig.from_yaml()

    # Load configured keys from config/serving.yaml
    valid_keys = {"apix_dev_key_2024", "apix_prod_live_2024", "apix_test_client_key"}
    serving_yaml_path = getattr(gate_cfg, "yaml_path", None)

    # If no key provided, reject with 401 Unauthorized
    if not provided_key or provided_key not in valid_keys:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API Key. Provide a valid 'X-API-Key' header.",
        )

    return provided_key


# ---------------------------------------------------------------------------
# Watchlist Registration Helper
# ---------------------------------------------------------------------------

def register_watchlist_request(
    session: Session,
    origin: str,
    destination: str,
    client_identifier: str,
    rate_limit_hourly: int = 10,
) -> bool:
    """
    Record an uncovered route request in route_watchlist with client rate limiting.
    Returns True if registered/incremented, False if rate limited.
    """
    route_code = f"{origin}-{destination}"
    client_hash = RouteWatchlist.hash_client(client_identifier)
    now = datetime.now(timezone.utc)
    one_hour_ago = now - timedelta(hours=1)

    entry = (
        session.query(RouteWatchlist)
        .filter_by(route_code=route_code, client_hash=client_hash)
        .first()
    )

    if entry:
        # Check rate limit (if requested > rate_limit_hourly times in the last hour)
        if entry.last_requested_at and entry.last_requested_at >= one_hour_ago:
            if entry.request_count >= rate_limit_hourly:
                return False

        entry.request_count += 1
        entry.last_requested_at = now
        session.commit()
        return True
    else:
        new_entry = RouteWatchlist(
            origin=origin,
            destination=destination,
            route_code=route_code,
            client_hash=client_hash,
            request_count=1,
            first_requested_at=now,
            last_requested_at=now,
        )
        session.add(new_entry)
        session.commit()
        return True


# ---------------------------------------------------------------------------
# Search Implementation
# ---------------------------------------------------------------------------

@router.get("/fares/search")
@router.get("/api/fares/search")
def search_fares(
    origin: str = Query(..., min_length=3, max_length=3, description="3-letter origin IATA code (e.g. BOM)"),
    destination: str = Query(..., min_length=3, max_length=3, description="3-letter destination IATA code (e.g. DEL)"),
    date: date = Query(..., description="Travel date (YYYY-MM-DD)"),
    carrier: Optional[str] = Query(None, description="Optional airline IATA code or name (e.g. 6E, AI)"),
    demo_mode: bool = Query(False, description="Enable demo mode to include synthetic test data"),
    x_demo_mode: Optional[str] = Header(None, alias="X-Demo-Mode"),
    request: Request = None,
    api_key: str = Depends(verify_api_key),
    session: Session = Depends(get_db),
):
    """
    Serve-time airfare search endpoint with FareGate validation.
    """
    origin_clean = origin.strip().upper()
    dest_clean = destination.strip().upper()
    route_code = f"{origin_clean}-{dest_clean}"

    is_demo = demo_mode or (x_demo_mode is not None and x_demo_mode.lower() in ("true", "1"))

    # 1. Route Coverage Verification
    route = (
        session.query(Route)
        .filter_by(origin=origin_clean, destination=dest_clean, is_active=True)
        .first()
    )

    if not route:
        # Client identifier for rate limiting
        client_ip = (
            request.client.host if request and request.client else "127.0.0.1"
        )
        client_id = f"{api_key}:{client_ip}"
        watchlist_added = register_watchlist_request(
            session=session,
            origin=origin_clean,
            destination=dest_clean,
            client_identifier=client_id,
        )

        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "status": "not_covered",
                "message": f"Route {route_code} is currently not covered in the APIx observation basket.",
                "route_code": route_code,
                "watchlist_registered": watchlist_added,
                "coverage": {
                    "is_covered": False,
                    "active_sources": [],
                },
            },
        )

    # 2. Query Direct Observations on travel_date
    query = (
        session.query(AirfareObservation)
        .filter(
            AirfareObservation.route_id == route.id,
            AirfareObservation.travel_date == date,
            AirfareObservation.status == "valid",
        )
    )

    if not is_demo:
        query = query.filter(AirfareObservation.is_synthetic == False)

    if carrier:
        carrier_clean = carrier.strip()
        query = query.join(Airline, AirfareObservation.airline_id == Airline.id).filter(
            (Airline.iata_code == carrier_clean.upper()) | (Airline.name.ilike(f"%{carrier_clean}%"))
        )

    observations = query.all()

    # 3. Setup FareGate
    gate_config = FareGateConfig.from_yaml(allow_synthetic=is_demo)
    gate = FareGate(config=gate_config)

    cross_source_map = gate.build_cross_source_map(observations)
    now_utc = datetime.now(timezone.utc)
    today_kolkata = now_utc.astimezone(KOLKATA_TZ).date()

    validated_flights: List[Dict[str, Any]] = []
    is_estimated = False
    explanation = None

    for obs in observations:
        carrier_key = (
            obs.airline.iata_code if obs.airline and obs.airline.iata_code else (obs.airline.name if obs.airline else "UNKNOWN")
        ).strip().upper()
        flight_key = (obs.flight_number or "").strip().upper()
        cs_quotes = cross_source_map.get((carrier_key, flight_key, obs.travel_date), [])

        eval_res = gate.evaluate_fare(
            fare=obs,
            cross_source_quotes=cs_quotes,
            now_utc=now_utc,
            allow_synthetic_override=is_demo,
        )

        if eval_res.status != "hidden":
            validated_flights.append({
                "flight_number": obs.flight_number,
                "airline_name": obs.airline.name if obs.airline else "Unknown Airline",
                "airline_iata": obs.airline.iata_code if obs.airline else None,
                "origin": route.origin,
                "destination": route.destination,
                "travel_date": obs.travel_date.isoformat(),
                "dep_time": obs.dep_time.isoformat() if obs.dep_time else None,
                "dep_band": obs.dep_band,
                "stops": obs.stops,
                "duration_min": obs.duration_min,
                "fare_class": obs.fare_class,
                "pricing": {
                    "base_fare": float(obs.base_fare) if obs.base_fare else None,
                    "taxes": float(obs.taxes) if obs.taxes else 0.0,
                    "udf_psf": float(obs.udf_psf) if obs.udf_psf else 0.0,
                    "convenience_fee": float(obs.convenience_fee) if obs.convenience_fee else 0.0,
                    "other_fees": float(obs.other_fees) if obs.other_fees else 0.0,
                    "total_fare": float(obs.total_fare),
                    "currency": obs.currency,
                },
                "sources": [obs.source.name] if obs.source else ["Unknown"],
                "last_updated": obs.collection_timestamp.isoformat() if obs.collection_timestamp else None,
                "gate_status": eval_res.status,
                "confidence": eval_res.confidence,
                "age_minutes": eval_res.age_minutes,
                "warnings": eval_res.warnings,
                "is_synthetic": obs.is_synthetic,
                "is_imputed": obs.is_imputed,
            })

    # 4. Nearest Window Fallback if No Direct Valid Observations
    if not validated_flights:
        # Search for closest available travel_date on this route
        fallback_query = (
            session.query(AirfareObservation)
            .filter(
                AirfareObservation.route_id == route.id,
                AirfareObservation.status == "valid",
            )
        )
        if not is_demo:
            fallback_query = fallback_query.filter(AirfareObservation.is_synthetic == False)
        if carrier:
            carrier_clean = carrier.strip()
            fallback_query = fallback_query.join(Airline, AirfareObservation.airline_id == Airline.id).filter(
                (Airline.iata_code == carrier_clean.upper()) | (Airline.name.ilike(f"%{carrier_clean}%"))
            )

        fallback_obs = fallback_query.all()

        if fallback_obs:
            # Find observation with minimum day difference from requested travel date
            fallback_obs.sort(key=lambda x: abs((x.travel_date - date).days))
            closest_date = fallback_obs[0].travel_date
            closest_records = [o for o in fallback_obs if o.travel_date == closest_date]

            is_estimated = True
            lead_diff = (closest_date - today_kolkata).days
            explanation = (
                f"No direct observations collected for travel date {date.isoformat()}. "
                f"Showing estimated nearest collected window (travel date: {closest_date.isoformat()}, T+{lead_diff} days)."
            )

            fb_cs_map = gate.build_cross_source_map(closest_records)
            for obs in closest_records:
                carrier_key = (
                    obs.airline.iata_code if obs.airline and obs.airline.iata_code else (obs.airline.name if obs.airline else "UNKNOWN")
                ).strip().upper()
                flight_key = (obs.flight_number or "").strip().upper()
                cs_quotes = fb_cs_map.get((carrier_key, flight_key, obs.travel_date), [])

                eval_res = gate.evaluate_fare(
                    fare=obs,
                    cross_source_quotes=cs_quotes,
                    now_utc=now_utc,
                    allow_synthetic_override=is_demo,
                )

                if eval_res.status != "hidden":
                    validated_flights.append({
                        "flight_number": obs.flight_number,
                        "airline_name": obs.airline.name if obs.airline else "Unknown Airline",
                        "airline_iata": obs.airline.iata_code if obs.airline else None,
                        "origin": route.origin,
                        "destination": route.destination,
                        "travel_date": obs.travel_date.isoformat(),
                        "dep_time": obs.dep_time.isoformat() if obs.dep_time else None,
                        "dep_band": obs.dep_band,
                        "stops": obs.stops,
                        "duration_min": obs.duration_min,
                        "fare_class": obs.fare_class,
                        "pricing": {
                            "base_fare": float(obs.base_fare) if obs.base_fare else None,
                            "taxes": float(obs.taxes) if obs.taxes else 0.0,
                            "udf_psf": float(obs.udf_psf) if obs.udf_psf else 0.0,
                            "convenience_fee": float(obs.convenience_fee) if obs.convenience_fee else 0.0,
                            "other_fees": float(obs.other_fees) if obs.other_fees else 0.0,
                            "total_fare": float(obs.total_fare),
                            "currency": obs.currency,
                        },
                        "sources": [obs.source.name] if obs.source else ["Unknown"],
                        "last_updated": obs.collection_timestamp.isoformat() if obs.collection_timestamp else None,
                        "gate_status": eval_res.status,
                        "confidence": "low" if eval_res.confidence == "high" else eval_res.confidence,
                        "age_minutes": eval_res.age_minutes,
                        "warnings": eval_res.warnings + ["nearest_window_estimate"],
                        "is_synthetic": obs.is_synthetic,
                        "is_imputed": True,
                    })

    # 5. Route Summary Metrics
    if validated_flights:
        fares = [f["pricing"]["total_fare"] for f in validated_flights]
        cheapest_val = min(fares)
        fares_sorted = sorted(fares)
        n_fares = len(fares_sorted)
        typical_val = (
            fares_sorted[n_fares // 2]
            if n_fares % 2 == 1
            else (fares_sorted[n_fares // 2 - 1] + fares_sorted[n_fares // 2]) / 2.0
        )
    else:
        cheapest_val = None
        typical_val = None

    # 6. Lead Time Position
    requested_lead_days = (date - today_kolkata).days
    target_window = None
    for w in (1, 7, 15, 30, 45):
        if abs(w - requested_lead_days) <= 7:
            target_window = w
            break

    # 7. Coverage Object
    active_sources = list({f["sources"][0] for f in validated_flights if f["sources"]})
    freshness_hours = (
        min(f["age_minutes"] for f in validated_flights) / 60.0 if validated_flights else 0.0
    )

    response_payload: Dict[str, Any] = {
        "route": {
            "origin": route.origin,
            "destination": route.destination,
            "route_code": route.route_code,
        },
        "query": {
            "requested_date": date.isoformat(),
            "carrier_filter": carrier,
            "demo_mode": is_demo,
        },
        "lead_time_position": {
            "lead_days": requested_lead_days,
            "target_lead_window": target_window,
            "is_estimated": is_estimated,
            "explanation": explanation,
        },
        "summary": {
            "cheapest_fare": cheapest_val,
            "typical_fare": typical_val,
            "n_flights": len(validated_flights),
        },
        "coverage": {
            "is_covered": True,
            "active_sources": active_sources,
            "data_freshness_hours": round(freshness_hours, 2),
            "collection_mode": "recorded_fixture",
        },
        "flights": validated_flights,
    }

    if is_demo:
        response_payload["banner"] = "SYNTHETIC DEMO DATA - NOT FOR PRODUCTION PRICE INDEX"
        response_payload["is_synthetic"] = True

    return response_payload
