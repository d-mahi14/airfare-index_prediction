"""
backend/app/models/__init__.py
Import all models here so Alembic's autogenerate can discover them.
"""
from backend.app.models.airfare import (  # noqa: F401
    Airline,
    AirfareObservation,
    Route,
    Source,
)
from backend.app.models.collection import CollectionRun  # noqa: F401
from backend.app.models.index import IndexValue, RouteWeight  # noqa: F401
