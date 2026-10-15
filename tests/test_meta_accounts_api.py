"""
Tests for Meta Ad Accounts API Endpoints (Phase-1 onboarding CRUD).
"""

import uuid
from datetime import date
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from app.core.database import async_session_maker
from app.models.ad_account import AdAccount
from app.models.metrics import CampaignMetricsSnapshot
from app.models.tenant import Tenant


@pytest.fixture
async def sample_tenant():
    """Seed a test tenant into the database."""
    t_id = uuid.uuid4()
    async with async_session_maker() as session:
        tenant = Tenant(
            id=t_id,
            company_name="Phase1 Agency Client",
            country_code="PK",
            currency="PKR",
            preferred_language="roman_urdu",
            whatsapp_notification_number="+923009988776",
        )
        session.add(tenant)
        await session.commit()
    return tenant


@pytest.mark.asyncio
async def test_register_ad_account_success(client: AsyncClient, sample_tenant):
    """Test successful ad account registration and DB persistence."""
    payload = {
        "tenant_id": str(sample_tenant.id),
        "external_account_id": "act_phase1_test_999",
        "account_name": "Phase1 Testing Brand",
        "max_budget_ceiling_pkr": 50000.0,
        "target_cpa_pkr": 650.0,
        "target_roas": 2.5,
    }

    response = await client.post("/api/v1/meta/accounts", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["status"] == "registered"
    assert data["external_account_id"] == "act_phase1_test_999"
    assert data["account_name"] == "Phase1 Testing Brand"

    # Verify duplicate prevention (409)
    dup_res = await client.post("/api/v1/meta/accounts", json=payload)
    assert dup_res.status_code == 409


@pytest.mark.asyncio
async def test_register_ad_account_invalid_tenant(client: AsyncClient):
    """Test registering ad account with non-existent tenant returns 404."""
    payload = {
        "tenant_id": str(uuid.uuid4()),
        "external_account_id": "act_ghost_111",
        "account_name": "Ghost Account",
        "max_budget_ceiling_pkr": 10000.0,
    }
    response = await client.post("/api/v1/meta/accounts", json=payload)
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_list_ad_accounts(client: AsyncClient, sample_tenant):
    """Test listing ad accounts with and without tenant filter."""
    async with async_session_maker() as session:
        acc = AdAccount(
            tenant_id=sample_tenant.id,
            platform="META",
            external_account_id="act_list_001",
            account_name="List Brand Account",
            max_budget_ceiling_pkr=20000.0,
            is_active=True,
        )
        session.add(acc)
        await session.commit()

    # List all
    res = await client.get("/api/v1/meta/accounts")
    assert res.status_code == 200
    data = res.json()
    assert data["total"] >= 1
    assert any(a["external_account_id"] == "act_list_001" for a in data["accounts"])

    # Filter by tenant
    res_filter = await client.get(f"/api/v1/meta/accounts?tenant_id={sample_tenant.id}")
    assert res_filter.status_code == 200
    assert res_filter.json()["total"] >= 1


@pytest.mark.asyncio
async def test_get_account_metrics(client: AsyncClient, sample_tenant):
    """Test querying metrics snapshots for an account."""
    acc_id = uuid.uuid4()
    today = date.today()

    async with async_session_maker() as session:
        acc = AdAccount(
            id=acc_id,
            tenant_id=sample_tenant.id,
            platform="META",
            external_account_id="act_metrics_001",
            account_name="Metrics Test Account",
            max_budget_ceiling_pkr=30000.0,
            is_active=True,
        )
        session.add(acc)

        snap = CampaignMetricsSnapshot(
            ad_account_id=acc_id,
            external_campaign_id="camp_m_01",
            campaign_name="Summer Test Campaign",
            snapshot_date=today,
            spend=12000.0,
            impressions=50000,
            clicks=1500,
            conversions=20,
            roas=3.2,
            ctr=3.0,
            cpc=8.0,
            cpa=600.0,
        )
        session.add(snap)
        await session.commit()

    res = await client.get(f"/api/v1/meta/accounts/act_metrics_001/metrics?date_start={today.isoformat()}")
    assert res.status_code == 200
    data = res.json()
    assert data["account_id"] == "act_metrics_001"
    assert len(data["metrics"]) == 1
    assert data["metrics"][0]["spend"] == 12000.0
    assert data["metrics"][0]["roas"] == 3.2


@pytest.mark.asyncio
async def test_trigger_metrics_sync(client: AsyncClient, sample_tenant):
    """Test manual live sync endpoint persists snapshots to DB."""
    async with async_session_maker() as session:
        acc = AdAccount(
            tenant_id=sample_tenant.id,
            platform="META",
            external_account_id="act_sync_test_888",
            account_name="Sync Test Account",
            max_budget_ceiling_pkr=40000.0,
            is_active=True,
        )
        session.add(acc)
        await session.commit()

    mock_insights = [
        {
            "campaign_id": "camp_synced_99",
            "campaign_name": "Synced Brand Awareness",
            "spend": "4500.00",
            "impressions": "20000",
            "clicks": "800",
            "actions": [{"action_type": "purchase", "value": "15"}],
            "action_values": [{"action_type": "purchase", "value": "13500.00"}],
        }
    ]

    with patch("app.api.endpoints.meta_accounts.MetaGraphClient") as mock_client_cls:
        mock_instance = AsyncMock()
        mock_instance.get_account_insights.return_value = mock_insights
        mock_client_cls.return_value = mock_instance

        res = await client.post("/api/v1/meta/accounts/act_sync_test_888/sync")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "synced"
        assert data["snapshots_saved"] == 1


@pytest.mark.asyncio
async def test_get_account_metrics_by_internal_uuid(client: AsyncClient, sample_tenant):
    """Test resolving account metrics using internal database UUID."""
    acc_id = uuid.uuid4()
    async with async_session_maker() as session:
        acc = AdAccount(
            id=acc_id,
            tenant_id=sample_tenant.id,
            platform="META",
            external_account_id="act_uuid_lookup_001",
            account_name="UUID Lookup Account",
            max_budget_ceiling_pkr=10000.0,
            is_active=True,
        )
        session.add(acc)
        await session.commit()

    res = await client.get(f"/api/v1/meta/accounts/{str(acc_id)}/metrics")
    assert res.status_code == 200
    assert res.json()["account_id"] == "act_uuid_lookup_001"


@pytest.mark.asyncio
async def test_trigger_metrics_sync_meta_error_502(client: AsyncClient, sample_tenant):
    """Test MetaAPIError produces 502 Bad Gateway response."""
    from app.utils.meta_client import MetaAPIError

    async with async_session_maker() as session:
        acc = AdAccount(
            tenant_id=sample_tenant.id,
            platform="META",
            external_account_id="act_sync_error_001",
            account_name="Sync Error Account",
            max_budget_ceiling_pkr=10000.0,
            is_active=True,
        )
        session.add(acc)
        await session.commit()

    with patch("app.api.endpoints.meta_accounts.MetaGraphClient") as mock_client_cls:
        mock_instance = AsyncMock()
        mock_instance.get_account_insights.side_effect = MetaAPIError("Meta API service unavailable", code=500)
        mock_client_cls.return_value = mock_instance

        res = await client.post("/api/v1/meta/accounts/act_sync_error_001/sync")
        assert res.status_code == 502
        assert "Meta Graph API error" in res.json()["detail"]
