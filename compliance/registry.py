"""
compliance/registry.py
Source configuration models and loader for config/sources.yaml.
"""
from datetime import date
from pathlib import Path
from typing import List, Literal, Optional

import yaml
from pydantic import BaseModel, Field, HttpUrl

SourceType = Literal["airline", "ota"]
CollectionMode = Literal["live_scrape", "official_api", "recorded_fixture", "disabled"]
RobotsStatus = Literal["allowed", "disallowed", "partial", "unreachable", "pending"]

DEFAULT_SOURCES_YAML = Path(__file__).parent.parent / "config" / "sources.yaml"


class SourceConfig(BaseModel):
    """Configuration for an airline or OTA data collection source."""

    name: str = Field(..., description="Official source identifier")
    type: SourceType = Field(..., description="airline | ota")
    base_url: str = Field(..., description="Base domain URL of the source")
    collection_mode: CollectionMode = Field(
        default="recorded_fixture",
        description="live_scrape | official_api | recorded_fixture | disabled",
    )
    max_rps: float = Field(
        default=0.5,
        gt=0.0,
        description="Maximum requests per second allowed",
    )
    robots_status: RobotsStatus = Field(
        default="pending",
        description="allowed | disallowed | partial | unreachable | pending",
    )
    tos_notes: str = Field(
        default="TO BE REVIEWED BY HUMAN",
        description="Human ToS review status and notes",
    )
    last_checked: Optional[date] = Field(
        default=None,
        description="Date of last robots.txt audit",
    )
    search_paths_to_check: List[str] = Field(
        default_factory=list,
        description="List of URL paths to check against robots.txt rules",
    )


class SourceRegistry:
    """Registry that loads and accesses source configurations."""

    def __init__(self, config_path: Optional[Path | str] = None):
        self.config_path = Path(config_path) if config_path else DEFAULT_SOURCES_YAML
        self._sources: dict[str, SourceConfig] = {}
        self.load()

    def load(self) -> None:
        """Load and validate sources from the YAML configuration file."""
        if not self.config_path.exists():
            raise FileNotFoundError(f"Source configuration file not found at: {self.config_path}")

        with open(self.config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        if not data or "sources" not in data:
            raise ValueError(f"Invalid sources configuration format in: {self.config_path}")

        self._sources = {}
        for item in data["sources"]:
            cfg = SourceConfig(**item)
            self._sources[cfg.name] = cfg

    def get_source(self, name: str) -> Optional[SourceConfig]:
        """Retrieve a source configuration by exact name (case-insensitive fallback)."""
        if name in self._sources:
            return self._sources[name]
        for s_name, s_cfg in self._sources.items():
            if s_name.lower() == name.lower():
                return s_cfg
        return None

    def list_sources(self) -> List[SourceConfig]:
        """Return all registered source configurations."""
        return list(self._sources.values())

    def get_by_mode(self, mode: CollectionMode) -> List[SourceConfig]:
        """Filter sources by collection mode."""
        return [s for s in self._sources.values() if s.collection_mode == mode]

    def get_by_type(self, source_type: SourceType) -> List[SourceConfig]:
        """Filter sources by source type (airline vs ota)."""
        return [s for s in self._sources.values() if s.type == source_type]

    def __len__(self) -> int:
        return len(self._sources)

    def __iter__(self):
        return iter(self._sources.values())
