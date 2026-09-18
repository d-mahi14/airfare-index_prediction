"""
backend/app/utils/logging.py
Structured logging configuration for the APIx backend.
"""
import logging
import sys


def configure_logging(level: str = "INFO") -> None:
    """
    Configure root logger with structured formatting.

    Format: ISO timestamp [LEVEL] logger_name: message
    """
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(
        level=numeric_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
        stream=sys.stdout,
        force=True,
    )
    # Suppress overly verbose third-party loggers
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.pool").setLevel(logging.WARNING)
    logging.getLogger("alembic").setLevel(logging.INFO)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
