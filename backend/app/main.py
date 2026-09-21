"""
backend/app/main.py
FastAPI application entry point.

Endpoints:
  - /api/health: Service health check
  - /fares/search & /api/fares/search: Serve-time validated fare search
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.api.fares import router as fares_router
from backend.app.api.insights import router as insights_router
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
    version="0.2.0",
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

# Register endpoint routers
app.include_router(fares_router)
app.include_router(insights_router)


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
        "version": "0.2.0",
    }
