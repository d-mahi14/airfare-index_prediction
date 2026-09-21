# backend/tests/conftest.py
"""
Shared pytest fixtures for backend tests.

Runs DB tests strictly on PostgreSQL with full dialect support
(UUID, check constraints, unique keys, timezone types).
Builds schema via `alembic upgrade head` and tears down via `alembic downgrade base`.
No silent fallback to SQLite: if PostgreSQL is unreachable or TEST_DATABASE_URL is missing,
tests fail immediately with clear diagnostic errors.
"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, make_url, text
from sqlalchemy.orm import sessionmaker

# Ensure project root is on sys.path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

# Load .env file from project root
dotenv_path = project_root / ".env"
load_dotenv(dotenv_path=dotenv_path)

from backend.app.database import Base
import backend.app.models  # noqa: F401 — register all models

ALEMBIC_INI_PATH = str(project_root / "alembic.ini")


def get_test_database_url() -> str:
    """Read TEST_DATABASE_URL strictly from environment / .env, raising error if missing."""
    url = os.environ.get("TEST_DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError(
            "TEST_DATABASE_URL environment variable is required for running tests, but is not set. "
            "Please configure TEST_DATABASE_URL in your .env file or environment (e.g., "
            "TEST_DATABASE_URL=postgresql+psycopg2://airfare_user:password@localhost:5432/airfare_test)."
        )
    return url


def verify_test_db_safety(url_str: str) -> None:
    """Safety guard: refuse to run drop/downgrade/migrations unless database name ends with '_test'."""
    parsed_url = make_url(url_str)
    db_name = parsed_url.database or ""
    if not db_name.endswith("_test"):
        raise RuntimeError(
            f"SAFETY GUARD VIOLATION: Test database name '{db_name}' must end with '_test'. "
            f"Refusing to execute drop/downgrade/migration operations to protect development and production databases."
        )


def _get_test_engine(test_db_url: str):
    """Create engine for PostgreSQL test DB, failing with descriptive error if unreachable."""
    verify_test_db_safety(test_db_url)
    parsed = make_url(test_db_url)
    safe_url = parsed.render_as_string(hide_password=True)

    try:
        engine = create_engine(test_db_url, echo=False, pool_pre_ping=True)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return engine
    except Exception as exc:
        raise RuntimeError(
            f"Failed to connect to PostgreSQL test database at '{safe_url}'. "
            f"Database tests require a live PostgreSQL test instance and will not silently fall back to SQLite. "
            f"Error: {exc}"
        ) from exc


@pytest.fixture(scope="session")
def test_engine():
    """
    Session-scoped database engine.
    Builds the test schema by running `alembic upgrade head` against the test DB.
    Tears down with a clean `alembic downgrade base`.
    """
    test_db_url = get_test_database_url()
    verify_test_db_safety(test_db_url)
    engine = _get_test_engine(test_db_url)

    alembic_cfg = Config(ALEMBIC_INI_PATH)
    alembic_cfg.set_main_option("sqlalchemy.url", test_db_url)

    # Clean existing schema if dirty from interrupted prior runs, then run upgrade head
    try:
        command.downgrade(alembic_cfg, "base")
    except Exception:
        pass
    command.upgrade(alembic_cfg, "head")

    yield engine

    # Clean teardown: downgrade to base
    verify_test_db_safety(test_db_url)
    try:
        command.downgrade(alembic_cfg, "base")
    except Exception:
        pass
    engine.dispose()


@pytest.fixture(scope="function")
def db_session(test_engine):
    """Provide an isolated database session per test with clean tables."""
    with test_engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(table.delete())

    SessionLocal = sessionmaker(bind=test_engine, autocommit=False, autoflush=False)
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@pytest.fixture(scope="function")
def db_engine(test_engine):
    """Function-level alias for test_engine."""
    return test_engine
