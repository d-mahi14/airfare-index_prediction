# backend/tests/conftest.py
"""
Shared pytest fixtures for backend tests.

Key design: tests use an in-memory SQLite database, not the real PostgreSQL.
This makes tests:
  - Fast (no network)
  - Isolated (each test gets a fresh DB)
  - No external dependencies

SQLite doesn't support all PostgreSQL features (e.g. UUID type maps differently),
but it's sufficient for testing the ORM layer and business logic.
"""
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Ensure project root is on sys.path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from backend.app.database import Base
import backend.app.models  # noqa: F401 — register all models


@pytest.fixture(scope="function")
def db_engine():
    """Create a fresh in-memory SQLite engine for each test function."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        echo=False,
    )
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture(scope="function")
def db_session(db_engine):
    """Provide a SQLAlchemy session bound to the in-memory SQLite DB."""
    SessionLocal = sessionmaker(bind=db_engine, autocommit=False, autoflush=False)
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
