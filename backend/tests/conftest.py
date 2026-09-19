# backend/tests/conftest.py
"""
Shared pytest fixtures for backend tests.

Runs DB tests on PostgreSQL (airfare_test_db) with full dialect support
(UUID, check constraints, unique keys, timezone types).
Falls back to in-memory SQLite if PostgreSQL is unreachable.
"""
import os
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# Ensure project root is on sys.path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from backend.app.database import Base
import backend.app.models  # noqa: F401 — register all models

TEST_POSTGRES_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg2://airfare_user:apix_dev_password_2024@localhost:5432/airfare_test_db",
)


def _get_test_engine():
    """Try connecting to PostgreSQL test DB; fallback to SQLite if unavailable."""
    try:
        engine = create_engine(TEST_POSTGRES_URL, echo=False, pool_pre_ping=True)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return engine
    except Exception:
        # Graceful SQLite fallback for isolated test environments
        return create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            echo=False,
        )


@pytest.fixture(scope="session")
def test_engine():
    """Session-scoped database engine."""
    engine = _get_test_engine()
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture(scope="function")
def db_session(test_engine):
    """Provide an isolated database session per test with clean tables."""
    Base.metadata.create_all(test_engine)
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
