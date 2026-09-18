"""
scraper/base.py
Abstract base class for all airfare collectors.

Design principle: Every collector follows the same interface.
Swapping from MockCollector to a real Playwright collector requires
changing only the concrete class — the pipeline remains unchanged.
"""
import abc
import logging
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import List

from backend.app.schemas.airfare import AirfareObservationCreate

logger = logging.getLogger(__name__)


class CollectorError(Exception):
    """Raised when a collector encounters an unrecoverable error."""
    pass


class BaseCollector(abc.ABC):
    """
    Abstract base for all airfare data collectors.

    Subclasses must implement:
        collect(origin, destination, travel_date) -> List[AirfareObservationCreate]

    The collect() method should return a list of validated Pydantic observations.
    It must NOT write to the database — that is the pipeline's job.
    """

    source_name: str  # Subclasses must define this class attribute

    def __init__(self, raw_data_dir: str = "data/raw"):
        self.raw_data_dir = Path(raw_data_dir)
        self.raw_data_dir.mkdir(parents=True, exist_ok=True)
        self._run_id = uuid.uuid4()

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
            CollectorError: if the collection fails unrecoverably.
        """
        ...

    def _save_raw(self, content: str, suffix: str = "txt") -> Path:
        """
        Persist raw collected content to disk for reproducibility.

        Returns the path to the saved file.
        """
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        filename = f"{self.source_name}_{ts}_{self._run_id.hex[:8]}.{suffix}"
        path = self.raw_data_dir / filename
        path.write_text(content, encoding="utf-8")
        logger.debug(f"Raw content saved to {path}")
        return path

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} source={self.source_name}>"
