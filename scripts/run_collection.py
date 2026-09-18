"""
scripts/run_collection.py
CLI entry point for running a single airfare collection job.

Usage:
    python scripts/run_collection.py
    python scripts/run_collection.py --origin BOM --destination DEL --lead-days 7
    python scripts/run_collection.py --seed 42   # reproducible run

This script orchestrates:
    1. Load config
    2. Connect to database
    3. Resolve route and travel date
    4. Run MockCollector
    5. Validate observations
    6. Store to database
    7. Print summary

It is NOT a web server — run it as a one-off job or via scheduler.
"""
import argparse
import logging
import sys
from datetime import date, timedelta
from pathlib import Path

# Ensure project root is on PYTHONPATH when run directly
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from backend.app.config import get_settings
from backend.app.database import build_engine, get_db_session
from backend.app.models import *  # ensure all models are registered with Base
from backend.app.database import Base
from scraper.collectors.mock_collector import MockCollector
from scraper.pipelines.validator import validate_observations
from scraper.pipelines.storage import (
    _get_or_create_route,
    _get_or_create_source,
    create_collection_run,
    finish_collection_run,
    store_observations,
)

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger("run_collection")


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run one airfare collection job and store to PostgreSQL."
    )
    parser.add_argument("--origin", default="BOM", help="IATA origin code (default: BOM)")
    parser.add_argument("--destination", default="DEL", help="IATA destination code (default: DEL)")
    parser.add_argument(
        "--lead-days",
        type=int,
        default=7,
        help="Days ahead of today to search for fares (default: 7)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Random seed for MockCollector (omit for random behavior)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Collect and validate but do NOT write to DB",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    args = parse_args()
    settings = get_settings()

    origin = args.origin.upper()
    destination = args.destination.upper()
    travel_date = date.today() + timedelta(days=args.lead_days)
    route_code = f"{origin}-{destination}"

    logger.info("=" * 60)
    logger.info("APIx Collection Job")
    logger.info("=" * 60)
    logger.info(f"  Route:        {route_code}")
    logger.info(f"  Travel date:  {travel_date} (T+{args.lead_days})")
    logger.info(f"  Collector:    MockCollector (seed={args.seed})")
    logger.info(f"  Dry run:      {args.dry_run}")
    logger.info("=" * 60)

    # --- Step 1: Collect ---
    collector = MockCollector(seed=args.seed)
    try:
        raw_observations = collector.collect(origin, destination, travel_date)
    except Exception as exc:
        logger.error(f"Collection failed: {exc}", exc_info=True)
        return 1

    logger.info(f"Collected {len(raw_observations)} raw observations")

    # --- Step 2: Validate ---
    valid_obs, rejected = validate_observations(raw_observations)
    logger.info(
        f"Validation: {len(valid_obs)} valid, {len(rejected)} rejected"
    )

    # Print sample observation
    if valid_obs:
        sample = valid_obs[0]
        logger.info("\nSample valid observation:")
        logger.info(f"  Airline:      {sample.airline_name} ({sample.airline_iata})")
        logger.info(f"  Flight:       {sample.flight_number}")
        logger.info(f"  Route:        {sample.origin} → {sample.destination}")
        logger.info(f"  Travel date:  {sample.travel_date}")
        logger.info(f"  Lead days:    {sample.lead_days}")
        logger.info(f"  Fare class:   {sample.fare_class}")
        logger.info(f"  Base fare:    ₹{sample.base_fare}")
        logger.info(f"  Taxes:        ₹{sample.taxes}")
        logger.info(f"  Total fare:   ₹{sample.total_fare}")
        logger.info(f"  Currency:     {sample.currency}")
        logger.info(f"  Availability: {sample.availability}")

    if args.dry_run:
        logger.info("DRY RUN — no data written to database.")
        return 0

    # --- Step 3: Store ---
    logger.info("\nConnecting to database...")
    try:
        with get_db_session() as session:
            source = _get_or_create_source(
                session,
                name=MockCollector.source_name,
                base_url=None,
            )
            route = _get_or_create_route(session, origin, destination)
            run = create_collection_run(session, source, route)

            saved, rej_count, dup_count = store_observations(
                session, valid_obs, rejected, run
            )
            finish_collection_run(
                session,
                run,
                records_found=len(raw_observations),
                records_saved=saved,
                records_rejected=rej_count + dup_count,
            )
            session.commit()

            logger.info("\n" + "=" * 60)
            logger.info("Collection Summary")
            logger.info("=" * 60)
            logger.info(f"  Run ID:         {run.id}")
            logger.info(f"  Records found:  {len(raw_observations)}")
            logger.info(f"  Records saved:  {saved}")
            logger.info(f"  Rejected:       {rej_count}")
            logger.info(f"  Duplicates:     {dup_count}")
            logger.info("=" * 60)

    except Exception as exc:
        logger.error(f"Database operation failed: {exc}", exc_info=True)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
