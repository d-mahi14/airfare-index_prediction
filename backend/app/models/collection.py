"""
backend/app/models/collection.py
CollectionRun model — records metadata for each scraper execution.

Every collection run is a unit of work: one source per run execution (with optional route context).
This provides a complete audit trail of what was collected, when, blocks, CAPTCHAs, and completion status.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from backend.app.database import Base


def _now_utc():
    return datetime.now(timezone.utc)


class CollectionRun(Base):
    """
    One execution of a collector for a source.

    Fields:
        status          -- 'running' | 'completed' | 'failed' | 'partial'
        blocked_count   -- number of HTTP 403 / IP blocks encountered
        captcha_count   -- number of CAPTCHA challenges detected
        records_found   -- total observations returned by the source
        records_saved   -- observations successfully written to DB
        records_rejected -- observations that failed validation or deduplication
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
        nullable=True,
        index=True,
    )
    status = Column(
        String(20),
        nullable=False,
        default="running",
        comment="running | completed | failed | partial",
    )
    start_time = Column(DateTime(timezone=True), nullable=False, default=_now_utc)
    end_time = Column(DateTime(timezone=True), nullable=True)
    records_found = Column(Integer, nullable=True, default=0)
    records_saved = Column(Integer, nullable=True, default=0)
    records_rejected = Column(Integer, nullable=True, default=0)
    blocked_count = Column(Integer, nullable=False, default=0, comment="Number of request blocks")
    captcha_count = Column(Integer, nullable=False, default=0, comment="Number of CAPTCHA challenges encountered")
    error_message = Column(Text, nullable=True)

    # Relationships
    source = relationship("Source", back_populates="collection_runs")
    route = relationship("Route", back_populates="collection_runs")
    observations = relationship("AirfareObservation", back_populates="collection_run")

    def __repr__(self) -> str:
        return (
            f"<CollectionRun id={str(self.id)[:8]}... "
            f"source_id={self.source_id} status={self.status} "
            f"saved={self.records_saved}>"
        )
