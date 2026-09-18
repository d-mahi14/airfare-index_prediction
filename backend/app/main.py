"""
backend/app/main.py
FastAPI application entry point — Milestone 1 stub.

Only /api/health is implemented in Milestone 1.
Full API endpoints (fares, index, routes) come in Phase 14.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.config import get_settings
from backend.app.database import check_connection

settings = get_settings()

app = FastAPI(
    title="Real-Time Indian Domestic Airfare Price Index (APIx)",
    description=(
        "An independent high-frequency airfare data collection and index construction system "
        "for Indian domestic aviation. Provides daily APIx values, route-level indices, "
        "lead-time analysis, and MoSPI CPI benchmark comparison."
    ),
    version="0.1.0-milestone1",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health", tags=["Health"])
def health_check():
    """
    Service health check.
    Returns database connectivity status and basic config.
    """
    db_ok = check_connection()
    return {
        "status": "healthy" if db_ok else "degraded",
        "database": "connected" if db_ok else "disconnected",
        "app_env": settings.app_env,
        "base_year": settings.base_year,
        "version": "0.1.0-milestone1",
    }
