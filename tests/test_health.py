"""
Tests for health check endpoints.
"""

import pytest


@pytest.mark.asyncio
async def test_health_check(client):
    """Test the basic health endpoint returns healthy status."""
    response = await client.get("/api/v1/health")
    assert response.status_code == 200

    data = response.json()
    assert data["status"] == "healthy"
    assert data["service"] == "agentzline"
    assert data["tier"] == "bronze"


@pytest.mark.asyncio
async def test_readiness_check(client):
    """Test the readiness probe endpoint."""
    response = await client.get("/api/v1/health/ready")
    assert response.status_code == 200

    data = response.json()
    assert data["status"] == "ready"
