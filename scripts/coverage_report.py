"""
scripts/coverage_report.py
Coverage and reliability audit reporting tool for APIx airfare collection.

Generates structured reports over a sliding window (default: last 7 days):
  - Per Source x Route x Lead Window matrix
  - Overall Source Summary
  - Success Rate (% of scheduled observation days populated)
  - Sold-Out Share (% of quotes with no seats available)
  - Block Count & CAPTCHA Count (from collection_runs)

Usage:
  python -m scripts.coverage_report
  python -m scripts.coverage_report --days 7
  python -m scripts.coverage_report --source EaseMyTrip --format markdown
  python -m scripts.coverage_report --json
"""
import argparse
from datetime import date, datetime, timedelta, timezone
import json
import logging
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from backend.app.database import get_db_session
from backend.app.models.airfare import AirfareObservation, Route, Source
from backend.app.models.collection import CollectionRun
from scraper.grid import CollectionGrid

KOLKATA_TZ = ZoneInfo("Asia/Kolkata")
logger = logging.getLogger("coverage_report")


def calculate_coverage_metrics(
    session: Session,
    days: int = 7,
    source_name: Optional[str] = None,
    route_code: Optional[str] = None,
    as_of_date: Optional[date] = None,
) -> Dict[str, Any]:
    """
    Calculate grid coverage, success rates, sold-out shares, and block counts.
    """
    end_date = as_of_date or datetime.now(timezone.utc).astimezone(KOLKATA_TZ).date()
    start_date = end_date - timedelta(days=days - 1)

    # 1. Query CollectionRuns for blocks and captchas
    runs_query = session.query(
        Source.name.label("source_name"),
        func.count(CollectionRun.id).label("total_runs"),
        func.sum(CollectionRun.blocked_count).label("total_blocks"),
        func.sum(CollectionRun.captcha_count).label("total_captchas"),
        func.sum(CollectionRun.records_saved).label("total_saved"),
    ).join(Source, CollectionRun.source_id == Source.id).filter(
        func.date(CollectionRun.start_time) >= start_date,
        func.date(CollectionRun.start_time) <= end_date,
    )
    if source_name:
        runs_query = runs_query.filter(Source.name.ilike(source_name))
    runs_stats = runs_query.group_by(Source.name).all()

    source_run_metrics: Dict[str, Dict[str, Any]] = {}
    for r in runs_stats:
        source_run_metrics[r.source_name] = {
            "total_runs": int(r.total_runs or 0),
            "total_blocks": int(r.total_blocks or 0),
            "total_captchas": int(r.total_captchas or 0),
            "total_saved": int(r.total_saved or 0),
        }

    # 2. Query AirfareObservations for cell metrics (source x route x target_lead_window)
    obs_query = session.query(
        Source.name.label("source_name"),
        Route.route_code.label("route_code"),
        AirfareObservation.target_lead_window.label("lead_window"),
        func.count(AirfareObservation.id).label("total_quotes"),
        func.count(func.distinct(AirfareObservation.collection_date)).label("distinct_days_collected"),
        func.sum(
            case((AirfareObservation.is_sold_out.is_(True), 1), else_=0)
        ).label("sold_out_count"),
        func.sum(
            case((AirfareObservation.status == "valid", 1), else_=0)
        ).label("valid_count"),
    ).join(
        Source, AirfareObservation.source_id == Source.id
    ).join(
        Route, AirfareObservation.route_id == Route.id
    ).filter(
        AirfareObservation.collection_date >= start_date,
        AirfareObservation.collection_date <= end_date,
    )

    if source_name:
        obs_query = obs_query.filter(Source.name.ilike(source_name))
    if route_code:
        obs_query = obs_query.filter(Route.route_code == route_code)

    obs_stats = obs_query.group_by(
        Source.name,
        Route.route_code,
        AirfareObservation.target_lead_window,
    ).all()

    # Build cell matrix breakdown
    cell_records: List[Dict[str, Any]] = []
    total_quotes_all = 0
    total_sold_out_all = 0
    total_valid_all = 0

    for row in obs_stats:
        s_name = row.source_name
        r_code = row.route_code
        lead_w = row.lead_window or 0
        total_q = int(row.total_quotes or 0)
        days_collected = int(row.distinct_days_collected or 0)
        sold_out_q = int(row.sold_out_count or 0)
        valid_q = int(row.valid_count or 0)

        total_quotes_all += total_q
        total_sold_out_all += sold_out_q
        total_valid_all += valid_q

        success_rate_pct = round((days_collected / max(1, days)) * 100.0, 2)
        sold_out_share_pct = round((sold_out_q / max(1, total_q)) * 100.0, 2) if total_q > 0 else 0.0

        cell_records.append({
            "source": s_name,
            "route": r_code,
            "lead_window": f"T+{lead_w}",
            "days_collected": days_collected,
            "window_days": days,
            "success_rate_pct": success_rate_pct,
            "total_quotes": total_q,
            "valid_quotes": valid_q,
            "sold_out_quotes": sold_out_q,
            "sold_out_share_pct": sold_out_share_pct,
        })

    # Sort records by source, route, lead_window
    cell_records.sort(key=lambda x: (x["source"], x["route"], x["lead_window"]))

    overall_success_rate = round(
        (sum(c["days_collected"] for c in cell_records) / max(1, len(cell_records) * days)) * 100.0, 2
    ) if cell_records else 0.0

    overall_sold_out_share = round(
        (total_sold_out_all / max(1, total_quotes_all)) * 100.0, 2
    ) if total_quotes_all > 0 else 0.0

    return {
        "report_period": {
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "days": days,
        },
        "summary": {
            "total_cell_records": len(cell_records),
            "total_quotes": total_quotes_all,
            "total_valid_quotes": total_valid_all,
            "total_sold_out_quotes": total_sold_out_all,
            "overall_success_rate_pct": overall_success_rate,
            "overall_sold_out_share_pct": overall_sold_out_share,
        },
        "sources": source_run_metrics,
        "cells": cell_records,
    }


def render_report_table(report: Dict[str, Any]) -> str:
    """Format coverage metrics as a clean, human-readable ASCII table."""
    period = report["report_period"]
    summary = report["summary"]
    sources = report["sources"]
    cells = report["cells"]

    lines = []
    lines.append("=" * 85)
    lines.append(f" APIx Airfare Collection Coverage Report ({period['start_date']} to {period['end_date']} - {period['days']} Days)")
    lines.append("=" * 85)
    lines.append(
        f" Total Quotes: {summary['total_quotes']} | Valid: {summary['total_valid_quotes']} | "
        f"Overall Success Rate: {summary['overall_success_rate_pct']}% | Sold-Out Share: {summary['overall_sold_out_share_pct']}%"
    )
    lines.append("-" * 85)

    # 1. Source Summary
    lines.append("\n[1] Source Operational & Block Summary:")
    lines.append(f"{'Source Name':<20} | {'Runs':<6} | {'Saved Quotes':<14} | {'Blocks':<8} | {'CAPTCHAs':<9}")
    lines.append("-" * 68)
    if sources:
        for s_name, s_stat in sources.items():
            lines.append(
                f"{s_name:<20} | {s_stat['total_runs']:<6} | {s_stat['total_saved']:<14} | "
                f"{s_stat['total_blocks']:<8} | {s_stat['total_captchas']:<9}"
            )
    else:
        lines.append(" No collection runs recorded in this time window.")

    # 2. Detailed Grid Cell Coverage
    lines.append("\n[2] Grid Cell Breakdown (Source x Route x Lead Window):")
    lines.append(
        f"{'Source':<16} | {'Route':<9} | {'Lead':<6} | {'Days':<6} | {'Success Rate':<14} | {'Quotes':<8} | {'Sold-Out %':<12}"
    )
    lines.append("-" * 85)

    if cells:
        for c in cells:
            lines.append(
                f"{c['source']:<16} | {c['route']:<9} | {c['lead_window']:<6} | "
                f"{c['days_collected']}/{c['window_days']:<4} | {c['success_rate_pct']:>6.1f}%        | "
                f"{c['total_quotes']:<8} | {c['sold_out_share_pct']:>6.1f}%"
            )
    else:
        lines.append(" No cell observations found for the specified filters.")

    lines.append("=" * 85)
    return "\n".join(lines)


def render_report_markdown(report: Dict[str, Any]) -> str:
    """Format coverage metrics as a Markdown document."""
    period = report["report_period"]
    summary = report["summary"]
    sources = report["sources"]
    cells = report["cells"]

    lines = []
    lines.append(f"# APIx Collection Coverage Report ({period['start_date']} to {period['end_date']})")
    lines.append(f"\n- **Report Duration**: {period['days']} days")
    lines.append(f"- **Total Quotes**: {summary['total_quotes']}")
    lines.append(f"- **Overall Success Rate**: {summary['overall_success_rate_pct']}%")
    lines.append(f"- **Sold-Out Share**: {summary['overall_sold_out_share_pct']}%\n")

    lines.append("## Source Summary Table\n")
    lines.append("| Source | Runs | Saved Quotes | Blocks Encountered | CAPTCHAs |")
    lines.append("| :--- | :--- | :--- | :--- | :--- |")
    for s_name, s_stat in sources.items():
        lines.append(
            f"| **{s_name}** | {s_stat['total_runs']} | {s_stat['total_saved']} | "
            f"{s_stat['total_blocks']} | {s_stat['total_captchas']} |"
        )

    lines.append("\n## Grid Cell Coverage Breakdown\n")
    lines.append("| Source | Route | Lead Window | Days Collected | Success Rate | Total Quotes | Sold-Out Share |")
    lines.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
    for c in cells:
        lines.append(
            f"| {c['source']} | {c['route']} | {c['lead_window']} | {c['days_collected']}/{c['window_days']} | "
            f"{c['success_rate_pct']}% | {c['total_quotes']} | {c['sold_out_share_pct']}% |"
        )

    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate coverage and reliability reports for APIx airfare collection."
    )
    parser.add_argument("--days", type=int, default=7, help="Number of past days to analyze (default: 7)")
    parser.add_argument("--source", default=None, help="Filter report by source name")
    parser.add_argument("--route", default=None, help="Filter report by route code (e.g. BOM-DEL)")
    parser.add_argument("--format", choices=["table", "json", "markdown"], default="table", help="Output format")
    parser.add_argument("--json", action="store_true", help="Shortcut for --format json")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    fmt = "json" if args.json else args.format

    with get_db_session() as session:
        report = calculate_coverage_metrics(
            session=session,
            days=args.days,
            source_name=args.source,
            route_code=args.route,
        )

    if fmt == "json":
        print(json.dumps(report, indent=2))
    elif fmt == "markdown":
        print(render_report_markdown(report))
    else:
        print(render_report_table(report))

    return 0


if __name__ == "__main__":
    sys.exit(main())
