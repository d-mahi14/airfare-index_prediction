"""
scraper/collectors/mock_collector.py
Synthetic airfare collector for APIx pipeline development and testing (Phases 7 & 8).

Features:
  - Generates realistic, deterministically-seeded Indian domestic airfare quotes.
  - Multi-dimensional pricing model incorporating:
      * Advance purchase lead window (T+1, T+7, T+15, T+30, T+45)
      * Day-of-week demand curve (Friday/Sunday premium vs Tuesday/Wednesday discount)
      * Carrier tier differentials (Full Service vs LCC)
      * Route distance and corridor characteristics
  - Sold-out flight state generation (varying by lead window).
  - Complete fee breakdown (base_fare, taxes, udf_psf, convenience_fee, other_fees).
  - All observations carry is_synthetic=True.
"""
import json
import logging
import random
from datetime import date, datetime, time, timezone
from decimal import Decimal
from typing import List, Optional
from zoneinfo import ZoneInfo

from backend.app.schemas.airfare import AirfareObservationCreate
from scraper.base import BaseCollector

logger = logging.getLogger(__name__)

KOLKATA_TZ = ZoneInfo("Asia/Kolkata")

# ---------------------------------------------------------------------------
# Synthetic Fleet & Airline Profiles
# ---------------------------------------------------------------------------

_AIRLINES = [
    {"name": "IndiGo", "iata": "6E", "type": "LCC", "price_mult": 1.00},
    {"name": "Air India", "iata": "AI", "type": "FSC", "price_mult": 1.15},
    {"name": "SpiceJet", "iata": "SG", "type": "LCC", "price_mult": 0.95},
    {"name": "Air India Express", "iata": "IX", "type": "LCC", "price_mult": 0.92},
    {"name": "Akasa Air", "iata": "QP", "type": "LCC", "price_mult": 0.93},
]

# ---------------------------------------------------------------------------
# Route Benchmarks (20 Top DGCA City-Pairs)
# ---------------------------------------------------------------------------

_ROUTE_FARE_RANGES = {
    # Mumbai <-> Delhi
    "BOM-DEL": (2800, 8500),
    "DEL-BOM": (2800, 8500),
    # Delhi <-> Bengaluru
    "DEL-BLR": (3000, 9200),
    "BLR-DEL": (3000, 9200),
    # Mumbai <-> Bengaluru
    "BOM-BLR": (2200, 6200),
    "BLR-BOM": (2200, 6200),
    # Delhi <-> Hyderabad
    "DEL-HYD": (2500, 7500),
    "HYD-DEL": (2500, 7500),
    # Mumbai <-> Hyderabad
    "BOM-HYD": (1800, 5500),
    "HYD-BOM": (1800, 5500),
    # Delhi <-> Kolkata
    "DEL-CCU": (3000, 9500),
    "CCU-DEL": (3000, 9500),
    # Mumbai <-> Kolkata
    "BOM-CCU": (3500, 11000),
    "CCU-BOM": (3500, 11000),
    # Delhi <-> Chennai
    "DEL-MAA": (3200, 10000),
    "MAA-DEL": (3200, 10000),
    # Mumbai <-> Chennai
    "BOM-MAA": (2000, 6500),
    "MAA-BOM": (2000, 6500),
    # Bengaluru <-> Hyderabad
    "BLR-HYD": (1600, 4800),
    "HYD-BLR": (1600, 4800),
}
_DEFAULT_FARE_RANGE = (2000, 8500)

_ROUTE_DURATIONS = {
    "BOM-DEL": 130, "DEL-BOM": 130,
    "DEL-BLR": 165, "BLR-DEL": 165,
    "BOM-BLR": 105, "BLR-BOM": 105,
    "DEL-HYD": 135, "HYD-DEL": 135,
    "BOM-HYD": 90,  "HYD-BOM": 90,
    "DEL-CCU": 140, "CCU-DEL": 140,
    "BOM-CCU": 165, "CCU-BOM": 165,
    "DEL-MAA": 170, "MAA-DEL": 170,
    "BOM-MAA": 115, "MAA-BOM": 115,
    "BLR-HYD": 75,  "HYD-BLR": 75,
}
_DEFAULT_DURATION = 120

# ---------------------------------------------------------------------------
# Elasticity Multipliers
# ---------------------------------------------------------------------------

# Advance purchase lead-time curve
_LEAD_TIME_MULTIPLIERS = {
    1:  1.45,  # T+1: highest urgency
    7:  1.22,  # T+7: short lead
    15: 1.05,  # T+15: medium lead
    30: 0.94,  # T+30: standard advance
    45: 0.85,  # T+45: early-bird discount
}
_DEFAULT_LEAD_MULTIPLIER = 1.0

# Day of week multiplier (0=Monday, 6=Sunday)
_WEEKDAY_MULTIPLIERS = {
    0: 1.05,  # Monday: business morning travel
    1: 0.92,  # Tuesday: lowest midweek demand
    2: 0.90,  # Wednesday: lowest midweek demand
    3: 0.97,  # Thursday: moderate demand
    4: 1.15,  # Friday: weekend getaway surge
    5: 1.08,  # Saturday: leisure departure
    6: 1.18,  # Sunday: weekend return surge
}

# Sold-out probability by lead window
_SOLD_OUT_RATES = {
    1:  0.12,  # 12% probability of sold out on T+1
    7:  0.06,  # 6% probability
    15: 0.03,  # 3% probability
    30: 0.01,  # 1% probability
    45: 0.005, # 0.5% probability
}

_TAX_RATE = Decimal("0.05")  # 5% GST on economy base fare


class MockCollector(BaseCollector):
    """
    Enhanced synthetic airfare collector for testing and simulation.
    Generates realistic, seeded observations across all lead windows and routes.
    """

    source_name = "MockCollector"

    def __init__(
        self,
        raw_data_dir: str = "data/raw",
        seed: Optional[int] = None,
    ):
        super().__init__(raw_data_dir=raw_data_dir)
        self._seed = seed
        self._rng = random.Random(seed)

    def collect(
        self,
        origin: str,
        destination: str,
        travel_date: date,
    ) -> List[AirfareObservationCreate]:
        """
        Generate synthetic observations for route and travel_date.
        """
        origin = origin.upper().strip()
        destination = destination.upper().strip()
        collection_ts = datetime.now(timezone.utc)
        collection_date_kolkata = collection_ts.astimezone(KOLKATA_TZ).date()
        route_code = f"{origin}-{destination}"

        lead_days = (travel_date - collection_date_kolkata).days
        if lead_days < 0:
            logger.warning(f"travel_date {travel_date} is in the past; returning empty list")
            return []

        fare_min, fare_max = _ROUTE_FARE_RANGES.get(route_code, _DEFAULT_FARE_RANGE)
        flight_duration = _ROUTE_DURATIONS.get(route_code, _DEFAULT_DURATION)

        # Match closest target lead window (1, 7, 15, 30, 45)
        closest_window = min(_LEAD_TIME_MULTIPLIERS.keys(), key=lambda k: abs(k - lead_days))
        target_lead_window = closest_window if abs(closest_window - lead_days) <= 7 else None

        lead_multiplier = _LEAD_TIME_MULTIPLIERS.get(closest_window, _DEFAULT_LEAD_MULTIPLIER)
        weekday_multiplier = _WEEKDAY_MULTIPLIERS.get(travel_date.weekday(), 1.0)
        sold_out_prob = _SOLD_OUT_RATES.get(closest_window, 0.02)

        # Select 2 to 4 airlines to quote this route
        num_airlines = self._rng.randint(2, min(4, len(_AIRLINES)))
        selected_airlines = self._rng.sample(_AIRLINES, num_airlines)

        observations: List[AirfareObservationCreate] = []
        raw_records = []

        for airline in selected_airlines:
            carrier_mult = airline.get("price_mult", 1.0)
            combined_multiplier = lead_multiplier * weekday_multiplier * carrier_mult

            raw_base = self._rng.uniform(fare_min, fare_max) * combined_multiplier
            base_fare = Decimal(str(round(raw_base / 10) * 10))
            taxes = (base_fare * _TAX_RATE).quantize(Decimal("1.00"))
            udf_psf = Decimal(str(self._rng.choice([250, 320, 380, 440])))
            convenience_fee = Decimal(str(self._rng.choice([200, 250, 300, 350])))
            other_fees = Decimal("0.00")
            total_fare = base_fare + taxes + udf_psf + convenience_fee + other_fees

            flight_num = f"{airline['iata']}-{self._rng.randint(100, 999)}"
            dep_hour = self._rng.randint(5, 22)
            dep_minute = self._rng.choice([0, 15, 30, 45])
            dep_time_obj = time(dep_hour, dep_minute)

            # Determine sold-out state
            is_sold_out = self._rng.random() < sold_out_prob
            if is_sold_out:
                seats_left = 0
                availability = "sold_out"
            else:
                seats_left = self._rng.choice([None, 2, 4, 7, 9, 14])
                availability = "available"

            raw_record = {
                "source": self.source_name,
                "origin": origin,
                "destination": destination,
                "airline": airline["name"],
                "airline_iata": airline["iata"],
                "flight_number": flight_num,
                "travel_date": travel_date.isoformat(),
                "collection_timestamp": collection_ts.isoformat(),
                "collection_date": collection_date_kolkata.isoformat(),
                "lead_days": lead_days,
                "fare_class": "Economy",
                "base_fare": float(base_fare),
                "taxes": float(taxes),
                "udf_psf": float(udf_psf),
                "convenience_fee": float(convenience_fee),
                "other_fees": float(other_fees),
                "total_fare": float(total_fare),
                "currency": "INR",
                "dep_time": dep_time_obj.strftime("%H:%M:%S"),
                "duration_min": flight_duration,
                "stops": 0,
                "seats_left": seats_left,
                "is_sold_out": is_sold_out,
                "availability": availability,
                "target_lead_window": target_lead_window,
                "is_synthetic": True,
            }
            raw_records.append(raw_record)

            try:
                obs = AirfareObservationCreate(
                    collection_timestamp=collection_ts,
                    collection_date=collection_date_kolkata,
                    source_name=self.source_name,
                    origin=origin,
                    destination=destination,
                    airline_name=airline["name"],
                    airline_iata=airline["iata"],
                    flight_number=flight_num,
                    travel_date=travel_date,
                    lead_days=lead_days,
                    fare_class="Economy",
                    base_fare=base_fare,
                    taxes=taxes,
                    udf_psf=udf_psf,
                    convenience_fee=convenience_fee,
                    other_fees=other_fees,
                    total_fare=total_fare,
                    currency="INR",
                    dep_time=dep_time_obj,
                    duration_min=flight_duration,
                    stops=0,
                    seats_left=seats_left,
                    is_sold_out=is_sold_out,
                    is_synthetic=True,
                    target_lead_window=target_lead_window,
                    availability=availability,
                )
                observations.append(obs)
            except Exception as exc:
                logger.error(f"Schema validation error for {airline['name']}: {exc}")
                continue

        raw_content = json.dumps(raw_records, indent=2, ensure_ascii=False)
        raw_path = self._save_raw(raw_content, suffix="json")

        for obs in observations:
            obs.raw_reference = str(raw_path)

        return observations
