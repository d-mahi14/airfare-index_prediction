"""
backend/tests/test_insights.py
Unit and endpoint tests for Groq LLM airfare insights.
"""
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.services.llm import generate_fare_insights, get_groq_client


@pytest.fixture
def client():
    return TestClient(app)


def test_insights_status_endpoint(client):
    response = client.get("/api/insights/status")
    assert response.status_code == 200
    data = response.json()
    assert data["provider"] == "Groq"
    assert "model" in data
    assert "configured" in data


def test_generate_fare_insights_fallback_without_client():
    with patch("backend.app.services.llm.get_groq_client", return_value=None):
        res = generate_fare_insights(
            origin="DEL",
            destination="BOM",
            travel_date="2026-10-06",
            lead_days=15,
            summary={"cheapest_fare": 4500, "typical_fare": 5480, "n_flights": 8},
            flights=[],
        )
        assert res["source"] == "heuristic"
        assert "DEL→BOM" in res["insight"]
        assert res["status"] == "fallback"


def test_generate_fare_insights_with_mocked_groq():
    mock_client = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = "Airfare on the DEL-BOM corridor reflects stable demand at T+15 days."
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    mock_client.chat.completions.create.return_value = mock_response

    with patch("backend.app.services.llm.get_groq_client", return_value=mock_client):
        res = generate_fare_insights(
            origin="DEL",
            destination="BOM",
            travel_date="2026-10-06",
            lead_days=15,
            summary={"cheapest_fare": 4500, "typical_fare": 5480, "n_flights": 8},
            flights=[
                {
                    "flight_number": "6E-205",
                    "airline_name": "IndiGo",
                    "pricing": {"total_fare": 4500, "base_fare": 3500, "taxes": 450, "udf_psf": 350, "convenience_fee": 200},
                }
            ],
        )
        assert res["source"] == "groq"
        assert "DEL-BOM" in res["insight"]
        assert res["status"] == "ok"


def test_post_fare_summary_endpoint(client):
    payload = {
        "origin": "DEL",
        "destination": "BOM",
        "travel_date": "2026-10-06",
        "lead_days": 15,
        "summary": {"cheapest_fare": 4500, "typical_fare": 5480, "n_flights": 1},
        "flights": [],
    }
    response = client.post(
        "/api/insights/fare-summary",
        json=payload,
        headers={"X-API-Key": "apix_dev_key_2024"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "insight" in data
    assert "status" in data
