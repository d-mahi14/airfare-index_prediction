"""
backend/app/models/index.py
Index-related ORM models.

IndexValue      -- computed APIx price index values (overall, route-level, or lead-time variants)
RouteWeight     -- weight assigned to each route (derived from DGCA city-pair traffic)
LeadTimeWeight  -- weight assigned to each advance-purchase lead window (T+1, T+7, T+15, T+30, T+45)
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
    SmallInteger,
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
    Computed APIx value.

    apix_value is stored as NUMERIC(10, 4) to support fractional index values
    (e.g. 121.4372) without floating-point precision issues.

    methodology_version allows us to recompute with a new methodology and
    compare versions while keeping historical values intact.
    """
    __tablename__ = "index_values"

    id = Column(Integer, primary_key=True, autoincrement=True)
    index_date = Column(Date, nullable=False, index=True)
    frequency = Column(
        String(20),
        nullable=False,
        default="daily",
        comment="daily | weekly | monthly",
    )
    variant = Column(
        String(50),
        nullable=False,
        default="overall",
        comment="overall | 7d_lead | route_BOM-DEL | etc.",
    )
    apix_value = Column(
        Numeric(10, 4),
        nullable=False,
        comment="Computed APIx (base=100 in base_year)",
    )
    methodology_version = Column(
        String(20),
        nullable=False,
        default="v1.0",
        comment="Version of the index calculation methodology",
    )
    n_obs = Column(
        Integer,
        nullable=True,
        comment="Number of fare observations used in this computation",
    )
    coverage = Column(
        Numeric(5, 4),
        nullable=True,
        comment="Fraction of expected route/lead cells represented (0.0 to 1.0)",
    )
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now_utc)

    @property
    def observation_count(self) -> int | None:
        """Backward-compatible property for n_obs."""
        return self.n_obs

    @observation_count.setter
    def observation_count(self, value: int | None):
        self.n_obs = value

    __table_args__ = (
        UniqueConstraint(
            "index_date",
            "frequency",
            "variant",
            "methodology_version",
            name="uq_index_values_key",
        ),
    )

    def __repr__(self) -> str:
        return f"<IndexValue date={self.index_date} variant={self.variant} apix={self.apix_value}>"


class RouteWeight(Base):
    """
    Weight assigned to a route in the weighted APIx calculation.

    Derived from DGCA (Directorate General of Civil Aviation) city-pair passenger traffic data.
    The sum of all active weights for a given time period equals 1.0.
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
        comment="Route weight (0-1); all active weights sum to 1.0",
    )
    valid_from = Column(
        Date,
        nullable=False,
        comment="Date from which this weight applies",
    )
    valid_to = Column(
        Date,
        nullable=True,
        comment="Date until which this weight applies (NULL = current)",
    )
    is_active = Column(Boolean, nullable=False, default=True)
    source = Column(
        Text,
        nullable=True,
        default="DGCA_City_Pair_Traffic",
        comment="Reference for the weight specification (e.g. DGCA_2024_Q4)",
    )
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now_utc)

    route = relationship("Route", back_populates="route_weights")

    @property
    def effective_date(self) -> date:
        """Backward compatibility for effective_date."""
        return self.valid_from

    @effective_date.setter
    def effective_date(self, value: date):
        self.valid_from = value

    __table_args__ = (
        UniqueConstraint("route_id", "valid_from", name="uq_route_weight_period"),
    )

    def __repr__(self) -> str:
        return f"<RouteWeight route_id={self.route_id} weight={self.weight} from={self.valid_from}>"


class LeadTimeWeight(Base):
    """
    Weight assigned to advance-purchase lead windows (e.g. T+1, T+7, T+15, T+30, T+45)
    in the multi-lead composite index calculation.
    """
    __tablename__ = "lead_time_weights"

    id = Column(Integer, primary_key=True, autoincrement=True)
    lead_days = Column(
        SmallInteger,
        nullable=False,
        index=True,
        comment="Lead time in days (1, 7, 15, 30, 45)",
    )
    weight = Column(
        Numeric(8, 6),
        nullable=False,
        comment="Lead window weight (0-1); active weights sum to 1.0",
    )
    valid_from = Column(
        Date,
        nullable=False,
        comment="Date from which this weight applies",
    )
    valid_to = Column(
        Date,
        nullable=True,
        comment="Date until which this weight applies (NULL = current)",
    )
    is_active = Column(Boolean, nullable=False, default=True)
    source = Column(
        Text,
        nullable=True,
        default="DGCA_Booking_Curve_Model",
        comment="Methodology reference for advance booking curve weights",
    )
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now_utc)

    __table_args__ = (
        UniqueConstraint("lead_days", "valid_from", name="uq_lead_time_weight_period"),
    )

    def __repr__(self) -> str:
        return f"<LeadTimeWeight lead={self.lead_days}d weight={self.weight} from={self.valid_from}>"
