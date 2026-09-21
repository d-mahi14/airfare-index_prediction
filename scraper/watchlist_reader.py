"""
scraper/watchlist_reader.py
Reads high-frequency requested routes from route_watchlist and checks collection permissions.

Ensures that candidate watchlist routes are only scheduled for collection on sources whose
collection_mode explicitly permits it (e.g. live_scrape or official_api with human ToS review).
When all sources operate in recorded_fixture mode, records a compliance notice and prevents live scraping.
"""
from datetime import datetime, timezone
import logging
from typing import Any, Dict, List, Optional
from sqlalchemy.orm import Session

from backend.app.models.watchlist import RouteWatchlist
from compliance.registry import SourceRegistry

logger = logging.getLogger(__name__)


def get_watchlist_candidates(
    session: Session,
    min_requests: int = 1,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """
    Query top requested uncovered routes from route_watchlist.
    """
    entries = (
        session.query(RouteWatchlist)
        .filter(RouteWatchlist.request_count >= min_requests)
        .order_by(RouteWatchlist.request_count.desc(), RouteWatchlist.last_requested_at.desc())
        .limit(limit)
        .all()
    )

    candidates: List[Dict[str, Any]] = []
    for e in entries:
        candidates.append({
            "route_code": e.route_code,
            "origin": e.origin,
            "destination": e.destination,
            "request_count": e.request_count,
            "first_requested_at": e.first_requested_at.isoformat() if e.first_requested_at else None,
            "last_requested_at": e.last_requested_at.isoformat() if e.last_requested_at else None,
        })
    return candidates


def evaluate_watchlist_collection_eligibility(
    session: Session,
    registry: Optional[SourceRegistry] = None,
    min_requests: int = 1,
) -> Dict[str, Any]:
    """
    Evaluate candidate routes against source compliance policies.
    """
    source_reg = registry or SourceRegistry()
    sources = source_reg.list_sources()

    live_sources = [s.name for s in sources if s.collection_mode in ("live_scrape", "official_api")]
    candidates = get_watchlist_candidates(session=session, min_requests=min_requests)

    can_collect_live = len(live_sources) > 0

    if not can_collect_live:
        compliance_notice = (
            "No active sources permitted for live collection. "
            "All sources currently operate in recorded_fixture mode per docs/COMPLIANCE.md."
        )
    else:
        compliance_notice = f"Live collection permitted on: {', '.join(live_sources)}"

    return {
        "candidate_count": len(candidates),
        "candidates": candidates,
        "eligible_for_live_collection": can_collect_live,
        "permitted_live_sources": live_sources,
        "compliance_notice": compliance_notice,
    }
