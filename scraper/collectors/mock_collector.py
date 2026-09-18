"""
scraper/collectors/mock_collector.py
Synthetic/mock airfare collector for pipeline development and testing.

PURPOSE:
  Generates realistic synthetic Indian domestic airfare observations.
  Used when live scraping is not yet configured or is under ethical review.

  The synthetic data is:
    - Statistically plausible (based on real Indian domestic fare ranges)
    - Deterministically seeded so tests are reproducible
    - Structurally identical to what a real collector would produce
    - Clearly labelled as synthetic (source_name = "MockCollector")

DESIGN NOTE:
  Replacing this with a real collector only requires:
    1. Creating a new class that extends BaseCollector
    2. Implementing collect()
    3. Passing it to the pipeline instead of MockCollector

  Nothing in the pipeline, validator, or storage layer changes.

SYNTHETIC FARE MODEL:
  - Base fares follow a realistic BOM-DEL distribution (~₹2500–₹8000)
  - Lead-time pricing: fares increase as travel approaches
  - Airlines: IndiGo, Air India, SpiceJet, Vistara (now Air India Express)
  - Taxes are ~18% of base fare (GST on economy domestic)
  - Small random variation simulates real price noise
"""
import json
import logging
import random
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import List

from backend.app.schemas.airfare import AirfareObservationCreate
from scraper.base import BaseCollector

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Synthetic fare configuration
# ---------------------------------------------------------------------------

# Indian domestic airlines with IATA codes
_AIRLINES = [
    {"name": "IndiGo", "iata": "6E"},
    {"name": "Air India", "iata": "AI"},
    {"name": "SpiceJet", "iata": "SG"},
    {"name": "Air India Express", "iata": "IX"},
    {"name": "Akasa Air", "iata": "QP"},
]

# Route-specific base fare ranges (Economy, one-way, INR)
# Based on typical observed ranges for these routes
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

# Lead-time multiplier: closer to departure = more expensive
_LEAD_TIME_MULTIPLIERS = {
    1:  1.45,
    7:  1.20,
    15: 1.05,
    30: 0.95,
    45: 0.88,
}
_DEFAULT_LEAD_MULTIPLIER = 1.0

# GST on economy class domestic air tickets (India): ~18% effective rate
# (5% on base + fuel surcharge portion; simplified to ~18% of base)
_TAX_RATE = Decimal("0.18")

# Number of airlines to include per collection (simulates not all airlines
# always flying a route at any given time)
_MIN_AIRLINES = 2
_MAX_AIRLINES = 4


class MockCollector(BaseCollector):
    """
    Synthetic airfare collector.

    Generates deterministically-seeded realistic observations.
    seed=None for random behavior; set seed for reproducible tests.
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

        Returns one observation per airline that "operates" this route.
        """
        origin = origin.upper().strip()
        destination = destination.upper().strip()
        collection_ts = datetime.now(timezone.utc)
        route_code = f"{origin}-{destination}"

        logger.info(
            f"MockCollector: collecting {route_code} for travel_date={travel_date}"
        )

        # Compute lead days
        lead_days = (travel_date - collection_ts.date()).days
        if lead_days < 0:
            logger.warning(
                f"travel_date {travel_date} is in the past; returning empty list"
            )
            return []

        # Get fare range for this route (or default)
        fare_min, fare_max = _ROUTE_FARE_RANGES.get(route_code, _DEFAULT_FARE_RANGE)

        # Lead-time multiplier
        # Find closest lead_time bucket
        multiplier = _DEFAULT_LEAD_MULTIPLIER
        closest_bucket = min(_LEAD_TIME_MULTIPLIERS.keys(), key=lambda k: abs(k - lead_days))
        if abs(closest_bucket - lead_days) <= 7:
            multiplier = _LEAD_TIME_MULTIPLIERS[closest_bucket]

        # Select airlines for this collection
        num_airlines = self._rng.randint(_MIN_AIRLINES, min(_MAX_AIRLINES, len(_AIRLINES)))
        selected_airlines = self._rng.sample(_AIRLINES, num_airlines)

        observations: List[AirfareObservationCreate] = []
        raw_records = []

        for airline in selected_airlines:
            # Generate base fare with lead-time adjustment and random noise
            raw_base = self._rng.uniform(fare_min, fare_max) * multiplier
            # Round to nearest 10 (airlines typically price in round numbers)
            base_fare = Decimal(str(round(raw_base / 10) * 10))
            taxes = (base_fare * _TAX_RATE).quantize(Decimal("1.00"))
            fees = Decimal("0.00")
            total_fare = base_fare + taxes + fees

            # Synthetic flight number
            flight_num = f"{airline['iata']}{self._rng.randint(100, 999)}"

            # Build raw record for file storage
            raw_record = {
                "source": self.source_name,
                "origin": origin,
                "destination": destination,
                "airline": airline["name"],
                "airline_iata": airline["iata"],
                "flight_number": flight_num,
                "travel_date": travel_date.isoformat(),
                "collection_timestamp": collection_ts.isoformat(),
                "lead_days": lead_days,
                "fare_class": "Economy",
                "base_fare": float(base_fare),
                "taxes": float(taxes),
                "fees": float(fees),
                "total_fare": float(total_fare),
                "currency": "INR",
                "availability": "available",
                "synthetic": True,
            }
            raw_records.append(raw_record)

            try:
                obs = AirfareObservationCreate(
                    collection_timestamp=collection_ts,
                    source_name=self.source_name,
                    origin=origin,
                    destination=destination,
                    airline_name=airline["name"],
                    airline_iata=airline["iata"],
                    flight_number=flight_num,
                    travel_date=travel_date,
                    # lead_days will be auto-computed and validated by schema
                    fare_class="Economy",
                    base_fare=base_fare,
                    taxes=taxes,
                    fees=fees,
                    total_fare=total_fare,
                    currency="INR",
                    availability="available",
                )
                observations.append(obs)
            except Exception as exc:
                logger.error(f"Schema validation failed for {airline['name']}: {exc}")
                continue

        # Save raw JSON to disk for reproducibility
        raw_content = json.dumps(raw_records, indent=2, ensure_ascii=False)
        raw_path = self._save_raw(raw_content, suffix="json")

        # Attach raw_reference to each observation
        for obs in observations:
            obs.raw_reference = str(raw_path)

        logger.info(
            f"MockCollector: collected {len(observations)} observations "
            f"for {route_code} travel_date={travel_date}"
        )
        return observations
