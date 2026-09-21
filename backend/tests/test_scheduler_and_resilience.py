"""
backend/tests/test_scheduler_and_resilience.py
Tests for scheduled daily collection orchestrator, circuit breaker resilience,
idempotency on re-runs, mode isolation, coverage report math, and APScheduler service.
"""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import uuid

import pytest

from backend.app.models.airfare import AirfareObservation, Airline, Route, Source
from backend.app.models.collection import CollectionRun
from scraper.framework.circuit_breaker import CircuitBreaker, CircuitBreakerConfig, CircuitState
from scraper.scheduler import create_scheduler
from scripts.coverage_report import calculate_coverage_metrics, render_report_markdown, render_report_table
from scripts.daily_collection import run_daily_collection, validate_mode_isolation


# ---------------------------------------------------------------------------
# 1. Circuit Breaker Unit Tests
# ---------------------------------------------------------------------------

class TestCircuitBreaker:
    """Test Circuit Breaker state transitions, threshold triggers, and cooldown recovery."""

    def test_initial_state_is_closed(self):
        cb = CircuitBreaker("TestAirline", CircuitBreakerConfig(failure_threshold=3, cooldown_seconds=60))
        assert cb.state == CircuitState.CLOSED
        assert cb.allow_request() is True
        assert cb.consecutive_failures == 0

    def test_trips_to_open_after_threshold_failures(self):
        cb = CircuitBreaker("TestAirline", CircuitBreakerConfig(failure_threshold=3, cooldown_seconds=60))

        cb.record_block("Rate limited 429", block_type="rate_limit_429")
        assert cb.state == CircuitState.CLOSED
        assert cb.consecutive_failures == 1
        assert cb.allow_request() is True

        cb.record_block("WAF challenge", block_type="waf_challenge")
        assert cb.state == CircuitState.CLOSED
        assert cb.consecutive_failures == 2
        assert cb.allow_request() is True

        # Third consecutive failure -> should trip to OPEN
        cb.record_block("CAPTCHA challenge", block_type="captcha")
        assert cb.state == CircuitState.OPEN
        assert cb.consecutive_failures == 3
        assert cb.allow_request() is False
        assert "Threshold reached" in (cb.last_trip_reason or "")
        assert cb.trip_count == 1

    def test_success_resets_failures(self):
        cb = CircuitBreaker("TestAirline", CircuitBreakerConfig(failure_threshold=3, cooldown_seconds=60))
        cb.record_block("Temporary 503")
        cb.record_block("Temporary 503")
        assert cb.consecutive_failures == 2

        cb.record_success()
        assert cb.consecutive_failures == 0
        assert cb.state == CircuitState.CLOSED

    def test_cooldown_transitions_to_half_open_and_recovers(self):
        clock_state = [1000.0]
        cb = CircuitBreaker(
            "TestAirline",
            CircuitBreakerConfig(failure_threshold=2, cooldown_seconds=300),
            clock_fn=lambda: clock_state[0],
        )

        # Trip to OPEN
        cb.record_block("Block 1")
        cb.record_block("Block 2")
        assert cb.state == CircuitState.OPEN
        assert cb.allow_request() is False

        # Advance clock by 299s (cooldown not expired)
        clock_state[0] += 299.0
        assert cb.state == CircuitState.OPEN
        assert cb.allow_request() is False

        # Advance clock to 300s -> transitions to HALF_OPEN
        clock_state[0] += 1.0
        assert cb.state == CircuitState.HALF_OPEN
        assert cb.allow_request() is True

        # Successful probe recovers to CLOSED
        cb.record_success()
        assert cb.state == CircuitState.CLOSED
        assert cb.consecutive_failures == 0

    def test_failed_probe_in_half_open_re_trips_to_open(self):
        clock_state = [1000.0]
        cb = CircuitBreaker(
            "TestAirline",
            CircuitBreakerConfig(failure_threshold=2, cooldown_seconds=300),
            clock_fn=lambda: clock_state[0],
        )

        cb.record_block("Block 1")
        cb.record_block("Block 2")
        assert cb.state == CircuitState.OPEN

        # Advance past cooldown
        clock_state[0] += 301.0
        assert cb.state == CircuitState.HALF_OPEN

        # Probe fails -> immediately trips back to OPEN
        cb.record_block("Probe failed", block_type="captcha")
        assert cb.state == CircuitState.OPEN
        assert cb.allow_request() is False
        assert cb.trip_count == 2


# ---------------------------------------------------------------------------
# 2. Mode Isolation Unit Tests
# ---------------------------------------------------------------------------

class TestModeIsolation:
    """Test strict separation of synthetic mock mode and real/recorded mode."""

    def test_mock_sources_allowed(self):
        mode = validate_mode_isolation(["MockCollector"])
        assert mode == "mock"

    def test_real_sources_allowed(self):
        mode = validate_mode_isolation(["EaseMyTrip", "IndiGo"])
        assert mode == "recorded"

    def test_mixed_mock_and_real_sources_raises_error(self):
        with pytest.raises(ValueError, match="Strict mode isolation error"):
            validate_mode_isolation(["MockCollector", "EaseMyTrip"])

        with pytest.raises(ValueError, match="Strict mode isolation error"):
            validate_mode_isolation(["mock", "IndiGo"])


# ---------------------------------------------------------------------------
# 3. Idempotent Daily Collection Integration Tests
# ---------------------------------------------------------------------------

class TestDailyCollectionIdempotency:
    """Test daily collection execution and idempotent re-runs against PostgreSQL."""

    def test_daily_collection_single_run_per_source(self, db_session):
        test_date = date(2026, 9, 21)
        # Run on a restricted grid (1 route, 2 lead windows)
        summary = run_daily_collection(
            collection_date=test_date,
            mode="mock",
            sources=["MockCollector"],
            routes=["BOM-DEL"],
            lead_days=[1, 7],
            seed=42,
            dry_run=False,
            session=db_session,
        )

        assert summary["total_records_saved"] > 0
        assert summary["total_duplicates_skipped"] == 0

        # Verify exactly ONE collection_runs row was created for MockCollector
        runs = db_session.query(CollectionRun).join(Source).filter(
            Source.name == "MockCollector",
        ).all()
        assert len(runs) >= 1
        assert any(r.records_saved == summary["total_records_saved"] for r in runs)

    def test_rerun_is_idempotent_no_duplicates_inserted(self, db_session):
        test_date = date(2026, 9, 22)
        # First Run
        run1 = run_daily_collection(
            collection_date=test_date,
            mode="mock",
            sources=["MockCollector"],
            routes=["DEL-BLR"],
            lead_days=[1, 7],
            seed=100,
            dry_run=False,
            session=db_session,
        )
        saved_first = run1["total_records_saved"]
        assert saved_first > 0

        # Second Run with identical inputs
        run2 = run_daily_collection(
            collection_date=test_date,
            mode="mock",
            sources=["MockCollector"],
            routes=["DEL-BLR"],
            lead_days=[1, 7],
            seed=100,
            dry_run=False,
            session=db_session,
        )

        # On rerun: 0 new rows saved, all detected as duplicates
        assert run2["total_records_saved"] == 0
        assert run2["total_duplicates_skipped"] >= saved_first


# ---------------------------------------------------------------------------
# 4. Coverage Report Calculation Tests
# ---------------------------------------------------------------------------

class TestCoverageReportMetrics:
    """Test coverage calculation, success rates, sold-out share, and block counts."""

    def test_coverage_metrics_calculation(self, db_session):
        # Insert test source and route
        source = Source(name="TestCoverageSource", base_url="https://test.com", is_active=True)
        route = Route(origin="MAA", destination="DEL", route_code="MAA-DEL", is_active=True)
        airline = Airline(name="TestFly", iata_code="TF", is_active=True)
        db_session.add_all([source, route, airline])
        db_session.flush()

        # Insert a collection run with 1 block and 1 captcha
        c_run = CollectionRun(
            id=uuid.uuid4(),
            source_id=source.id,
            status="completed",
            start_time=datetime(2026, 9, 20, 2, 0, 0, tzinfo=timezone.utc),
            records_saved=10,
            blocked_count=1,
            captcha_count=1,
        )
        db_session.add(c_run)
        db_session.flush()

        # Insert 10 observations: 3 sold-out, across 2 distinct collection dates
        for i in range(10):
            obs = AirfareObservation(
                id=uuid.uuid4(),
                collection_run_id=c_run.id,
                collection_timestamp=datetime(2026, 9, 20, 2, 0, 0, tzinfo=timezone.utc),
                collection_date=date(2026, 9, 20) if i < 6 else date(2026, 9, 21),
                source_id=source.id,
                route_id=route.id,
                airline_id=airline.id,
                flight_number=f"TF-{100 + i}",
                travel_date=date(2026, 9, 27),
                lead_days=7,
                fare_class="Economy",
                base_fare=Decimal("3000.00"),
                taxes=Decimal("150.00"),
                udf_psf=Decimal("300.00"),
                convenience_fee=Decimal("200.00"),
                other_fees=Decimal("0.00"),
                total_fare=Decimal("3650.00"),
                is_sold_out=(i < 3),  # 3 sold out out of 10
                is_synthetic=True,
                target_lead_window=7,
                status="valid",
            )
            db_session.add(obs)
        db_session.flush()

        # Calculate coverage over last 7 days ending 2026-09-21
        report = calculate_coverage_metrics(
            session=db_session,
            days=7,
            source_name="TestCoverageSource",
            as_of_date=date(2026, 9, 21),
        )

        assert report["report_period"]["days"] == 7
        assert report["summary"]["total_quotes"] == 10
        assert report["summary"]["total_sold_out_quotes"] == 3
        # Sold-out share = 3 / 10 = 30.0%
        assert report["summary"]["overall_sold_out_share_pct"] == 30.0

        # Check source block count
        assert "TestCoverageSource" in report["sources"]
        assert report["sources"]["TestCoverageSource"]["total_blocks"] == 1
        assert report["sources"]["TestCoverageSource"]["total_captchas"] == 1

        # Check cell metrics (2 distinct days collected out of 7 days -> 2/7 = 28.57%)
        cell = report["cells"][0]
        assert cell["source"] == "TestCoverageSource"
        assert cell["route"] == "MAA-DEL"
        assert cell["lead_window"] == "T+7"
        assert cell["days_collected"] == 2
        assert cell["success_rate_pct"] == round((2 / 7) * 100.0, 2)
        assert cell["sold_out_share_pct"] == 30.0

        # Check renderers do not crash
        table_output = render_report_table(report)
        assert "APIx Airfare Collection Coverage Report" in table_output
        assert "MAA-DEL" in table_output

        md_output = render_report_markdown(report)
        assert "# APIx Collection Coverage Report" in md_output


# ---------------------------------------------------------------------------
# 5. APScheduler Service Configuration Tests
# ---------------------------------------------------------------------------

class TestSchedulerService:
    """Test APScheduler daemon creation and job configuration."""

    def test_create_scheduler_loads_jobs(self):
        custom_config = {
            "scheduler": {
                "cron_expression": "15 3 * * *",  # 03:15 IST
                "timezone": "Asia/Kolkata",
            }
        }
        scheduler = create_scheduler(blocking=False, config=custom_config)
        jobs = scheduler.get_jobs()
        assert len(jobs) == 1
        job = jobs[0]
        assert job.id == "apix_daily_collection"
        assert str(job.trigger.timezone) == "Asia/Kolkata"
