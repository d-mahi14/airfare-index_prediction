"""
backend/app/models/collection.py
CollectionRun model — records metadata for each scraper execution.

Every collection run is a unit of work: one source × one route × one timestamp.
This provides a complete audit trail of what was collected, when, and how it went.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    SmallInteger,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from backend.app.database import Base


def _now_utc():
    return datetime.now(timezone.utc)


class CollectionRun(Base):
    """
    One execution of a collector for a specific source × route combination.

    Fields:
        records_found   -- total observations returned by the source
        records_saved   -- observations successfully written to DB
        records_rejected -- observations that failed validation
        error_message   -- set if the run itself failed (not per-record errors)
    """
    __tablename__ = "collection_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
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
    start_time = Column(DateTime(timezone=True), nullable=False, default=_now_utc)
    end_time = Column(DateTime(timezone=True), nullable=True)
    records_found = Column(Integer, nullable=True, default=0)
    records_saved = Column(Integer, nullable=True, default=0)
    records_rejected = Column(Integer, nullable=True, default=0)
    error_message = Column(Text, nullable=True)

    # Relationships
    source = relationship("Source", back_populates="collection_runs")
    route = relationship("Route", back_populates="collection_runs")
    observations = relationship("AirfareObservation", back_populates="collection_run")

    def __repr__(self) -> str:
        return (
            f"<CollectionRun id={str(self.id)[:8]}... "
            f"source_id={self.source_id} route_id={self.route_id} "
            f"saved={self.records_saved}>"
        )
