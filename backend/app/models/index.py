"""
backend/app/models/index.py
Index-related ORM models.

IndexValue  -- the computed daily APIx value
RouteWeight -- the weight assigned to each route in the weighted index

Note: RouteWeight is a stub in Milestone 1 — it will be populated when
the PSD route weight specification is provided (Phase 11).
"""
from datetime import date, datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from backend.app.database import Base


def _now_utc():
    return datetime.now(timezone.utc)


class IndexValue(Base):
    """
    Daily computed APIx value.

    apix_value is stored as NUMERIC(10, 4) to support fractional index values
    (e.g. 121.4372) without floating-point precision issues.

    methodology_version allows us to recompute with a new methodology and
    compare versions while keeping historical values intact.
    """
    __tablename__ = "index_values"

    id = Column(Integer, primary_key=True, autoincrement=True)
    index_date = Column(Date, nullable=False, index=True)
    apix_value = Column(
        Numeric(10, 4),
        nullable=False,
        comment="Computed daily APIx (base=100 in base_year)",
    )
    methodology_version = Column(
        String(20),
        nullable=False,
        default="v1.0",
        comment="Version of the index calculation methodology",
    )
    observation_count = Column(
        Integer,
        nullable=True,
        comment="Number of fare observations used in this computation",
    )
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now_utc)

    __table_args__ = (
        UniqueConstraint("index_date", "methodology_version", name="uq_index_date_version"),
    )

    def __repr__(self) -> str:
        return f"<IndexValue date={self.index_date} apix={self.apix_value}>"


class RouteWeight(Base):
    """
    Weight assigned to a route in the weighted APIx calculation.

    Populated from the PSD specification (to be provided at Phase 11).
    The sum of all active weights for a given effective_date should equal 1.0.

    source field records where the weight came from (e.g. 'PSD_v1', 'DGCA_2024').
    """
    __tablename__ = "route_weights"

    id = Column(Integer, primary_key=True, autoincrement=True)
    route_id = Column(
        Integer,
        ForeignKey("routes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    weight = Column(
        Numeric(8, 6),
        nullable=False,
        comment="Route weight (0-1); all active weights must sum to ~1.0",
    )
    effective_date = Column(
        Date,
        nullable=False,
        comment="Date from which this weight applies",
    )
    is_active = Column(Boolean, nullable=False, default=True)
    source = Column(
        Text,
        nullable=True,
        comment="Reference for the weight specification (e.g. PSD_v1)",
    )
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now_utc)

    route = relationship("Route", back_populates="route_weights")

    __table_args__ = (
        UniqueConstraint("route_id", "effective_date", name="uq_route_weight_date"),
    )

    def __repr__(self) -> str:
        return f"<RouteWeight route_id={self.route_id} weight={self.weight}>"
