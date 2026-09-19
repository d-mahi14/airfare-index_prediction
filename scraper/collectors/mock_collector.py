"""
scraper/collectors/mock_collector.py
Synthetic/mock airfare collector for pipeline development and testing.

PURPOSE:
  Generates realistic synthetic Indian domestic airfare observations.
  Includes fee breakdown (taxes, udf_psf, convenience_fee, other_fees),
  flight schedules (dep_time, dep_band, duration, stops), and booking metadata.
"""
import json
import logging
import random
from datetime import date, datetime, time, timezone
from decimal import Decimal
from typing import List
from zoneinfo import ZoneInfo

from backend.app.schemas.airfare import AirfareObservationCreate
from scraper.base import BaseCollector

logger = logging.getLogger(__name__)

KOLKATA_TZ = ZoneInfo("Asia/Kolkata")

# ---------------------------------------------------------------------------
# Synthetic fare configuration
# ---------------------------------------------------------------------------

_AIRLINES = [
    {"name": "IndiGo", "iata": "6E"},
    {"name": "Air India", "iata": "AI"},
    {"name": "SpiceJet", "iata": "SG"},
    {"name": "Air India Express", "iata": "IX"},
    {"name": "Akasa Air", "iata": "QP"},
]

_ROUTE_FARE_RANGES = {
    "BOM-DEL": (2800, 8500),
    "BOM-BLR": (2200, 6000),
    "DEL-BLR": (3000, 9000),
    "DEL-HYD": (2500, 7500),
    "BOM-HYD": (1800, 5500),
    "DEL-MAA": (3200, 10000),
    "BOM-MAA": (2000, 6500),
    "DEL-CCU": (3000, 9500),
    "BOM-CCU": (3500, 11000),
    "DEL-AMD": (1500, 4500),
}
_DEFAULT_FARE_RANGE = (2000, 9000)

_ROUTE_DURATIONS = {
    "BOM-DEL": 130,
    "BOM-BLR": 105,
    "DEL-BLR": 165,
    "DEL-HYD": 135,
    "BOM-HYD": 90,
    "DEL-MAA": 170,
    "BOM-MAA": 115,
    "DEL-CCU": 140,
    "BOM-CCU": 165,
    "DEL-AMD": 80,
}
_DEFAULT_DURATION = 120

_LEAD_TIME_MULTIPLIERS = {
    1:  1.45,
    7:  1.20,
    15: 1.05,
    30: 0.95,
    45: 0.88,
}
_DEFAULT_LEAD_MULTIPLIER = 1.0

_TAX_RATE = Decimal("0.05")  # 5% GST on domestic economy base
_MIN_AIRLINES = 2
_MAX_AIRLINES = 4


class MockCollector(BaseCollector):
    """
    Synthetic airfare collector.
    Generates deterministically-seeded realistic observations.
    """

    source_name = "MockCollector"

    def __init__(
        self,
        raw_data_dir: str = "data/raw",
        seed: int | None = None,
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
        Generate synthetic airfare observations for the given route and date.
        """
        origin = origin.upper().strip()
        destination = destination.upper().strip()
        collection_ts = datetime.now(timezone.utc)
        collection_date_kolkata = collection_ts.astimezone(KOLKATA_TZ).date()
        route_code = f"{origin}-{destination}"

        logger.info(
            f"MockCollector: collecting {route_code} for travel_date={travel_date}"
        )

        lead_days = (travel_date - collection_date_kolkata).days
        if lead_days < 0:
            logger.warning(
                f"travel_date {travel_date} is in the past; returning empty list"
            )
            return []

        fare_min, fare_max = _ROUTE_FARE_RANGES.get(route_code, _DEFAULT_FARE_RANGE)
        flight_duration = _ROUTE_DURATIONS.get(route_code, _DEFAULT_DURATION)

        # Match target lead window (1, 7, 15, 30, 45)
        closest_bucket = min(_LEAD_TIME_MULTIPLIERS.keys(), key=lambda k: abs(k - lead_days))
        target_lead_window = closest_bucket if abs(closest_bucket - lead_days) <= 7 else None
        multiplier = _LEAD_TIME_MULTIPLIERS.get(closest_bucket, _DEFAULT_LEAD_MULTIPLIER)

        num_airlines = self._rng.randint(_MIN_AIRLINES, min(_MAX_AIRLINES, len(_AIRLINES)))
        selected_airlines = self._rng.sample(_AIRLINES, num_airlines)

        observations: List[AirfareObservationCreate] = []
        raw_records = []

        for airline in selected_airlines:
            raw_base = self._rng.uniform(fare_min, fare_max) * multiplier
            base_fare = Decimal(str(round(raw_base / 10) * 10))
            taxes = (base_fare * _TAX_RATE).quantize(Decimal("1.00"))
            udf_psf = Decimal(str(self._rng.choice([250, 350, 420])))
            convenience_fee = Decimal(str(self._rng.choice([200, 250, 300])))
            other_fees = Decimal("0.00")
            total_fare = base_fare + taxes + udf_psf + convenience_fee + other_fees

            flight_num = f"{airline['iata']}{self._rng.randint(100, 999)}"
            dep_hour = self._rng.randint(5, 22)
            dep_minute = self._rng.choice([0, 15, 30, 45])
            dep_time_obj = time(dep_hour, dep_minute)

            seats_left = self._rng.choice([None, 3, 5, 8, 12])

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
                "availability": "available",
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
                    is_sold_out=False,
                    is_synthetic=True,
                    target_lead_window=target_lead_window,
                    availability="available",
                )
                observations.append(obs)
            except Exception as exc:
                logger.error(f"Schema validation failed for {airline['name']}: {exc}")
                continue

        raw_content = json.dumps(raw_records, indent=2, ensure_ascii=False)
        raw_path = self._save_raw(raw_content, suffix="json")

        for obs in observations:
            obs.raw_reference = str(raw_path)

        logger.info(
            f"MockCollector: collected {len(observations)} observations "
            f"for {route_code} travel_date={travel_date}"
        )
        return observations
