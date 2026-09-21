"""
scraper/grid.py
Collection grid generator for the APIx data collection matrix.

Generates the multi-dimensional observation space:
  Routes x Lead Windows x Carriers x Departure Bands x Sources x Fare Class
"""
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, Iterator, List, Optional

import yaml

DEFAULT_COLLECTION_YAML = Path(__file__).parent.parent / "config" / "collection.yaml"
DEFAULT_ROUTES_YAML = Path(__file__).parent / "config" / "routes.yaml"


@dataclass(frozen=True)
class GridCell:
    """Atomic collection target in the observation grid."""

    route_code: str
    origin: str
    destination: str
    lead_days: int
    collection_date: date
    travel_date: date
    source: str
    fare_class: str = "Economy"
    carrier_name: Optional[str] = None
    carrier_iata: Optional[str] = None
    departure_band: Optional[str] = None

    @property
    def cell_key(self) -> str:
        return f"{self.source}:{self.route_code}:T+{self.lead_days}:{self.travel_date}:{self.fare_class}"


class CollectionGrid:
    """Generates and manages collection grid execution cells."""

    def __init__(
        self,
        config_path: Optional[Path | str] = None,
        routes_config_path: Optional[Path | str] = None,
    ):
        self.config_path = Path(config_path) if config_path else DEFAULT_COLLECTION_YAML
        self.routes_config_path = Path(routes_config_path) if routes_config_path else DEFAULT_ROUTES_YAML
        self._load_config()

    def _load_config(self) -> None:
        if self.config_path.exists():
            with open(self.config_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
                grid_cfg = data.get("grid", {})
                self.lead_days = grid_cfg.get("lead_days", [1, 7, 15, 30, 45])
                self.carriers = grid_cfg.get("carriers", [
                    {"name": "IndiGo", "iata": "6E"},
                    {"name": "Air India", "iata": "AI"},
                    {"name": "SpiceJet", "iata": "SG"},
                    {"name": "Air India Express", "iata": "IX"},
                    {"name": "Akasa Air", "iata": "QP"},
                ])
                self.departure_bands = grid_cfg.get(
                    "departure_bands",
                    ["early", "morning", "afternoon", "evening", "night"],
                )
                self.fare_classes = grid_cfg.get("fare_classes", ["Economy"])
                self.default_sources = grid_cfg.get("default_sources", ["MockCollector"])
        else:
            self.lead_days = [1, 7, 15, 30, 45]
            self.carriers = [{"name": "IndiGo", "iata": "6E"}]
            self.departure_bands = ["morning", "evening"]
            self.fare_classes = ["Economy"]
            self.default_sources = ["MockCollector"]

        # Load active routes
        self.routes = []
        if self.routes_config_path.exists():
            with open(self.routes_config_path, "r", encoding="utf-8") as f:
                r_data = yaml.safe_load(f) or {}
                for r in r_data.get("routes", []):
                    if r.get("active", True):
                        self.routes.append({
                            "origin": r["origin"].upper(),
                            "destination": r["destination"].upper(),
                            "route_code": r["route_code"].upper(),
                            "name": r.get("name", r["route_code"]),
                        })

    def generate_cells(
        self,
        collection_date: Optional[date] = None,
        routes: Optional[List[str]] = None,
        lead_days: Optional[List[int]] = None,
        sources: Optional[List[str]] = None,
    ) -> List[GridCell]:
        """
        Generate list of collection GridCells for the specified filters.
        """
        col_date = collection_date or date.today()
        selected_leads = lead_days if lead_days is not None else self.lead_days
        selected_sources = sources if sources is not None else self.default_sources

        # Filter routes if specified
        target_routes = self.routes
        if routes:
            norm_routes = {r.upper().strip() for r in routes}
            target_routes = [
                r for r in self.routes
                if r["route_code"] in norm_routes or f"{r['origin']}-{r['destination']}" in norm_routes
            ]

        cells = []
        for src in selected_sources:
            for r in target_routes:
                for ld in selected_leads:
                    travel_dt = col_date + timedelta(days=ld)
                    for fc in self.fare_classes:
                        cell = GridCell(
                            route_code=r["route_code"],
                            origin=r["origin"],
                            destination=r["destination"],
                            lead_days=ld,
                            collection_date=col_date,
                            travel_date=travel_dt,
                            source=src,
                            fare_class=fc,
                        )
                        cells.append(cell)

        return cells

    def total_cells_count(
        self,
        collection_date: Optional[date] = None,
        routes: Optional[List[str]] = None,
        lead_days: Optional[List[int]] = None,
        sources: Optional[List[str]] = None,
    ) -> int:
        """Return the count of collection cells."""
        return len(self.generate_cells(collection_date, routes, lead_days, sources))
