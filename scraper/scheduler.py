"""
scraper/scheduler.py
APScheduler background daemon for scheduled daily airfare collection.

Features:
  - Schedules daily collection jobs in Asia/Kolkata timezone.
  - Supports cron expressions from config/collection.yaml.
  - Supports continuous daemon execution or background scheduler integration.
"""
from datetime import datetime
import logging
import signal
import sys
import time
from zoneinfo import ZoneInfo
from typing import Any, Dict, Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from scripts.daily_collection import load_collection_config, run_daily_collection

logger = logging.getLogger("apix_scheduler")
KOLKATA_TZ = ZoneInfo("Asia/Kolkata")


def create_scheduler(
    blocking: bool = True,
    config: Optional[Dict[str, Any]] = None,
) -> BlockingScheduler | BackgroundScheduler:
    """
    Instantiate and configure an APScheduler instance for APIx daily collection.
    """
    cfg = config or load_collection_config()
    sched_cfg = cfg.get("scheduler", {})
    cron_expr = sched_cfg.get("cron_expression", "0 2 * * *")
    tz_str = sched_cfg.get("timezone", "Asia/Kolkata")
    timezone_obj = ZoneInfo(tz_str)

    # Parse cron expression: minute hour day month day_of_week
    parts = cron_expr.split()
    if len(parts) != 5:
        minute, hour = "0", "2"
        day, month, day_of_week = "*", "*", "*"
    else:
        minute, hour, day, month, day_of_week = parts

    trigger = CronTrigger(
        minute=minute,
        hour=hour,
        day=day,
        month=month,
        day_of_week=day_of_week,
        timezone=timezone_obj,
    )

    scheduler_cls = BlockingScheduler if blocking else BackgroundScheduler
    scheduler = scheduler_cls(timezone=timezone_obj)

    scheduler.add_job(
        func=run_daily_collection,
        trigger=trigger,
        id="apix_daily_collection",
        name="APIx Daily Airfare Collection Job",
        replace_existing=True,
    )

    logger.info(
        f"Configured APScheduler daily job with trigger '{cron_expr}' ({tz_str})."
    )
    return scheduler


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    logger.info("Starting APIx Collection Scheduler Daemon...")

    scheduler = create_scheduler(blocking=True)

    def handle_signal(sig, frame):
        logger.info("Shutdown signal received. Stopping scheduler...")
        scheduler.shutdown(wait=False)
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler daemon terminated.")


if __name__ == "__main__":
    main()
