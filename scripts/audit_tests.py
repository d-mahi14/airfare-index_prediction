"""
Audit verification script for items 3, 4, 5.
"""
import sys
from pathlib import Path

# Add project root to sys.path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
import psycopg2
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.database import Base
from backend.app.models.airfare import Airline, AirfareObservation, Route, Source
from backend.app.models.collection import CollectionRun
from backend.app.schemas.airfare import AirfareObservationCreate
from scraper.pipelines.storage import create_collection_run, store_observations
from scraper.pipelines.validator import validate_observation

DB_URL = "postgresql://airfare_user:apix_dev_password_2024@localhost:5432/airfare_fresh_audit_db"

print("================================================================")
print("AUDIT ITEM 3: Insert Duplicate Observation")
print("================================================================")
conn = psycopg2.connect(DB_URL)
cur = conn.cursor()

# 3A: Direct DB insert test
cur.execute("INSERT INTO sources (id, name, is_active, created_at) VALUES (201, 'AuditSource3', true, NOW()) ON CONFLICT (name) DO UPDATE SET id=EXCLUDED.id RETURNING id;")
s_id = cur.fetchone()[0]
cur.execute("INSERT INTO routes (id, origin, destination, route_code, is_active, created_at) VALUES (201, 'BOM', 'DEL', 'BOM-DEL', true, NOW()) ON CONFLICT (route_code) DO UPDATE SET id=EXCLUDED.id RETURNING id;")
r_id = cur.fetchone()[0]
cur.execute("INSERT INTO airlines (id, name, iata_code, is_active, created_at) VALUES (201, 'AuditAir3', 'A3', true, NOW()) ON CONFLICT (name) DO UPDATE SET id=EXCLUDED.id RETURNING id;")
a_id = cur.fetchone()[0]

obs_uuid1 = str(uuid.uuid4())
obs_uuid2 = str(uuid.uuid4())

cur.execute(f"""
    INSERT INTO airfare_observations (
        id, source_id, route_id, airline_id, flight_number, travel_date,
        collection_timestamp, collection_date, lead_days, fare_class, total_fare, currency, status, created_at
    ) VALUES (
        '{obs_uuid1}', {s_id}, {r_id}, {a_id}, 'A3100', '2026-09-26',
        '2026-09-19 10:00:00+00', '2026-09-19', 7, 'Economy', 5000.00, 'INR', 'valid', NOW()
    );
""")
conn.commit()
print("[3A] First direct SQL INSERT: SUCCESS")

db_duplicate_rejected = False
try:
    cur.execute(f"""
        INSERT INTO airfare_observations (
            id, source_id, route_id, airline_id, flight_number, travel_date,
            collection_timestamp, collection_date, lead_days, fare_class, total_fare, currency, status, created_at
        ) VALUES (
            '{obs_uuid2}', {s_id}, {r_id}, {a_id}, 'A3100', '2026-09-26',
            '2026-09-19 10:00:00+00', '2026-09-19', 7, 'Economy', 5200.00, 'INR', 'valid', NOW()
        );
    """)
    conn.commit()
    print("[3A] Second direct SQL INSERT: FAIL (Allowed duplicate)")
except psycopg2.errors.UniqueViolation as e:
    conn.rollback()
    db_duplicate_rejected = True
    print(f"[3A] Second direct SQL INSERT: PASS (Rejected with UniqueViolation on constraint '{e.diag.constraint_name}')")

cur.close()
conn.close()

# 3B: StoragePipeline test
engine = create_engine(DB_URL)
Session = sessionmaker(bind=engine)
session = Session()

source = session.query(Source).filter_by(name='StorageAuditSource').first()
if not source:
    source = Source(name='StorageAuditSource', is_active=True)
    session.add(source)
    session.commit()

route = session.query(Route).filter_by(route_code='BOM-DEL').first()
run = create_collection_run(session, source, route)
session.commit()

obs_pipeline = AirfareObservationCreate(
    collection_timestamp=datetime(2026, 9, 19, 10, 0, tzinfo=timezone.utc),
    collection_date=date(2026, 9, 19),
    source_name=source.name,
    origin='BOM',
    destination='DEL',
    airline_name='IndiGo',
    airline_iata='6E',
    flight_number='6E999',
    travel_date=date(2026, 9, 26),
    lead_days=7,
    fare_class='Economy',
    base_fare=Decimal('4000.00'),
    taxes=Decimal('200.00'),
    udf_psf=Decimal('300.00'),
    convenience_fee=Decimal('200.00'),
    other_fees=Decimal('0.00'),
    total_fare=Decimal('4700.00'),
)

saved1, rej1, dup1 = store_observations(session, [obs_pipeline], [], run)
session.commit()
print(f"[3B] StoragePipeline Initial Run: saved={saved1}, rejected={rej1}, duplicates={dup1}")

saved2, rej2, dup2 = store_observations(session, [obs_pipeline], [], run)
session.commit()
print(f"[3B] StoragePipeline Duplicate Run: saved={saved2}, rejected={rej2}, duplicates={dup2}")

pipeline_duplicate_rejected = (saved2 == 0 and dup2 == 1)
if pipeline_duplicate_rejected:
    print("[3B] StoragePipeline Duplicate Detection: PASS (Correctly identified duplicate and skipped re-insert)")
else:
    print("[3B] StoragePipeline Duplicate Detection: FAIL")

print("\n================================================================")
print("AUDIT ITEM 4: Insert total != sum of components")
print("================================================================")
# Test 4A: Schema-level rejection
schema_rejected = False
try:
    bad_obs = AirfareObservationCreate(
        collection_timestamp=datetime(2026, 9, 19, 10, 0, tzinfo=timezone.utc),
        source_name="SumAudit",
        origin="BOM",
        destination="DEL",
        airline_name="Air India",
        travel_date=date(2026, 9, 26),
        base_fare=Decimal("4000.00"),
        taxes=Decimal("500.00"),
        udf_psf=Decimal("200.00"),
        convenience_fee=Decimal("150.00"),
        other_fees=Decimal("0.00"),
        total_fare=Decimal("6000.00"),  # Expected: 4850.00 -> Mismatch!
    )
    print("[4A] Schema Validation: FAIL (Allowed invalid sum)")
except ValidationError as e:
    schema_rejected = True
    print(f"[4A] Schema Validation: PASS (Rejected with ValidationError: {e.errors()[0]['msg']})")

# Test 4B: Validator pipeline rejection
validator_rejected = False
try:
    # Construct minimal valid object without base_fare, but test validator rule directly
    obs_test = AirfareObservationCreate(
        collection_timestamp=datetime(2026, 9, 19, 10, 0, tzinfo=timezone.utc),
        source_name="SumAudit",
        origin="BOM",
        destination="DEL",
        airline_name="Air India",
        travel_date=date(2026, 9, 26),
        base_fare=Decimal("4000.00"),
        taxes=Decimal("500.00"),
        udf_psf=Decimal("200.00"),
        convenience_fee=Decimal("150.00"),
        other_fees=Decimal("0.00"),
        total_fare=Decimal("4850.00"),
    )
    # Tamper with total_fare directly to test validator pass
    obs_test.total_fare = Decimal("6000.00")
    val_res = validate_observation(obs_test)
    if not val_res.is_valid:
        validator_rejected = True
        print(f"[4B] Pipeline Validator: PASS (Rejected with reason: {val_res.rejection_reason})")
    else:
        print("[4B] Pipeline Validator: FAIL (Allowed mismatched sum)")
except Exception as e:
    print(f"[4B] Exception in validator check: {e}")

print("\n================================================================")
print("AUDIT ITEM 5: Check is_synthetic on existing rows")
print("================================================================")
all_synthetic = session.query(AirfareObservation).all()
synthetic_count = session.query(AirfareObservation).filter_by(is_synthetic=True).count()
total_rows = len(all_synthetic)
non_synthetic_count = session.query(AirfareObservation).filter(AirfareObservation.is_synthetic != True).count()

print(f"Total rows in DB: {total_rows}")
print(f"Rows with is_synthetic = True: {synthetic_count}")
print(f"Rows with is_synthetic != True: {non_synthetic_count}")

if total_rows > 0 and non_synthetic_count == 0:
    print("PASS: 100% of airfare_observations have is_synthetic = True.")
elif total_rows == 0:
    print("PASS: Table is currently empty or has no non-synthetic rows.")
else:
    print(f"FAIL: Found {non_synthetic_count} rows where is_synthetic != True.")

session.close()
engine.dispose()
