"""
backend/app/services/llm.py
LLM service client powered by Groq API.
Provides AI-driven airfare insights, route trend analysis, and fee breakdown commentary.
"""
from typing import Any, Dict, List, Optional
import logging

from backend.app.config import get_settings

logger = logging.getLogger("apix.llm")

# Lazy import groq
try:
    from groq import Groq
    GROQ_AVAILABLE = True
except ImportError:
    Groq = None
    GROQ_AVAILABLE = False


def get_groq_client() -> Optional[Any]:
    """Return an authenticated Groq client or None if key is absent."""
    settings = get_settings()
    api_key = settings.groq_api_key.strip()
    if not api_key or not GROQ_AVAILABLE:
        return None
    try:
        return Groq(api_key=api_key)
    except Exception as e:
        logger.warning(f"Failed to initialize Groq client: {e}")
        return None


def generate_fare_insights(
    origin: str,
    destination: str,
    travel_date: str,
    lead_days: Optional[int],
    summary: Dict[str, Any],
    flights: List[Dict[str, Any]],
    carrier: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Generate natural language AI insights for a given route search.
    Provides commentary on price levels, fee breakdowns, and lead-time horizon.
    """
    settings = get_settings()
    client = get_groq_client()

    cheapest = summary.get("cheapest_fare")
    typical = summary.get("typical_fare")
    n_flights = summary.get("n_flights", len(flights))

    # Basic fallback heuristic commentary if Groq is unavailable
    fallback_commentary = (
        f"For corridor {origin}→{destination} departing on {travel_date} (T+{lead_days or 'N'} horizon), "
        f"verified fares start at ₹{cheapest:,.0f} with a typical median market fare of ₹{typical:,.0f} across {n_flights} observed flights. "
        "Taxes and regulatory fees (UDF/PSF) comprise a standard portion of the total payable price."
        if cheapest and typical
        else f"corridor {origin}→{destination} currently has {n_flights} verified flight observations."
    )

    if not client:
        return {
            "source": "heuristic",
            "model": "rule-based",
            "insight": fallback_commentary,
            "status": "fallback",
            "message": "Groq API key not configured or client unavailable. Showing heuristic market summary.",
        }

    # Prepare compact prompt for Groq
    flight_samples = []
    for f in flights[:5]:
        pricing = f.get("pricing", {})
        flight_samples.append({
            "flight": f.get("flight_number"),
            "airline": f.get("airline_name"),
            "total": pricing.get("total_fare"),
            "base": pricing.get("base_fare"),
            "taxes_and_fees": (pricing.get("taxes") or 0) + (pricing.get("udf_psf") or 0) + (pricing.get("convenience_fee") or 0),
        })

    system_prompt = (
        "You are an expert Indian aviation economist and airfare index analyst for the APIx (Airfare Price Index) project. "
        "Provide a concise, objective 2-3 paragraph analysis of observed airfares for the given domestic corridor. "
        "Highlight: 1) Price level vs typical domestic benchmarks, 2) Lead-time dynamics (how booking horizon affects this quote), "
        "and 3) Fee decomposition takeaways (base fare vs statutory airport/fuel charges). "
        "Keep language professional, analytical, and data-backed. Do NOT use markdown bullet points; format in readable paragraphs."
    )

    user_prompt = (
        f"Route: {origin} to {destination}\n"
        f"Travel Date: {travel_date} (Lead Horizon: T+{lead_days} days)\n"
        f"Filtered Airline: {carrier or 'All Airlines'}\n"
        f"Cheapest Observed Fare: INR {cheapest}\n"
        f"Median (Typical) Fare: INR {typical}\n"
        f"Sample Verified Flights: {flight_samples}\n"
    )

    try:
        response = client.chat.completions.create(
            model=settings.groq_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.3,
            max_tokens=450,
        )
        insight_text = response.choices[0].message.content.strip()

        return {
            "source": "groq",
            "model": settings.groq_model,
            "insight": insight_text,
            "status": "ok",
        }
    except Exception as e:
        logger.error(f"Error calling Groq API: {e}")
        return {
            "source": "heuristic_fallback",
            "model": "fallback",
            "insight": fallback_commentary,
            "status": "error",
            "error": str(e),
        }
