"""
backend/app/models/watchlist.py
ORM model for tracking uncovered route requests (RouteWatchlist).

When users query routes not currently in the APIx basket, requests are recorded here
(deduplicated and rate-limited per client). The collection scheduler reads this table
to identify candidate routes for basket expansion, adhering to sources' collection_mode permissions.
"""
from datetime import datetime, timezone
import hashlib

from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    String,
    UniqueConstraint,
)

from backend.app.database import Base


def _now_utc():
    return datetime.now(timezone.utc)


class RouteWatchlist(Base):
    """
    Tracks requested routes that are currently uncovered.
    """
    __tablename__ = "route_watchlist"

    id = Column(Integer, primary_key=True, autoincrement=True)
    origin = Column(String(3), nullable=False)
    destination = Column(String(3), nullable=False)
    route_code = Column(String(8), nullable=False, index=True)
    client_hash = Column(String(64), nullable=False, index=True)
    request_count = Column(Integer, nullable=False, default=1)
    first_requested_at = Column(DateTime(timezone=True), nullable=False, default=_now_utc)
    last_requested_at = Column(DateTime(timezone=True), nullable=False, default=_now_utc)

    __table_args__ = (
        UniqueConstraint("route_code", "client_hash", name="uq_watchlist_route_client"),
    )

    @classmethod
    def hash_client(cls, client_identifier: str) -> str:
        """Hash client IP or API key to preserve privacy."""
        return hashlib.sha256(client_identifier.encode("utf-8")).hexdigest()

    def __repr__(self) -> str:
        return f"<RouteWatchlist {self.route_code} requests={self.request_count}>"
