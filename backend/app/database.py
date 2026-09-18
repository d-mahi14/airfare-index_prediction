"""
backend/app/database.py
SQLAlchemy engine and session management.

For tests, override the DATABASE_URL via environment to use SQLite.
"""
from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from backend.app.config import get_settings


class Base(DeclarativeBase):
    """All ORM models inherit from this base."""
    pass


def build_engine(database_url: str | None = None):
    """
    Create a SQLAlchemy engine.

    If database_url is None, uses the URL from settings.
    Allows tests to inject a SQLite URL.
    """
    url = database_url or get_settings().database_url
    connect_args = {}
    if url.startswith("sqlite"):
        connect_args = {"check_same_thread": False}
    return create_engine(
        url,
        echo=False,         # set to True for SQL query logging
        pool_pre_ping=True, # verify connections before use
        connect_args=connect_args,
    )


# Application-level singletons (created once on import)
_engine = None
_SessionLocal = None


def get_engine():
    global _engine
    if _engine is None:
        _engine = build_engine()
    return _engine


def get_session_factory():
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(
            bind=get_engine(),
            autocommit=False,
            autoflush=False,
            expire_on_commit=False,
        )
    return _SessionLocal


@contextmanager
def get_db_session() -> Generator[Session, None, None]:
    """
    Context manager for a database session.

    Usage:
        with get_db_session() as session:
            session.add(obj)
            session.commit()
    """
    factory = get_session_factory()
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def check_connection() -> bool:
    """Return True if the database is reachable."""
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
