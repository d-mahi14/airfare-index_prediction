"""
backend/tests/test_collector_framework.py
Unit and integration tests for collector framework, rate limiter, robots guard,
retry mechanism, block detector, raw file storage, and recorded fixture collector.
"""
from datetime import date, datetime, time, timezone
from decimal import Decimal
from pathlib import Path
import random
import uuid

import pytest

from backend.app.models.airfare import AirfareObservation
from backend.app.models.collection import CollectionRun
from backend.app.schemas.airfare import AirfareObservationCreate
from compliance.registry import SourceConfig
from compliance.robots import RobotsChecker, RobotsResult
from scraper.base import BaseCollector, BlockedResult, CollectorError, DisallowedError
from scraper.collectors.recorded_collector import EaseMyTripCollector, RecordedCollector
from scraper.framework.block_detector import BlockDetector, detect_block
from scraper.framework.rate_limiter import RateLimiter
from scraper.framework.retry import compute_backoff_delay, retry_with_backoff
from scraper.framework.robots_guard import RobotsGuard
from scraper.parsers.recorded_parser import parse_flight_item, parse_recorded_flight_search
from scraper.pipelines.storage import create_collection_run, finish_collection_run, store_observations


# ---------------------------------------------------------------------------
# RateLimiter Tests
# ---------------------------------------------------------------------------

class TestRateLimiter:
    """Test rate limiter interval calculation, jitter bounds, and timing."""

    def test_base_interval(self):
        rl = RateLimiter(max_rps=0.5, jitter_pct=0.2)
        assert rl.base_interval == 2.0

    def test_invalid_parameters_raise(self):
        with pytest.raises(ValueError, match="max_rps must be strictly positive"):
            RateLimiter(max_rps=0)
        with pytest.raises(ValueError, match="jitter_pct must be between"):
            RateLimiter(max_rps=1.0, jitter_pct=1.5)

    def test_compute_delay_first_call_is_zero(self):
        rl = RateLimiter(max_rps=1.0, jitter_pct=0.0)
        delay = rl.compute_delay(last_time=None, current_time=100.0)
        assert delay == 0.0

    def test_compute_delay_with_jitter_bounds(self):
        rl = RateLimiter(max_rps=2.0, jitter_pct=0.2)  # base_interval = 0.5s, jitter [0.4s, 0.6s]
        rng = random.Random(42)
        delays = [
            rl.compute_delay(last_time=100.0, current_time=100.0, rng=rng)
            for _ in range(50)
        ]
        assert all(0.40 <= d <= 0.60 for d in delays)

    def test_elapsed_time_reduces_delay(self):
        rl = RateLimiter(max_rps=1.0, jitter_pct=0.0)  # base_interval = 1.0s
        # 0.4s elapsed since last request
        delay = rl.compute_delay(last_time=100.0, current_time=100.4)
        assert abs(delay - 0.6) < 1e-5

    def test_acquire_sleeps_and_updates_time(self):
        slept_durations = []
        clock_state = [100.0]

        def fake_clock():
            return clock_state[0]

        def fake_sleep(duration):
            slept_durations.append(duration)
            clock_state[0] += duration

        rl = RateLimiter(max_rps=1.0, jitter_pct=0.0, clock_fn=fake_clock, sleep_fn=fake_sleep)
        rl.acquire()  # First call, no sleep
        assert len(slept_durations) == 0

        # Immediate second call at same timestamp
        rl.acquire()
        assert len(slept_durations) == 1
        assert abs(slept_durations[0] - 1.0) < 1e-5


# ---------------------------------------------------------------------------
# Retry with Backoff Tests
# ---------------------------------------------------------------------------

class TestRetryWithBackoff:
    """Test exponential backoff and non-retryable exception rules."""

    def test_backoff_delay_exponential_growth(self):
        d0 = compute_backoff_delay(attempt=0, base_delay=1.0, backoff_factor=2.0, jitter=False)
        d1 = compute_backoff_delay(attempt=1, base_delay=1.0, backoff_factor=2.0, jitter=False)
        d2 = compute_backoff_delay(attempt=2, base_delay=1.0, backoff_factor=2.0, jitter=False)
        assert d0 == 1.0
        assert d1 == 2.0
        assert d2 == 4.0

    def test_successful_retry_on_transient_error(self):
        attempts = 0
        slept = []

        @retry_with_backoff(max_retries=3, base_delay=0.1, jitter=False, sleep_fn=slept.append)
        def flaky_function():
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise ConnectionResetError("Connection dropped")
            return "SUCCESS"

        result = flaky_function()
        assert result == "SUCCESS"
        assert attempts == 3
        assert len(slept) == 2

    def test_disallowed_error_never_retried(self):
        attempts = 0

        @retry_with_backoff(max_retries=3, sleep_fn=lambda _: None)
        def guarded_function():
            nonlocal attempts
            attempts += 1
            raise DisallowedError("Robots.txt disallows access")

        with pytest.raises(DisallowedError):
            guarded_function()

        # Must fail immediately on attempt 1 without retrying
        assert attempts == 1

    def test_blocked_result_stops_immediately_without_retry(self):
        attempts = 0

        @retry_with_backoff(max_retries=3, sleep_fn=lambda _: None)
        def scrape_function():
            nonlocal attempts
            attempts += 1
            return BlockedResult(is_blocked=True, block_type="captcha", status_code=403)

        result = scrape_function()
        assert isinstance(result, BlockedResult)
        assert result.block_type == "captcha"
        # Zero retries
        assert attempts == 1


# ---------------------------------------------------------------------------
# RobotsGuard Tests
# ---------------------------------------------------------------------------

class TestRobotsGuard:
    """Test robots.txt compliance checking."""

    def test_allowed_path_passes(self):
        checker = RobotsChecker()
        # Mock fetch_robots to return reachable allowed
        checker._memory_cache["https://www.example.com"] = RobotsResult(
            base_url="https://www.example.com",
            robots_url="https://www.example.com/robots.txt",
            is_reachable=True,
            status_code=200,
            raw_content="User-agent: *\nAllow: /search\n",
        )
        # Parse it
        from urllib.robotparser import RobotFileParser
        p = RobotFileParser()
        p.parse(["User-agent: *", "Allow: /search"])
        checker._memory_cache["https://www.example.com"].parser = p

        guard = RobotsGuard(checker=checker)
        # Should not raise
        guard.check_or_raise("https://www.example.com", path="/search/flights")
        assert guard.is_allowed("https://www.example.com", path="/search/flights") is True

    def test_disallowed_path_raises_disallowed_error(self):
        checker = RobotsChecker()
        from urllib.robotparser import RobotFileParser
        p = RobotFileParser()
        p.parse(["User-agent: *", "Disallow: /private/"])
        checker._memory_cache["https://www.example.com"] = RobotsResult(
            base_url="https://www.example.com",
            robots_url="https://www.example.com/robots.txt",
            is_reachable=True,
            status_code=200,
            raw_content="User-agent: *\nDisallow: /private/\n",
            parser=p,
        )

        guard = RobotsGuard(checker=checker)
        with pytest.raises(DisallowedError, match="disallowed by robots.txt"):
            guard.check_or_raise("https://www.example.com", path="/private/booking")

    def test_unreachable_robots_raises_disallowed_error(self):
        checker = RobotsChecker()
        checker._memory_cache["https://www.failing-site.com"] = RobotsResult(
            base_url="https://www.failing-site.com",
            robots_url="https://www.failing-site.com/robots.txt",
            is_reachable=False,
            status_code=504,
            error_message="Gateway Timeout",
        )
        guard = RobotsGuard(checker=checker)
        # Fail closed: unreachable != allowed
        with pytest.raises(DisallowedError):
            guard.check_or_raise("https://www.failing-site.com", path="/flight-search")


# ---------------------------------------------------------------------------
# BlockDetector Tests
# ---------------------------------------------------------------------------

class TestBlockDetector:
    """Test detection of CAPTCHAs, Cloudflare WAF, and 429 rate limit blocks."""

    def test_detect_429_status_code(self):
        res = detect_block(status_code=429, content="")
        assert res is not None
        assert res.is_blocked is True
        assert res.block_type == "rate_limit_429"
        assert res.status_code == 429

    def test_detect_403_waf_status_code(self):
        res = detect_block(status_code=403, content="Access Denied")
        assert res is not None
        assert res.is_blocked is True
        assert res.block_type == "waf_challenge"
        assert res.status_code == 403

    def test_detect_captcha_page_fixture(self):
        fixture_path = Path(__file__).parent.parent.parent / "tests" / "fixtures" / "captcha_page.html"
        assert fixture_path.exists()
        content = fixture_path.read_text(encoding="utf-8")

        res = detect_block(status_code=200, content=content)
        assert res is not None
        assert res.is_blocked is True
        assert res.block_type == "captcha"

    def test_detect_waf_fixture(self):
        fixture_path = Path(__file__).parent.parent.parent / "tests" / "fixtures" / "waf_block.html"
        assert fixture_path.exists()
        content = fixture_path.read_text(encoding="utf-8")

        res = detect_block(status_code=403, content=content)
        assert res is not None
        assert res.is_blocked is True
        assert res.block_type == "waf_challenge"

    def test_clean_response_returns_none(self):
        clean_json = '{"status": "ok", "flights": [{"flight_number": "6E-101"}]}'
        res = detect_block(status_code=200, content=clean_json)
        assert res is None


# ---------------------------------------------------------------------------
# Raw Response Storage Tests
# ---------------------------------------------------------------------------

class TestRawStorage:
    """Test raw response file persistence under data/raw/{source}/{date}/{run_id}/."""

    def test_raw_directory_structure(self, tmp_path):
        class DummyCollector(BaseCollector):
            source_name = "TestAirline"
            def collect(self, origin, destination, travel_date):
                return []

        run_id = uuid.uuid4()
        collector = DummyCollector(raw_data_dir=str(tmp_path), run_id=run_id)
        saved_path = collector._save_raw(
            content='{"test": 123}',
            suffix="json",
            collection_date=date(2026, 9, 20),
        )

        expected_dir = tmp_path / "testairline" / "2026-09-20" / str(run_id)
        assert saved_path.exists()
        assert saved_path.parent == expected_dir
        assert saved_path.read_text(encoding="utf-8") == '{"test": 123}'


# ---------------------------------------------------------------------------
# Recorded Collector & Parser Tests
# ---------------------------------------------------------------------------

class TestRecordedCollectorAndParser:
    """Test flight parsing from recorded JSON fixture and observation properties."""

    def test_parser_with_fixture(self):
        fixture_path = Path(__file__).parent.parent.parent / "tests" / "fixtures" / "recorded" / "easemytrip_search_response.json"
        assert fixture_path.exists()
        content = fixture_path.read_text(encoding="utf-8")

        travel_date = date(2026, 10, 5)
        obs_list = parse_recorded_flight_search(
            raw_content_or_json=content,
            origin="BOM",
            destination="DEL",
            travel_date=travel_date,
            source_name="EaseMyTrip",
            is_synthetic=False,
            raw_reference="data/raw/easemytrip/2026-09-20/run1/search.json",
        )

        assert len(obs_list) == 5

        # Check IndiGo flight
        indigo = next(o for o in obs_list if o.airline_iata == "6E")
        assert indigo.airline_name == "IndiGo"
        assert indigo.flight_number == "6E-5324"
        assert indigo.dep_time == time(6, 0)
        assert indigo.dep_band == "morning"
        assert indigo.stops == 0
        assert indigo.duration_min == 135
        assert indigo.base_fare == Decimal("3500.00")
        assert indigo.taxes == Decimal("175.00")
        assert indigo.udf_psf == Decimal("380.00")
        assert indigo.convenience_fee == Decimal("300.00")
        assert indigo.other_fees == Decimal("0.00")
        assert indigo.total_fare == Decimal("4355.00")
        assert indigo.is_sold_out is False
        assert indigo.seats_left == 9
        assert indigo.is_synthetic is False
        assert indigo.raw_reference == "data/raw/easemytrip/2026-09-20/run1/search.json"

        # Check sold out flight (Air India Express)
        ix = next(o for o in obs_list if o.airline_iata == "IX")
        assert ix.airline_name == "Air India Express"
        assert ix.is_sold_out is True
        assert ix.seats_left == 0
        assert ix.availability == "sold_out"
        assert ix.total_fare == ix.base_fare + ix.taxes + ix.udf_psf + ix.convenience_fee + ix.other_fees

    def test_recorded_collector_collect_flow(self, tmp_path):
        collector = EaseMyTripCollector(
            raw_data_dir=str(tmp_path),
            enforce_robots=False,  # Isolated unit test
            is_synthetic=False,
        )

        travel_date = date(2026, 10, 5)
        observations = collector.collect(
            origin="BOM",
            destination="DEL",
            travel_date=travel_date,
        )

        assert len(observations) == 5
        for obs in observations:
            assert obs.origin == "BOM"
            assert obs.destination == "DEL"
            assert obs.travel_date == travel_date
            assert obs.is_synthetic is False
            assert obs.raw_reference is not None
            assert Path(obs.raw_reference).exists()

    def test_recorded_collector_stops_on_captcha(self, tmp_path):
        collector = EaseMyTripCollector(
            raw_data_dir=str(tmp_path),
            enforce_robots=False,
        )
        captcha_html = "<html><body>Please verify you are human: cf-chl-bypass</body></html>"
        observations = collector.collect(
            origin="BOM",
            destination="DEL",
            travel_date=date(2026, 10, 5),
            raw_content_override=captcha_html,
            status_code_override=403,
        )
        # Should halt and return empty list without crashing or attempting bypass
        assert observations == []


# ---------------------------------------------------------------------------
# Database Storage Integration Test
# ---------------------------------------------------------------------------

class TestStorageWithRecordedCollector:
    """Test storing real/recorded observations into PostgreSQL test database."""

    def test_store_recorded_observations(self, db_session, tmp_path):
        collector = EaseMyTripCollector(
            raw_data_dir=str(tmp_path),
            enforce_robots=False,
            is_synthetic=False,
        )

        travel_date = date(2026, 10, 5)
        observations = collector.collect(
            origin="BOM",
            destination="DEL",
            travel_date=travel_date,
        )
        assert len(observations) > 0

        from scraper.pipelines.storage import _get_or_create_source
        source_model = _get_or_create_source(db_session, name="EaseMyTrip", base_url="https://www.easemytrip.com")
        run = create_collection_run(
            db_session,
            source=source_model,
        )

        saved, rej, dups = store_observations(
            session=db_session,
            observations=observations,
            rejected=[],
            run=run,
        )

        finish_collection_run(
            session=db_session,
            run=run,
            records_found=len(observations),
            records_saved=saved,
            records_rejected=rej,
        )

        assert saved == len(observations)
        assert rej == 0
        assert dups == 0

        # Query and verify stored row in DB
        db_obs = db_session.query(AirfareObservation).filter_by(
            flight_number="6E-5324",
            travel_date=travel_date,
        ).first()

        assert db_obs is not None
        assert db_obs.total_fare == Decimal("4355.00")
        assert db_obs.base_fare == Decimal("3500.00")
        assert db_obs.taxes == Decimal("175.00")
        assert db_obs.udf_psf == Decimal("380.00")
        assert db_obs.convenience_fee == Decimal("300.00")
        assert db_obs.is_synthetic is False
        assert db_obs.raw_reference is not None
        assert Path(db_obs.raw_reference).exists()
