"""
Shared test fixtures for AgentZline test suite.
"""

import os

import pytest
from cryptography.fernet import Fernet
from httpx import AsyncClient, ASGITransport

# Generate a valid Fernet key for tests (must be set before any app imports)
os.environ.setdefault("FERNET_ENCRYPTION_KEY", Fernet.generate_key().decode())

from app.main import app  # noqa: E402


@pytest.fixture
async def client():
    """Async test client for FastAPI endpoints."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def sample_campaign_metrics() -> list[dict]:
    """Sample campaign metrics for testing anomaly detection."""
    return [
        {
            "id": "camp_001",
            "name": "Summer Sale - P1",
            "spend": 15000.0,
            "impressions": 250000,
            "clicks": 1800,
            "conversions": 25,
            "roas": 2.1,
            "ctr": 0.72,
            "cpc": 8.33,
            "cpa": 600.0,
            "frequency": 2.3,
        },
        {
            "id": "camp_002",
            "name": "Eid Collection - Video",
            "spend": 8500.0,
            "impressions": 120000,
            "clicks": 600,
            "conversions": 0,  # Budget bleed!
            "roas": 0.0,
            "ctr": 0.50,
            "cpc": 14.17,
            "cpa": float("inf"),
            "frequency": 4.8,  # Ad fatigue!
        },
        {
            "id": "camp_003",
            "name": "Retargeting - Cart Abandon",
            "spend": 7000.0,
            "impressions": 80000,
            "clicks": 400,
            "conversions": 8,
            "roas": 0.9,  # ROAS below target!
            "ctr": 0.50,
            "cpc": 17.50,
            "cpa": 875.0,  # CPA well above target (500 * 1.25 = 625)
            "frequency": 3.1,
        },
    ]


@pytest.fixture
def sample_daily_summary() -> dict:
    """Sample daily summary for testing report formatting."""
    return {
        "account_name": "BrandX Pakistan",
        "date": "2026-06-09",
        "total_spend": 28500.0,
        "total_impressions": 450000,
        "total_clicks": 2800,
        "total_conversions": 33,
        "aggregate_roas": 1.2,
        "aggregate_ctr": 0.62,
    }
