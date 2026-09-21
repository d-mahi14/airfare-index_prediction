"""
scraper/collectors/makemytrip_collector.py
MakeMyTrip airfare collector (operated in recorded_fixture mode).

Compliance & Policy:
  - Source: MakeMyTrip (https://www.makemytrip.com)
  - Config: config/sources.yaml (collection_mode: recorded_fixture, tos_notes: 'TO BE REVIEWED BY HUMAN')
  - Live scraping prohibited without human legal review. Operates strictly in recorded_fixture mode.
"""
from datetime import date, datetime, timezone
import logging
from pathlib import Path
from typing import List, Optional
import uuid

from backend.app.schemas.airfare import AirfareObservationCreate
from compliance.registry import SourceConfig, SourceRegistry
from scraper.base import BaseCollector
from scraper.framework.block_detector import detect_block
from scraper.framework.rate_limiter import RateLimiter
from scraper.framework.robots_guard import RobotsGuard
from scraper.parsers.makemytrip_parser import parse_makemytrip_flight_search

logger = logging.getLogger(__name__)

DEFAULT_MMT_FIXTURE_PATH = (
    Path(__file__).parent.parent.parent
    / "tests"
    / "fixtures"
    / "recorded"
    / "makemytrip_search_response.json"
)


class MakeMyTripCollector(BaseCollector):
    """
    MakeMyTrip collector operating in compliant recorded_fixture mode.
    """

    source_name: str = "MakeMyTrip"

    def __init__(
        self,
        fixture_path: Optional[Path | str] = None,
        source_config: Optional[SourceConfig] = None,
        raw_data_dir: str = "data/raw",
        run_id: Optional[uuid.UUID | str] = None,
        enforce_robots: bool = True,
        is_synthetic: bool = False,
    ):
        super().__init__(raw_data_dir=raw_data_dir, run_id=run_id)
        self.fixture_path = Path(fixture_path) if fixture_path else DEFAULT_MMT_FIXTURE_PATH
        self.is_synthetic = is_synthetic
        self.enforce_robots = enforce_robots

        if source_config is None:
            try:
                registry = SourceRegistry()
                self.source_config = registry.get_source(self.source_name)
            except Exception as exc:
                logger.debug(f"Could not load source config for MakeMyTrip: {exc}")
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
        Collect airfare observations for MakeMyTrip.
        """
        origin = origin.strip().upper()
        destination = destination.strip().upper()
        search_path = "/flight/search"

        # 1. Robots.txt check
        if self.enforce_robots and self.source_config:
            self.robots_guard.check_or_raise(
                base_url_or_config=self.source_config.base_url,
                path=search_path,
            )

        # 2. Rate limiting
        self.rate_limiter.acquire()

        # 3. Retrieve raw payload
        if raw_content_override is not None:
            raw_content = raw_content_override
            status_code = status_code_override
        else:
            if not self.fixture_path.exists():
                logger.error(f"MakeMyTrip fixture not found at {self.fixture_path}")
                return []
            raw_content = self.fixture_path.read_text(encoding="utf-8")
            status_code = 200

        # 4. Block detection
        block_res = detect_block(status_code=status_code, content=raw_content)
        if block_res is not None:
            logger.warning(f"MakeMyTrip collection blocked: {block_res.block_type}")
            return []

        # 5. Persist raw response to data/raw/makemytrip/{date}/{run_id}/
        collection_ts = datetime.now(timezone.utc)
        collection_date = collection_ts.date()
        raw_filename = f"mmt_{origin}_{destination}_{travel_date.strftime('%Y%m%d')}.json"
        raw_path = self._save_raw(
            content=raw_content,
            suffix="json",
            collection_date=collection_date,
            run_id=self._run_id,
            filename_override=raw_filename,
        )

        # 6. Parse observations
        observations = parse_makemytrip_flight_search(
            raw_content_or_json=raw_content,
            origin=origin,
            destination=destination,
            travel_date=travel_date,
            collection_timestamp=collection_ts,
            is_synthetic=self.is_synthetic,
            raw_reference=str(raw_path),
        )

        return observations
