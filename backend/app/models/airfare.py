"""
backend/app/models/airfare.py
Core airfare domain ORM models.

Design notes:
- NUMERIC(10, 2) is used for all monetary fields (never FLOAT).
- UUIDs are used as primary keys for distributed-safe IDs.
- lead_days is stored (not computed on query) for efficient filtering.
- status + rejection_reason support the "never silently discard" policy.
- raw_reference stores a filesystem path to the raw collected content.
"""
import uuid
from datetime import date, datetime, timezone

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
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
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from backend.app.database import Base


def _now_utc():
    return datetime.now(timezone.utc)


class Route(Base):
    """
    An origin → destination route pair.
    route_code is the canonical key, e.g. 'BOM-DEL'.
    """
    __tablename__ = "routes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    origin = Column(String(3), nullable=False, comment="IATA airport code")
    destination = Column(String(3), nullable=False, comment="IATA airport code")
    route_code = Column(String(8), nullable=False, unique=True, comment="e.g. BOM-DEL")
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now_utc)

    observations = relationship("AirfareObservation", back_populates="route")
    collection_runs = relationship("CollectionRun", back_populates="route")
    route_weights = relationship("RouteWeight", back_populates="route")

    __table_args__ = (
        UniqueConstraint("origin", "destination", name="uq_route_origin_destination"),
    )

    def __repr__(self) -> str:
        return f"<Route {self.route_code}>"


class Airline(Base):
    """
    An airline operator. iata_code may be None for charter/unknown.
    """
    __tablename__ = "airlines"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False, unique=True)
    iata_code = Column(String(2), nullable=True, comment="2-letter IATA code")
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now_utc)

    observations = relationship("AirfareObservation", back_populates="airline")

    def __repr__(self) -> str:
        return f"<Airline {self.name} ({self.iata_code})>"


class Source(Base):
    """
    A data collection source (airline website, OTA, etc.).
    """
    __tablename__ = "sources"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False, unique=True, comment="e.g. MockCollector, IndiGo")
    base_url = Column(Text, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now_utc)

    observations = relationship("AirfareObservation", back_populates="source")
    collection_runs = relationship("CollectionRun", back_populates="source")

    def __repr__(self) -> str:
        return f"<Source {self.name}>"


class AirfareObservation(Base):
    """
    One airfare quote observed from a source at a point in time.

    Status lifecycle:
        'raw'      → freshly collected, not yet validated
        'valid'    → passed all validation checks
        'rejected' → failed validation; rejection_reason is set
        'duplicate'→ identified as a duplicate of an earlier record

    Monetary fields use NUMERIC(10, 2) — never float — to avoid
    rounding errors in index arithmetic.
    """
    __tablename__ = "airfare_observations"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        comment="UUID primary key — safe for distributed inserts",
    )
    collection_run_id = Column(
        UUID(as_uuid=True),
        ForeignKey("collection_runs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    collection_timestamp = Column(
        DateTime(timezone=True),
        nullable=False,
        default=_now_utc,
        index=True,
        comment="When this quote was collected",
    )
    source_id = Column(
        Integer,
        ForeignKey("sources.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    route_id = Column(
        Integer,
        ForeignKey("routes.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    airline_id = Column(
        Integer,
        ForeignKey("airlines.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    flight_number = Column(String(20), nullable=True)
    travel_date = Column(Date, nullable=False, index=True)
    lead_days = Column(
        SmallInteger,
        nullable=False,
        comment="travel_date - collection_date in days",
    )
    fare_class = Column(
        String(50),
        nullable=False,
        default="Economy",
        comment="e.g. Economy, Business, First",
    )
    base_fare = Column(
        Numeric(10, 2),
        nullable=True,
        comment="Fare before taxes/fees, in INR",
    )
    taxes = Column(Numeric(10, 2), nullable=True, default=0)
    fees = Column(Numeric(10, 2), nullable=True, default=0)
    total_fare = Column(
        Numeric(10, 2),
        nullable=False,
        comment="Total payable fare in INR",
    )
    currency = Column(String(3), nullable=False, default="INR")
    availability = Column(
        String(20),
        nullable=True,
        default="available",
        comment="available | sold_out | cancelled | unknown",
    )
    status = Column(
        String(20),
        nullable=False,
        default="raw",
        index=True,
        comment="raw | valid | rejected | duplicate",
    )
    rejection_reason = Column(
        Text,
        nullable=True,
        comment="Human-readable reason if status=rejected",
    )
    raw_reference = Column(
        Text,
        nullable=True,
        comment="Path to raw collected file for reproducibility",
    )
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=_now_utc,
    )

    # Relationships
    source = relationship("Source", back_populates="observations")
    route = relationship("Route", back_populates="observations")
    airline = relationship("Airline", back_populates="observations")
    collection_run = relationship("CollectionRun", back_populates="observations")

    __table_args__ = (
        # total_fare must be non-negative
        CheckConstraint("total_fare >= 0", name="ck_total_fare_non_negative"),
        # base_fare, if present, must be <= total_fare
        CheckConstraint(
            "base_fare IS NULL OR base_fare <= total_fare",
            name="ck_base_fare_lte_total",
        ),
        # lead_days must be >= 0 (collection date <= travel date)
        CheckConstraint("lead_days >= 0", name="ck_lead_days_non_negative"),
    )

    def __repr__(self) -> str:
        return (
            f"<AirfareObservation route_id={self.route_id} "
            f"travel_date={self.travel_date} "
            f"total_fare={self.total_fare} status={self.status}>"
        )
