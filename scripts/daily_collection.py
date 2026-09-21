"""
scripts/daily_collection.py
Scheduled, resilient daily collection orchestrator for APIx.

Key features:
  1. Creates exactly ONE collection_runs row per source per daily run.
  2. Enforces strict mode isolation (mock and real data never mix in one run).
  3. Integrated Circuit Breaker per source (trips after N consecutive blocks).
  4. Fully idempotent database writes (zero duplicate observations inserted on re-runs).
  5. Config-driven source selection and lead-window execution in Asia/Kolkata timezone.
"""
import argparse
from datetime import date, datetime, timezone
import logging
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo
import yaml

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.database import get_db_session
from backend.app.models import *  # ensure all models are registered
from compliance.registry import SourceRegistry
from scraper.base import BlockedResult
from scraper.collectors import (
    EaseMyTripCollector,
    IndiGoCollector,
    MakeMyTripCollector,
    MockCollector,
    RecordedCollector,
)
from scraper.framework.circuit_breaker import CircuitBreaker, CircuitBreakerConfig
from scraper.grid import CollectionGrid, GridCell
from scraper.pipelines.storage import (
    _get_or_create_source,
    create_collection_run,
    finish_collection_run,
    store_observations,
)
from scraper.pipelines.validator import validate_observations

KOLKATA_TZ = ZoneInfo("Asia/Kolkata")
DEFAULT_COLLECTION_YAML = PROJECT_ROOT / "config" / "collection.yaml"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger("daily_collection")


def load_collection_config(config_path: Optional[Path | str] = None) -> Dict[str, Any]:
    """Load collection and scheduling YAML configuration."""
    cfg_file = Path(config_path) if config_path else DEFAULT_COLLECTION_YAML
    if not cfg_file.exists():
        return {}
    with open(cfg_file, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def validate_mode_isolation(sources: List[str]) -> str:
    """
    Validate that mock and real/recorded sources do not mix in a single run.
    Returns the resolved mode ('mock' or 'recorded').
    """
    has_mock = any(s.lower() in ("mockcollector", "mock") for s in sources)
    has_real = any(s.lower() not in ("mockcollector", "mock") for s in sources)

    if has_mock and has_real:
        raise ValueError(
            "Strict mode isolation error: Cannot mix synthetic MockCollector and "
            f"real/recorded sources in a single collection run. Sources provided: {sources}"
        )

    return "mock" if has_mock else "recorded"


def run_daily_collection(
    collection_date: Optional[date] = None,
    mode: Optional[str] = None,
    sources: Optional[List[str]] = None,
    routes: Optional[List[str]] = None,
    lead_days: Optional[List[int]] = None,
    seed: Optional[int] = None,
    dry_run: bool = False,
    circuit_breakers: Optional[Dict[str, CircuitBreaker]] = None,
    config_path: Optional[Path | str] = None,
    session: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    Execute a resilient, scheduled daily collection run.
    Writes exactly ONE collection_runs record per source.
    """
    config = load_collection_config(config_path)
    grid_cfg = config.get("grid", {})
    cb_cfg_dict = config.get("circuit_breaker", {})

    cb_config = CircuitBreakerConfig(
        failure_threshold=cb_cfg_dict.get("failure_threshold", 3),
        cooldown_seconds=cb_cfg_dict.get("cooldown_seconds", 300),
    )

    # Determine collection date (Asia/Kolkata)
    if collection_date is None:
        collection_date = datetime.now(timezone.utc).astimezone(KOLKATA_TZ).date()

    # Resolve sources
    if sources is None:
        if mode == "recorded":
            # In recorded mode, default to active compliant recorded sources
            sources = ["EaseMyTrip"]
        else:
            sources = grid_cfg.get("default_sources", ["MockCollector"])

    # Strict mode isolation check
    resolved_mode = validate_mode_isolation(sources)
    if mode is not None and mode != resolved_mode:
        raise ValueError(
            f"Requested mode '{mode}' conflicts with provided sources {sources} (resolved mode: '{resolved_mode}')"
        )

    # Resolve lead windows and routes
    lead_windows = lead_days or grid_cfg.get("lead_days", [1, 7, 15, 30, 45])
    target_routes = routes  # None means all active routes from routes_config

    grid = CollectionGrid(
        config_path=config_path,
        routes_config_path=grid_cfg.get("routes_config"),
    )

    cb_map = circuit_breakers if circuit_breakers is not None else {}

    summary: Dict[str, Any] = {
        "collection_date": collection_date.isoformat(),
        "mode": resolved_mode,
        "dry_run": dry_run,
        "sources": {},
        "total_cells_attempted": 0,
        "total_cells_succeeded": 0,
        "total_records_saved": 0,
        "total_duplicates_skipped": 0,
        "total_blocked_count": 0,
        "total_captcha_count": 0,
    }

    logger.info("=" * 70)
    logger.info("APIx Scheduled Daily Collection Run")
    logger.info("=" * 70)
    logger.info(f"  Collection Date : {collection_date} (Asia/Kolkata)")
    logger.info(f"  Execution Mode  : {resolved_mode}")
    logger.info(f"  Sources         : {', '.join(sources)}")
    logger.info(f"  Lead Windows    : {lead_windows}")
    logger.info(f"  Dry Run         : {dry_run}")
    logger.info("=" * 70)

    # Process one source at a time -> ONE collection_runs row per source
    for source_name in sources:
        logger.info(f"\n>>> Starting collection for source: {source_name}")

        # Setup or get circuit breaker for this source
        if source_name not in cb_map:
            cb_map[source_name] = CircuitBreaker(source_name=source_name, config=cb_config)
        circuit_breaker = cb_map[source_name]

        # Instantiate appropriate collector
        if resolved_mode == "mock":
            collector = MockCollector(seed=seed)
        elif source_name.lower() == "indigo":
            collector = IndiGoCollector(enforce_robots=True, is_synthetic=False)
        elif source_name.lower() in ("makemytrip", "mmt"):
            collector = MakeMyTripCollector(enforce_robots=True, is_synthetic=False)
        elif source_name.lower() == "easemytrip":
            collector = EaseMyTripCollector(enforce_robots=True, is_synthetic=False)
        else:
            collector = RecordedCollector(source_name=source_name, enforce_robots=True, is_synthetic=False)

        # Generate grid cells for this source
        cells = grid.generate_cells(
            collection_date=collection_date,
            routes=target_routes,
            lead_days=lead_windows,
            sources=[source_name],
        )

        source_stats = {
            "attempted_cells": len(cells),
            "succeeded_cells": 0,
            "blocked_cells": 0,
            "records_found": 0,
            "records_saved": 0,
            "records_rejected": 0,
            "duplicates_skipped": 0,
            "blocked_count": 0,
            "captcha_count": 0,
            "circuit_state": circuit_breaker.state.value,
        }

        # Create one collection_runs row for this source
        run_record = None
        db_session_obj = None
        effective_session = None

        if not dry_run:
            if session is not None:
                effective_session = session
            else:
                db_session_obj = get_db_session()
                effective_session = db_session_obj.__enter__()

            source_orm = _get_or_create_source(effective_session, name=collector.source_name)
            run_record = create_collection_run(effective_session, source=source_orm, route=None)

        try:
            for idx, cell in enumerate(cells, 1):
                # Check Circuit Breaker before executing cell
                if not circuit_breaker.allow_request():
                    source_stats["blocked_cells"] += 1
                    source_stats["blocked_count"] += 1
                    logger.warning(
                        f"[{idx}/{len(cells)}] SKIPPED cell {cell.cell_key}: "
                        f"Circuit breaker for {source_name} is OPEN (Reason: {circuit_breaker.last_trip_reason})"
                    )
                    continue

                try:
                    raw_obs = collector.collect(
                        origin=cell.origin,
                        destination=cell.destination,
                        travel_date=cell.travel_date,
                    )
                except Exception as exc:
                    logger.error(f"Error collecting cell {cell.cell_key}: {exc}")
                    source_stats["blocked_count"] += 1
                    circuit_breaker.record_block(reason=str(exc), block_type="exception")
                    continue

                if not raw_obs:
                    # Could be empty or blocked
                    source_stats["blocked_cells"] += 1
                    continue

                # Validation & deduplication
                source_stats["records_found"] += len(raw_obs)
                valid_obs, rejected_tuples = validate_observations(raw_obs)
                source_stats["records_rejected"] += len(rejected_tuples)

                if valid_obs:
                    circuit_breaker.record_success()
                    source_stats["succeeded_cells"] += 1

                if not dry_run and effective_session and run_record:
                    saved_cnt, rej_cnt, dup_cnt = store_observations(
                        session=effective_session,
                        observations=valid_obs,
                        rejected=rejected_tuples,
                        run=run_record,
                    )
                    source_stats["records_saved"] += saved_cnt
                    source_stats["duplicates_skipped"] += dup_cnt
                else:
                    source_stats["records_saved"] += len(valid_obs)

            # Finish CollectionRun record
            if not dry_run and effective_session and run_record:
                status_str = "completed" if source_stats["succeeded_cells"] > 0 else "failed"
                if circuit_breaker.state.value == "OPEN":
                    status_str = "blocked"
                finish_collection_run(
                    session=effective_session,
                    run=run_record,
                    records_found=source_stats["records_found"],
                    records_saved=source_stats["records_saved"],
                    records_rejected=source_stats["records_rejected"],
                    blocked_count=source_stats["blocked_count"],
                    captcha_count=source_stats["captcha_count"],
                    status=status_str,
                    error_message=circuit_breaker.last_trip_reason if circuit_breaker.state.value == "OPEN" else None,
                )

        finally:
            if db_session_obj:
                db_session_obj.__exit__(None, None, None)

        source_stats["circuit_state"] = circuit_breaker.state.value
        summary["sources"][source_name] = source_stats
        summary["total_cells_attempted"] += source_stats["attempted_cells"]
        summary["total_cells_succeeded"] += source_stats["succeeded_cells"]
        summary["total_records_saved"] += source_stats["records_saved"]
        summary["total_duplicates_skipped"] += source_stats["duplicates_skipped"]
        summary["total_blocked_count"] += source_stats["blocked_count"]
        summary["total_captcha_count"] += source_stats["captcha_count"]

    logger.info("\n" + "=" * 70)
    logger.info("Daily Collection Summary:")
    logger.info(f"  Attempted Cells   : {summary['total_cells_attempted']}")
    logger.info(f"  Succeeded Cells   : {summary['total_cells_succeeded']}")
    logger.info(f"  Records Saved     : {summary['total_records_saved']}")
    logger.info(f"  Duplicates Skipped: {summary['total_duplicates_skipped']}")
    logger.info(f"  Blocks / Skipped  : {summary['total_blocked_count']}")
    logger.info("=" * 70)

    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="APIx Scheduled Resilient Daily Collection CLI entry point."
    )
    parser.add_argument("--date", default=None, help="Collection date YYYY-MM-DD (default: today)")
    parser.add_argument("--mode", default=None, choices=["mock", "recorded"], help="Collection mode (mock | recorded)")
    parser.add_argument("--sources", default=None, help="Comma-separated source names")
    parser.add_argument("--routes", default=None, help="Comma-separated route codes (e.g. BOM-DEL,DEL-BLR)")
    parser.add_argument("--lead-days", default=None, help="Comma-separated lead days (e.g. 1,7,15,30,45)")
    parser.add_argument("--seed", type=int, default=None, help="Random seed for mock generation")
    parser.add_argument("--dry-run", action="store_true", help="Collect without DB persistence")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    col_date = date.fromisoformat(args.date) if args.date else None
    sources_list = [s.strip() for s in args.sources.split(",")] if args.sources else None
    routes_list = [r.strip().upper() for r in args.routes.split(",")] if args.routes else None
    lead_list = [int(ld.strip()) for ld in str(args.lead_days).split(",")] if args.lead_days else None

    try:
        summary = run_daily_collection(
            collection_date=col_date,
            mode=args.mode,
            sources=sources_list,
            routes=routes_list,
            lead_days=lead_list,
            seed=args.seed,
            dry_run=args.dry_run,
        )
        is_success = (
            summary["total_records_saved"] > 0
            or summary["total_duplicates_skipped"] > 0
            or summary["total_cells_succeeded"] > 0
            or args.dry_run
        )
        return 0 if is_success else 1
    except Exception as exc:
        logger.critical(f"Daily collection run failed unrecoverably: {exc}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
