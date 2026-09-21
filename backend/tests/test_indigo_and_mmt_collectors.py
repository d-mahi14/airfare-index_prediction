"""
backend/tests/test_indigo_and_mmt_collectors.py
Comprehensive parser and collector tests for IndiGo and MakeMyTrip sources.

Validates:
  1. IndiGo JSON parsing:
     - 6E flight numbers, departure times, stops, durations.
     - Fare breakup extraction: base_fare, taxes (GST), udf_psf (PSF + UDF), convenience_fee, total_fare.
     - Mathematical reconciliation: total_fare == base_fare + taxes + udf_psf + convenience_fee + other_fees.
     - Sold-out detection: flag and seats_remaining == 0.
     - is_synthetic=False flag on real/recorded captures.
  2. MakeMyTrip JSON parsing:
     - Multi-carrier quotes (Air India, Akasa Air, SpiceJet).
     - Complete fare component decomposition.
     - Sold-out detection.
  3. Collector execution & Raw reference handling:
     - Saving raw payload into data/raw/{source}/{date}/{run_id}/.
     - Linking raw_reference path on observations.
     - Database persistence via storage pipeline with idempotency.
     - Block detection handling.
"""
from datetime import date, datetime, time, timezone
from decimal import Decimal
import json
from pathlib import Path
import tempfile
import uuid

import pytest

from backend.app.models.airfare import AirfareObservation
from backend.app.models.collection import CollectionRun
from backend.app.schemas.airfare import AirfareObservationCreate
from compliance.registry import SourceRegistry
from scraper.base import BlockedResult
from scraper.collectors.indigo_collector import DEFAULT_INDIGO_FIXTURE_PATH, IndiGoCollector
from scraper.collectors.makemytrip_collector import DEFAULT_MMT_FIXTURE_PATH, MakeMyTripCollector
from scraper.parsers.indigo_parser import parse_indigo_flight_search, parse_indigo_journey
from scraper.parsers.makemytrip_parser import parse_makemytrip_flight_search, parse_mmt_flight_item
from scraper.pipelines.storage import (
    _get_or_create_source,
    create_collection_run,
    finish_collection_run,
    store_observations,
)


# ---------------------------------------------------------------------------
# IndiGo Parser Tests
# ---------------------------------------------------------------------------

class TestIndiGoParser:
    """Unit tests for IndiGo JSON response parsing."""

    def test_indigo_fixture_exists(self):
        assert DEFAULT_INDIGO_FIXTURE_PATH.exists(), f"Missing fixture at {DEFAULT_INDIGO_FIXTURE_PATH}"

    def test_parse_indigo_full_fixture(self):
        content = DEFAULT_INDIGO_FIXTURE_PATH.read_text(encoding="utf-8")
        travel_dt = date(2026, 10, 15)
        obs_list = parse_indigo_flight_search(
            raw_content_or_json=content,
            origin="DEL",
            destination="BLR",
            travel_date=travel_dt,
            is_synthetic=False,
            raw_reference="data/raw/indigo/2026-09-21/test_run/indigo_DEL_BLR.json",
        )

        assert len(obs_list) == 4

        for obs in obs_list:
            assert isinstance(obs, AirfareObservationCreate)
            assert obs.source_name == "IndiGo"
            assert obs.origin == "DEL"
            assert obs.destination == "BLR"
            assert obs.airline_iata == "6E"
            assert obs.airline_name == "IndiGo"
            assert obs.is_synthetic is False
            assert obs.currency == "INR"
            assert obs.travel_date == travel_dt
            assert obs.raw_reference == "data/raw/indigo/2026-09-21/test_run/indigo_DEL_BLR.json"

            # Fare breakup mathematical integrity
            expected_sum = (
                obs.base_fare
                + (obs.taxes or Decimal("0.00"))
                + (obs.udf_psf or Decimal("0.00"))
                + (obs.convenience_fee or Decimal("0.00"))
                + (obs.other_fees or Decimal("0.00"))
            )
            assert abs(obs.total_fare - expected_sum) <= Decimal("0.05"), (
                f"Fare sum mismatch for {obs.flight_number}: {obs.total_fare} != {expected_sum}"
            )

    def test_indigo_flight_specifics_and_breakup(self):
        content = DEFAULT_INDIGO_FIXTURE_PATH.read_text(encoding="utf-8")
        obs_list = parse_indigo_flight_search(
            raw_content_or_json=content,
            origin="DEL",
            destination="BLR",
            travel_date=date(2026, 10, 15),
            is_synthetic=False,
        )

        f1 = next(o for o in obs_list if o.flight_number == "6E-2041")
        assert f1.dep_time == time(5, 45)
        assert f1.stops == 0
        assert f1.duration_min == 170
        assert f1.base_fare == Decimal("3800.00")
        assert f1.taxes == Decimal("190.00")
        assert f1.udf_psf == Decimal("440.00")  # PSF (250) + UDF (190)
        assert f1.convenience_fee == Decimal("300.00")
        assert f1.total_fare == Decimal("4730.00")
        assert f1.is_sold_out is False
        assert f1.seats_left == 12
        assert f1.availability == "available"

    def test_indigo_sold_out_detection(self):
        content = DEFAULT_INDIGO_FIXTURE_PATH.read_text(encoding="utf-8")
        obs_list = parse_indigo_flight_search(
            raw_content_or_json=content,
            origin="DEL",
            destination="BLR",
            travel_date=date(2026, 10, 15),
            is_synthetic=False,
        )

        f_sold = next(o for o in obs_list if o.flight_number == "6E-2849")
        assert f_sold.is_sold_out is True
        assert f_sold.seats_left == 0
        assert f_sold.availability == "sold_out"

    def test_indigo_journey_fallback_total_calculation(self):
        # Journey where total_fare is not provided directly but base + components are present
        journey = {
            "flight_number": "6E-9999",
            "carrier": "IndiGo",
            "carrier_code": "6E",
            "origin": "BLR",
            "destination": "HYD",
            "departure_time": "14:30",
            "stops": 0,
            "duration_minutes": 65,
            "fare_details": {
                "base_fare": 2500,
                "gst": 250,
                "passenger_service_fee": 100,
                "user_development_fee": 200,
                "convenience_fee": 300,
            },
            "availability": {"seats_remaining": 4, "is_sold_out": False},
        }
        obs = parse_indigo_journey(
            journey=journey,
            origin="BLR",
            destination="HYD",
            travel_date=date(2026, 10, 20),
            is_synthetic=False,
        )
        assert obs.total_fare == Decimal("3350.00")
        assert obs.udf_psf == Decimal("300.00")
        assert obs.is_sold_out is False


# ---------------------------------------------------------------------------
# MakeMyTrip Parser Tests
# ---------------------------------------------------------------------------

class TestMakeMyTripParser:
    """Unit tests for MakeMyTrip JSON response parsing."""

    def test_mmt_fixture_exists(self):
        assert DEFAULT_MMT_FIXTURE_PATH.exists(), f"Missing fixture at {DEFAULT_MMT_FIXTURE_PATH}"

    def test_parse_mmt_full_fixture(self):
        content = DEFAULT_MMT_FIXTURE_PATH.read_text(encoding="utf-8")
        travel_dt = date(2026, 10, 15)
        obs_list = parse_makemytrip_flight_search(
            raw_content_or_json=content,
            origin="BOM",
            destination="BLR",
            travel_date=travel_dt,
            is_synthetic=False,
            raw_reference="data/raw/makemytrip/2026-09-21/test_run/mmt_BOM_BLR.json",
        )

        assert len(obs_list) == 3

        for obs in obs_list:
            assert isinstance(obs, AirfareObservationCreate)
            assert obs.source_name == "MakeMyTrip"
            assert obs.origin == "BOM"
            assert obs.destination == "BLR"
            assert obs.is_synthetic is False
            assert obs.currency == "INR"
            assert obs.travel_date == travel_dt
            assert obs.raw_reference == "data/raw/makemytrip/2026-09-21/test_run/mmt_BOM_BLR.json"

            # Check math
            expected_sum = (
                obs.base_fare
                + (obs.taxes or Decimal("0.00"))
                + (obs.udf_psf or Decimal("0.00"))
                + (obs.convenience_fee or Decimal("0.00"))
                + (obs.other_fees or Decimal("0.00"))
            )
            assert abs(obs.total_fare - expected_sum) <= Decimal("0.05")

    def test_mmt_multi_carrier_extraction(self):
        content = DEFAULT_MMT_FIXTURE_PATH.read_text(encoding="utf-8")
        obs_list = parse_makemytrip_flight_search(
            raw_content_or_json=content,
            origin="BOM",
            destination="BLR",
            travel_date=date(2026, 10, 15),
            is_synthetic=False,
        )

        carriers = {o.airline_name for o in obs_list}
        carrier_codes = {o.airline_iata for o in obs_list}
        assert "Air India" in carriers
        assert "Akasa Air" in carriers
        assert "SpiceJet" in carriers

        assert {"AI", "QP", "SG"}.issubset(carrier_codes)

    def test_mmt_sold_out_detection(self):
        content = DEFAULT_MMT_FIXTURE_PATH.read_text(encoding="utf-8")
        obs_list = parse_makemytrip_flight_search(
            raw_content_or_json=content,
            origin="BOM",
            destination="BLR",
            travel_date=date(2026, 10, 15),
            is_synthetic=False,
        )

        f_sold = next(o for o in obs_list if o.flight_number == "SG-8711")
        assert f_sold.is_sold_out is True
        assert f_sold.seats_left == 0
        assert f_sold.availability == "sold_out"


# ---------------------------------------------------------------------------
# Collector Tests (IndiGo & MakeMyTrip)
# ---------------------------------------------------------------------------

class TestIndiGoAndMMTCollectors:
    """Integration and execution tests for IndiGoCollector and MakeMyTripCollector."""

    def test_indigo_collector_raw_file_and_parsing(self, db_session):
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_id = uuid.uuid4()
            collector = IndiGoCollector(
                raw_data_dir=tmp_dir,
                run_id=run_id,
                enforce_robots=False,
                is_synthetic=False,
            )

            results = collector.collect(
                origin="DEL",
                destination="BLR",
                travel_date=date(2026, 10, 15),
            )

            assert len(results) == 4
            first = results[0]
            assert first.source_name == "IndiGo"
            assert first.is_synthetic is False
            assert first.raw_reference is not None

            raw_path = Path(first.raw_reference)
            assert raw_path.exists()
            assert "indigo" in raw_path.parts
            raw_data = json.loads(raw_path.read_text(encoding="utf-8"))
            assert "journeys" in raw_data

            # Test persistence in DB session
            source_model = _get_or_create_source(db_session, name="IndiGo", base_url="https://www.goindigo.in")
            run_row = create_collection_run(
                session=db_session,
                source=source_model,
            )
            saved, rej, dups = store_observations(
                session=db_session,
                observations=results,
                rejected=[],
                run=run_row,
            )
            finish_collection_run(
                session=db_session,
                run=run_row,
                records_found=len(results),
                records_saved=saved,
                records_rejected=rej,
            )
            assert saved == 4
            assert rej == 0
            assert dups == 0

            # Verify in DB
            db_obs = db_session.query(AirfareObservation).filter_by(source_id=source_model.id).all()
            assert len(db_obs) == 4
            assert all(not o.is_synthetic for o in db_obs)

    def test_mmt_collector_raw_file_and_parsing(self, db_session):
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_id = uuid.uuid4()
            collector = MakeMyTripCollector(
                raw_data_dir=tmp_dir,
                run_id=run_id,
                enforce_robots=False,
                is_synthetic=False,
            )

            results = collector.collect(
                origin="BOM",
                destination="BLR",
                travel_date=date(2026, 10, 15),
            )

            assert len(results) == 3
            first = results[0]
            assert first.source_name == "MakeMyTrip"
            assert first.is_synthetic is False
            assert first.raw_reference is not None

            raw_path = Path(first.raw_reference)
            assert raw_path.exists()
            assert "makemytrip" in raw_path.parts
            raw_data = json.loads(raw_path.read_text(encoding="utf-8"))
            assert "flightList" in raw_data

            # Test persistence in DB session
            source_model = _get_or_create_source(db_session, name="MakeMyTrip", base_url="https://www.makemytrip.com")
            run_row = create_collection_run(
                session=db_session,
                source=source_model,
            )
            saved, rej, dups = store_observations(
                session=db_session,
                observations=results,
                rejected=[],
                run=run_row,
            )
            finish_collection_run(
                session=db_session,
                run=run_row,
                records_found=len(results),
                records_saved=saved,
                records_rejected=rej,
            )
            assert saved == 3
            assert rej == 0
            assert dups == 0

            db_obs = db_session.query(AirfareObservation).filter_by(source_id=source_model.id).all()
            assert len(db_obs) == 3
            assert all(not o.is_synthetic for o in db_obs)

    def test_block_detection_in_collectors(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            collector = IndiGoCollector(
                raw_data_dir=tmp_dir,
                enforce_robots=False,
            )
            # Simulate 429 response
            results = collector.collect(
                origin="DEL",
                destination="BLR",
                travel_date=date(2026, 10, 15),
                raw_content_override="<html>Too many requests</html>",
                status_code_override=429,
            )
            assert results == []

            # Simulate Cloudflare challenge in MMT
            mmt_collector = MakeMyTripCollector(
                raw_data_dir=tmp_dir,
                enforce_robots=False,
            )
            mmt_results = mmt_collector.collect(
                origin="BOM",
                destination="BLR",
                travel_date=date(2026, 10, 15),
                raw_content_override="<title>Just a moment... Attention Required! | Cloudflare</title>",
                status_code_override=403,
            )
            assert mmt_results == []

    def test_source_registry_integration(self):
        registry = SourceRegistry()
        indigo_cfg = registry.get_source("IndiGo")
        assert indigo_cfg is not None
        assert indigo_cfg.collection_mode == "recorded_fixture"
        assert indigo_cfg.tos_notes == "TO BE REVIEWED BY HUMAN"

        mmt_cfg = registry.get_source("MakeMyTrip")
        assert mmt_cfg is not None
        assert mmt_cfg.collection_mode == "recorded_fixture"
        assert mmt_cfg.tos_notes == "TO BE REVIEWED BY HUMAN"
