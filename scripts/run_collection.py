"""
scripts/run_collection.py
CLI entry point for running airfare collection jobs (Phases 7 & 8).

Usage:
    # Single route / single lead-day (default)
    python scripts/run_collection.py --origin BOM --destination DEL --lead-days 7

    # Multi-route / multi-lead collection
    python scripts/run_collection.py --routes BOM-DEL,DEL-BLR --lead-days 1,7,15

    # Full grid collection across all active routes and lead windows
    python scripts/run_collection.py --all --seed 42

    # Dry-run mode (no DB writes)
    python scripts/run_collection.py --routes BOM-DEL --lead-days 1,7 --dry-run
"""
import argparse
import logging
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import List

# Ensure project root is on sys.path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from backend.app.config import get_settings
from backend.app.database import get_db_session
from backend.app.models import *  # register all models with Base
from scraper.collectors.mock_collector import MockCollector
from scraper.grid import CollectionGrid, GridCell
from scraper.pipelines.validator import validate_observations
from scraper.pipelines.storage import (
    _get_or_create_route,
    _get_or_create_source,
    create_collection_run,
    finish_collection_run,
    store_observations,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger("run_collection")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run airfare collection jobs across routes and lead windows."
    )
    # Existing legacy flags
    parser.add_argument("--origin", default=None, help="IATA origin code (default: BOM)")
    parser.add_argument("--destination", default=None, help="IATA destination code (default: DEL)")

    # Enhanced multi-route & grid flags
    parser.add_argument(
        "--routes",
        default=None,
        help="Comma-separated route codes (e.g. BOM-DEL,DEL-BLR) or 'all'",
    )
    parser.add_argument(
        "--sources",
        default=None,
        help="Comma-separated source names (default: MockCollector)",
    )
    parser.add_argument(
        "--lead-days",
        default=None,
        help="Comma-separated lead days (e.g. 1,7,15,30,45) or single integer (default: 7)",
    )
    parser.add_argument(
        "--date",
        default=None,
        help="Collection date in YYYY-MM-DD format (default: today)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Run collection across all active routes and all lead windows",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Random seed for reproducible MockCollector generation",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Collect and validate observations without writing to PostgreSQL",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    settings = get_settings()

    # Determine collection date
    if args.date:
        try:
            collection_date = date.fromisoformat(args.date)
        except ValueError:
            logger.error(f"Invalid date format: {args.date}. Expected YYYY-MM-DD.")
            return 1
    else:
        collection_date = date.today()

    # Initialize grid generator
    grid = CollectionGrid()

    # Resolve routes and lead days
    if args.all:
        target_routes = None  # all active routes
        lead_days_list = [1, 7, 15, 30, 45]
    else:
        if args.routes:
            if args.routes.strip().lower() == "all":
                target_routes = None
            else:
                target_routes = [r.strip().upper() for r in args.routes.split(",") if r.strip()]
        elif args.origin and args.destination:
            target_routes = [f"{args.origin.strip().upper()}-{args.destination.strip().upper()}"]
        else:
            # Default fallback
            target_routes = ["BOM-DEL"]

        if args.lead_days:
            lead_days_list = [int(ld.strip()) for ld in str(args.lead_days).split(",") if ld.strip()]
        else:
            lead_days_list = [7]

    sources_list = [s.strip() for s in args.sources.split(",")] if args.sources else ["MockCollector"]

    cells: List[GridCell] = grid.generate_cells(
        collection_date=collection_date,
        routes=target_routes,
        lead_days=lead_days_list,
        sources=sources_list,
    )

    if not cells:
        logger.warning("No matching collection cells found for the specified parameters.")
        return 0

    logger.info("=" * 65)
    logger.info("APIx Airfare Collection Grid Execution")
    logger.info("=" * 65)
    logger.info(f"  Collection Date : {collection_date}")
    logger.info(f"  Total Grid Cells: {len(cells)}")
    logger.info(f"  Sources         : {', '.join(sources_list)}")
    logger.info(f"  Lead Windows    : {lead_days_list}")
    logger.info(f"  Random Seed     : {args.seed}")
    logger.info(f"  Dry Run         : {args.dry_run}")
    logger.info("=" * 65)

    collector = MockCollector(seed=args.seed)

    total_collected = 0
    total_valid = 0
    total_rejected = 0
    total_saved = 0
    total_duplicates = 0

    for idx, cell in enumerate(cells, 1):
        logger.info(
            f"[{idx}/{len(cells)}] Collecting {cell.route_code} (T+{cell.lead_days} -> travel_date={cell.travel_date})"
        )

        try:
            raw_obs = collector.collect(
                origin=cell.origin,
                destination=cell.destination,
                travel_date=cell.travel_date,
            )
        except Exception as exc:
            logger.error(f"Failed collection for cell {cell.cell_key}: {exc}", exc_info=True)
            continue

        total_collected += len(raw_obs)
        valid_obs, rejected_tuples = validate_observations(raw_obs)
        total_valid += len(valid_obs)
        total_rejected += len(rejected_tuples)

        if not args.dry_run:
            with get_db_session() as session:
                source_obj = _get_or_create_source(session, collector.source_name)
                route_obj = _get_or_create_route(session, cell.origin, cell.destination)

                run_obj = create_collection_run(
                    session=session,
                    source=source_obj,
                    route=route_obj,
                )

                saved_cnt, rej_cnt, dup_cnt = store_observations(
                    session=session,
                    observations=valid_obs,
                    rejected=rejected_tuples,
                    run=run_obj,
                )

                finish_collection_run(
                    session=session,
                    run=run_obj,
                    records_found=len(raw_obs),
                    records_saved=saved_cnt,
                    records_rejected=rej_cnt,
                )

                total_saved += saved_cnt
                total_duplicates += dup_cnt

    logger.info("=" * 65)
    logger.info("Collection Summary:")
    logger.info(f"  Grid Cells Executed: {len(cells)}")
    logger.info(f"  Total Quotes Found : {total_collected}")
    logger.info(f"  Valid Quotes       : {total_valid}")
    logger.info(f"  Rejected Quotes    : {total_rejected}")
    if not args.dry_run:
        logger.info(f"  Persisted to DB    : {total_saved}")
        logger.info(f"  Duplicates Skipped : {total_duplicates}")
    logger.info("=" * 65)

    return 0


if __name__ == "__main__":
    sys.exit(main())
