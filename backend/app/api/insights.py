"""
backend/app/api/insights.py
FastAPI router for AI-driven airfare insights powered by Groq.
"""
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Header, HTTPException, Query, status
from pydantic import BaseModel

from backend.app.config import get_settings
from backend.app.services.llm import generate_fare_insights, get_groq_client

router = APIRouter(prefix="/api/insights", tags=["AI Insights"])
settings = get_settings()


class FareInsightsRequest(BaseModel):
    origin: str
    destination: str
    travel_date: str
    lead_days: Optional[int] = 15
    carrier: Optional[str] = None
    summary: Dict[str, Any] = {}
    flights: List[Dict[str, Any]] = []


@router.get("/status")
def get_insights_status():
    """Check Groq LLM integration status."""
    has_key = bool(settings.groq_api_key.strip())
    client = get_groq_client()
    return {
        "provider": "Groq",
        "model": settings.groq_model,
        "configured": has_key,
        "client_ready": client is not None,
    }


@router.post("/fare-summary")
def get_fare_summary_insights(
    payload: FareInsightsRequest,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
):
    """
    Generate natural language analytical commentary for a search result using Groq.
    """
    # Verify API key if configured
    expected_key = "apix_dev_key_2024"
    if x_api_key and x_api_key != expected_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid X-API-Key provided",
        )

    return generate_fare_insights(
        origin=payload.origin.upper(),
        destination=payload.destination.upper(),
        travel_date=payload.travel_date,
        lead_days=payload.lead_days,
        summary=payload.summary,
        flights=payload.flights,
        carrier=payload.carrier,
    )
