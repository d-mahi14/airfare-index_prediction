"""
scraper/collectors/recorded_collector.py
High-fidelity recorded fixture collector for EaseMyTrip (and general recorded sources).

Compliance & Design Rationale:
  - Source chosen: EaseMyTrip (configured in config/sources.yaml).
  - Justification per docs/COMPLIANCE.md: All sources are set to collection_mode: recorded_fixture
    with tos_notes: 'TO BE REVIEWED BY HUMAN'. Because human legal review is pending,
    live scraping is prohibited and this collector operates strictly in recorded_fixture mode.
  - Safe Playwright Architecture:
    If live scraping were ever authorized, the collector intercepts JSON API responses from the
    search results page and halts immediately at the fare-breakup step. It NEVER enters passenger
    details, NEVER attempts checkout/holds/payments, and NEVER logs in or solves CAPTCHAs.
"""
from datetime import date, datetime, timezone
import json
import logging
from pathlib import Path
from typing import List, Optional
import uuid

from backend.app.schemas.airfare import AirfareObservationCreate
from compliance.registry import SourceConfig, SourceRegistry
from scraper.base import BaseCollector, BlockedResult, DisallowedError
from scraper.framework.block_detector import BlockDetector, detect_block
from scraper.framework.rate_limiter import RateLimiter
from scraper.framework.robots_guard import RobotsGuard
from scraper.parsers.recorded_parser import parse_recorded_flight_search

logger = logging.getLogger(__name__)

DEFAULT_FIXTURE_PATH = (
    Path(__file__).parent.parent.parent
    / "tests"
    / "fixtures"
    / "recorded"
    / "easemytrip_search_response.json"
)


class RecordedCollector(BaseCollector):
    """
    Collector operating in recorded_fixture mode against validated capture fixtures.
    """

    source_name: str = "EaseMyTrip"

    def __init__(
        self,
        source_name: str = "EaseMyTrip",
        fixture_path: Optional[Path | str] = None,
        source_config: Optional[SourceConfig] = None,
        raw_data_dir: str = "data/raw",
        run_id: Optional[uuid.UUID | str] = None,
        enforce_robots: bool = True,
        is_synthetic: bool = False,
    ):
        super().__init__(raw_data_dir=raw_data_dir, run_id=run_id)
        self.source_name = source_name
        self.fixture_path = Path(fixture_path) if fixture_path else DEFAULT_FIXTURE_PATH
        self.is_synthetic = is_synthetic
        self.enforce_robots = enforce_robots

        # Load source config from registry if not provided
        if source_config is None:
            try:
                registry = SourceRegistry()
                self.source_config = registry.get_source(self.source_name)
            except Exception as exc:
                logger.debug(f"Could not load source registry: {exc}")
                self.source_config = None
        else:
            self.source_config = source_config

        max_rps = self.source_config.max_rps if self.source_config else 0.5
        self.rate_limiter = RateLimiter(max_rps=max_rps, jitter_pct=0.2)
        self.robots_guard = RobotsGuard()

    def collect(
        self,
        origin: str,
        destination: str,
        travel_date: date,
        raw_content_override: Optional[str] = None,
        status_code_override: Optional[int] = 200,
    ) -> List[AirfareObservationCreate]:
        """
        Collect observations for the requested route and travel date.

        Steps:
          1. RobotsGuard check against source search path (raises DisallowedError if disallowed).
          2. RateLimiter token acquisition (polite spacing).
          3. Load recorded response fixture (or content override).
          4. BlockDetector inspection (returns empty list / logs if CAPTCHA or 429 encountered).
          5. Save raw response to data/raw/{source}/{date}/{run_id}/.
          6. Parse flight quotes, link raw_reference, and return validated Pydantic observations.
        """
        origin = origin.strip().upper()
        destination = destination.strip().upper()
        search_path = "/FlightList"

        # 1. Robots.txt Compliance Guard
        if self.enforce_robots and self.source_config:
            self.robots_guard.check_or_raise(
                base_url_or_config=self.source_config.base_url,
                path=search_path,
            )

        # 2. Rate Limiting
        self.rate_limiter.acquire()

        # 3. Retrieve raw response content
        if raw_content_override is not None:
            raw_content = raw_content_override
            status_code = status_code_override
        else:
            if not self.fixture_path.exists():
                logger.error(f"Recorded fixture file not found at: {self.fixture_path}")
                return []
            raw_content = self.fixture_path.read_text(encoding="utf-8")
            status_code = 200

        # 4. Anti-Bot / CAPTCHA / 429 Block Detection
        block_result = detect_block(status_code=status_code, content=raw_content)
        if block_result is not None:
            logger.warning(
                f"Collection blocked for {self.source_name} on {origin}-{destination}: "
                f"block_type={block_result.block_type}, status={block_result.status_code}"
            )
            # Ethical policy: Halt immediately, do not attempt to bypass or solve CAPTCHA
            return []

        # 5. Save raw response to data/raw/{source}/{date}/{run_id}/
        collection_ts = datetime.now(timezone.utc)
        collection_date = collection_ts.date()
        raw_filename = f"search_{origin}_{destination}_{travel_date.strftime('%Y%m%d')}.json"
        raw_path = self._save_raw(
            content=raw_content,
            suffix="json",
            collection_date=collection_date,
            run_id=self._run_id,
            filename_override=raw_filename,
        )

        # 6. Parse flight records
        observations = parse_recorded_flight_search(
            raw_content_or_json=raw_content,
            origin=origin,
            destination=destination,
            travel_date=travel_date,
            collection_timestamp=collection_ts,
            source_name=self.source_name,
            is_synthetic=self.is_synthetic,
            raw_reference=str(raw_path),
        )

        return observations


class EaseMyTripCollector(RecordedCollector):
    """EaseMyTrip recorded collector specialization."""

    source_name: str = "EaseMyTrip"
