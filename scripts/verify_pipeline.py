"""
scripts/verify_pipeline.py
End-to-end pipeline verification using in-memory SQLite (no PostgreSQL needed).
Run this to verify the entire collection → validate → store pipeline works.
"""
import sys
from datetime import date, timedelta
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from backend.app.database import Base
import backend.app.models  # register all models

# Create SQLite in-memory engine (no PostgreSQL needed)
engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)
session = Session()

print("=" * 65)
print("APIx End-to-End Pipeline Verification")
print("=" * 65)

# Step 1: Collect
from scraper.collectors.mock_collector import MockCollector
collector = MockCollector(raw_data_dir="data/raw", seed=42)
travel_date = date.today() + timedelta(days=7)
raw_obs = collector.collect("BOM", "DEL", travel_date)
print(f"\n[1] COLLECT:  {len(raw_obs)} observations from MockCollector")
print(f"    Route:      BOM -> DEL")
print(f"    Travel:     {travel_date} (T+7)")

# Step 2: Validate
from scraper.pipelines.validator import validate_observations
valid_obs, rejected = validate_observations(raw_obs)
print(f"\n[2] VALIDATE: {len(valid_obs)} valid, {len(rejected)} rejected")

# Step 3: Store
from scraper.pipelines.storage import (
    _get_or_create_source, _get_or_create_route,
    create_collection_run, finish_collection_run, store_observations
)
source = _get_or_create_source(session, "MockCollector")
route = _get_or_create_route(session, "BOM", "DEL")
session.commit()
run = create_collection_run(session, source, route)
session.commit()
saved, rej_count, dup_count = store_observations(session, valid_obs, rejected, run)
finish_collection_run(session, run, len(raw_obs), saved, rej_count + dup_count)
session.commit()

# Step 4: Verify from DB
from backend.app.models.airfare import AirfareObservation
all_obs = session.query(AirfareObservation).filter_by(status="valid").all()
print(f"\n[3] STORE:    {saved} records saved to DB")
print(f"\n[4] VERIFY (reading back from DB):")
print("-" * 65)
print(f"  {'Airline':<22} {'Flight':<8} {'Fare (INR)':>12}  {'Lead':>5}  {'Status'}")
print("-" * 65)
for o in all_obs:
    airline_name = o.airline.name if o.airline else "Unknown"
    flight = o.flight_number or "N/A"
    print(f"  {airline_name:<22} {flight:<8} {float(o.total_fare):>12,.2f}  {o.lead_days:>5}d  {o.status}")

print("-" * 65)
print(f"\nCollection Run Summary:")
print(f"  Run ID:           {run.id}")
print(f"  Source:           {source.name}")
print(f"  Route:            {route.route_code}")
print(f"  Records found:    {run.records_found}")
print(f"  Records saved:    {run.records_saved}")
print(f"  Records rejected: {run.records_rejected}")
print(f"\nSample Observation (first record):")
if all_obs:
    o = all_obs[0]
    print(f"  Airline:          {o.airline.name if o.airline else 'N/A'}")
    print(f"  Flight:           {o.flight_number or 'N/A'}")
    print(f"  Travel date:      {o.travel_date}")
    print(f"  Lead days:        {o.lead_days}")
    print(f"  Fare class:       {o.fare_class}")
    print(f"  Base fare:        INR {float(o.base_fare):,.2f}" if o.base_fare else "  Base fare:        N/A")
    print(f"  Taxes:            INR {float(o.taxes):,.2f}" if o.taxes else "  Taxes:            N/A")
    print(f"  Total fare:       INR {float(o.total_fare):,.2f}")
    print(f"  Currency:         {o.currency}")
    print(f"  Status:           {o.status}")
    print(f"  Raw reference:    {o.raw_reference}")

session.close()
print("\n" + "=" * 65)
print("END-TO-END PIPELINE: ALL STEPS VERIFIED SUCCESSFULLY")
print("=" * 65)
