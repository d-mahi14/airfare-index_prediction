"""
scraper/base.py
Abstract base class and core data contracts for all airfare collectors.

Design principle: Every collector follows the same interface.
Swapping from MockCollector to a real Playwright collector or recorded fixture collector
requires changing only the concrete class — the downstream validation & storage
pipelines remain unchanged.
"""
import abc
from dataclasses import dataclass
from datetime import date, datetime, timezone
import logging
from pathlib import Path
import re
from typing import List, Optional
import uuid

from backend.app.schemas.airfare import AirfareObservationCreate

logger = logging.getLogger(__name__)


class CollectorError(Exception):
    """Raised when a collector encounters an unrecoverable error."""
    pass


class DisallowedError(CollectorError):
    """Raised when access to a route/path is disallowed by robots.txt or compliance policy."""
    pass


@dataclass
class BlockedResult:
    """
    Result returned when a target site presents a bot challenge, CAPTCHA, or rate limit block.
    Ethical policy: We NEVER solve CAPTCHAs, rotate IPs to evade, or attempt evasion.
    """
    is_blocked: bool = True
    block_type: str = "captcha"  # "captcha" | "rate_limit_429" | "waf_challenge" | "ip_block"
    status_code: Optional[int] = None
    message: str = ""
    url: Optional[str] = None


class BaseCollector(abc.ABC):
    """
    Abstract base for all airfare data collectors.

    Subclasses must implement:
        collect(origin, destination, travel_date) -> List[AirfareObservationCreate]

    The collect() method should return a list of validated Pydantic observations.
    It must NOT write to the database — that is the pipeline's job.
    """

    source_name: str  # Subclasses must define this class attribute

    def __init__(
        self,
        raw_data_dir: str = "data/raw",
        run_id: Optional[uuid.UUID | str] = None,
    ):
        self.raw_data_dir = Path(raw_data_dir)
        self.raw_data_dir.mkdir(parents=True, exist_ok=True)
        if run_id is None:
            self._run_id = uuid.uuid4()
        elif isinstance(run_id, str):
            self._run_id = uuid.UUID(run_id)
        else:
            self._run_id = run_id

    @property
    def run_id(self) -> uuid.UUID:
        return self._run_id

    @abc.abstractmethod
    def collect(
        self,
        origin: str,
        destination: str,
        travel_date: date,
    ) -> List[AirfareObservationCreate]:
        """
        Collect airfare observations for a single route and travel date.

        Args:
            origin:       IATA origin airport code (e.g. "BOM")
            destination:  IATA destination airport code (e.g. "DEL")
            travel_date:  Date of travel

        Returns:
            List of validated AirfareObservationCreate objects.
            Returns empty list if no fares found (never raises for empty results).

        Raises:
            CollectorError / DisallowedError: if the collection fails unrecoverably.
        """
        ...

    def _save_raw(
        self,
        content: str,
        suffix: str = "json",
        collection_date: Optional[date] = None,
        run_id: Optional[uuid.UUID | str] = None,
        filename_override: Optional[str] = None,
    ) -> Path:
        """
        Persist raw collected content to disk under data/raw/{source}/{date}/{run_id}/.

        Returns the path to the saved file.
        """
        source_slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", self.source_name.lower()).strip("_")
        date_str = collection_date.isoformat() if collection_date else datetime.now(timezone.utc).strftime("%Y-%m-%d")
        effective_run_id = str(run_id or self._run_id)

        target_dir = self.raw_data_dir / source_slug / date_str / effective_run_id
        target_dir.mkdir(parents=True, exist_ok=True)

        if filename_override:
            filename = filename_override
        else:
            ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")[:19]
            filename = f"raw_response_{ts}.{suffix}"

        path = target_dir / filename
        path.write_text(content, encoding="utf-8")
        logger.debug(f"Raw content saved to {path}")
        return path

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} source={self.source_name}>"
