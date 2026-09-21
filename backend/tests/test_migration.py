"""
backend/tests/test_migration.py
Tests for Alembic migrations up/down and schema drift detection.

Verifies:
  - Non-destructive migration of fees into other_fees
  - Population of collection_date and is_synthetic flags
  - Observation count migration to n_obs
  - Full reversibility of migration 002
  - Schema parity with ORM metadata (zero schema drift)
  - Safety guard enforcement on non-_test database names
"""
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, text

from backend.app.database import Base
from backend.tests.conftest import (
    ALEMBIC_INI_PATH,
    get_test_database_url,
    verify_test_db_safety,
)

_PROJECT_ROOT = Path(__file__).parent.parent.parent


@pytest.fixture(scope="module")
def migration_engine():
    """Engine dedicated to migration lifecycle and drift tests on test DB."""
    test_db_url = get_test_database_url()
    verify_test_db_safety(test_db_url)
    engine = create_engine(test_db_url, pool_pre_ping=True)
    yield engine
    engine.dispose()


class TestAlembicMigrations:
    def test_migration_up_and_down_lifecycle(self, migration_engine):
        """Verify full migration lifecycle 001 -> 002 -> 001 -> head."""
        test_db_url = get_test_database_url()
        verify_test_db_safety(test_db_url)

        # 1. Clean public schema
        with migration_engine.begin() as conn:
            conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))

        with migration_engine.connect() as conn:
            cfg = Config(ALEMBIC_INI_PATH)
            cfg.attributes["connection"] = conn

            # 2. Upgrade to 001
            command.upgrade(cfg, "001_initial_schema")

            # 3. Insert legacy 001 rows
            conn.execute(text(
                "INSERT INTO sources (name, is_active, created_at) VALUES ('LegacySource', true, NOW())"
            ))
            conn.execute(text(
                "INSERT INTO routes (origin, destination, route_code, is_active, created_at) VALUES ('BOM', 'DEL', 'BOM-DEL', true, NOW())"
            ))
            conn.execute(text(
                "INSERT INTO airlines (name, iata_code, is_active, created_at) VALUES ('LegacyAir', 'LA', true, NOW())"
            ))
            source_id = conn.execute(text("SELECT id FROM sources WHERE name='LegacySource'")).scalar()
            route_id = conn.execute(text("SELECT id FROM routes WHERE route_code='BOM-DEL'")).scalar()
            airline_id = conn.execute(text("SELECT id FROM airlines WHERE name='LegacyAir'")).scalar()

            # Insert legacy airfare observation with old fees column
            conn.execute(text(f"""
                INSERT INTO airfare_observations (
                    id, source_id, route_id, airline_id, flight_number,
                    travel_date, lead_days, fare_class, base_fare, taxes,
                    fees, total_fare, currency, availability, status, created_at
                ) VALUES (
                    'a0000000-0000-0000-0000-000000000001',
                    {source_id}, {route_id}, {airline_id}, 'LA101',
                    '2026-09-26', 7, 'Economy', 4000.00, 500.00,
                    450.00, 4950.00, 'INR', 'available', 'valid', NOW()
                )
            """))

            # Insert legacy index_values
            conn.execute(text("""
                INSERT INTO index_values (index_date, apix_value, methodology_version, observation_count, created_at)
                VALUES ('2026-09-19', 112.5000, 'v1.0', 45, NOW())
            """))

            # Insert legacy route_weights
            conn.execute(text(f"""
                INSERT INTO route_weights (route_id, weight, effective_date, source, is_active, created_at)
                VALUES ({route_id}, 0.250000, '2026-01-01', 'Legacy_Spec', true, NOW())
            """))
            conn.commit()

            # 4. Run upgrade to 002
            command.upgrade(cfg, "002_harden_milestone1_schema")

            # 5. Verify migrated values in 002 schema
            obs = conn.execute(text("""
                SELECT other_fees, collection_date, is_synthetic, stops
                FROM airfare_observations
                WHERE id='a0000000-0000-0000-0000-000000000001'
            """)).mappings().first()

            assert obs is not None
            assert float(obs["other_fees"]) == 450.00  # migrated from fees
            assert obs["collection_date"] is not None
            assert obs["is_synthetic"] is True
            assert obs["stops"] == 0

            idx = conn.execute(text("""
                SELECT n_obs, frequency, variant
                FROM index_values
                WHERE index_date='2026-09-19'
            """)).mappings().first()

            assert idx is not None
            assert idx["n_obs"] == 45
            assert idx["frequency"] == "daily"
            assert idx["variant"] == "overall"

            rw = conn.execute(text("""
                SELECT valid_from, valid_to
                FROM route_weights
                WHERE source='Legacy_Spec'
            """)).mappings().first()

            assert rw is not None
            assert str(rw["valid_from"]) == "2026-01-01"

            # 6. Test downgrade back to 001
            command.downgrade(cfg, "001_initial_schema")

            # 7. Upgrade back to head
            command.upgrade(cfg, "head")

    def test_schema_drift_matches_orm_metadata(self, migration_engine):
        """Compare the migrated database schema against ORM Base.metadata and assert zero drift."""
        test_db_url = get_test_database_url()
        verify_test_db_safety(test_db_url)

        with migration_engine.connect() as conn:
            cfg = Config(ALEMBIC_INI_PATH)
            cfg.attributes["connection"] = conn
            command.upgrade(cfg, "head")

            mc = MigrationContext.configure(
                conn,
                opts={"compare_type": True, "compare_server_default": False},
            )
            raw_diff = compare_metadata(mc, Base.metadata)

            # Filter out cosmetic docstring comments
            def is_structural_diff(diff_item):
                if isinstance(diff_item, (list, tuple)) and len(diff_item) > 0:
                    first = diff_item[0]
                    if isinstance(first, (list, tuple)) and len(first) > 0:
                        return first[0] != "modify_comment"
                    return first != "modify_comment"
                return True

            structural_diffs = [d for d in raw_diff if is_structural_diff(d)]
            assert structural_diffs == [], f"Detected schema drift between migrations and ORM: {structural_diffs}"

    def test_safety_guard_rejects_non_test_db(self):
        """Verify that verify_test_db_safety rejects any database name not ending in '_test'."""
        with pytest.raises(RuntimeError, match="SAFETY GUARD VIOLATION"):
            verify_test_db_safety("postgresql+psycopg2://user:pass@localhost:5432/airfare_db")

        with pytest.raises(RuntimeError, match="SAFETY GUARD VIOLATION"):
            verify_test_db_safety("postgresql+psycopg2://user:pass@localhost:5432/production")

        with pytest.raises(RuntimeError, match="SAFETY GUARD VIOLATION"):
            verify_test_db_safety("postgresql+psycopg2://user:pass@localhost:5432/airfare_prod")

        # Valid test DB names ending with _test must pass without error
        verify_test_db_safety("postgresql+psycopg2://user:pass@localhost:5432/airfare_test")
        verify_test_db_safety("postgresql+psycopg2://user:pass@localhost:5432/my_app_test")
