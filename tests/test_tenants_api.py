"""
Tests for Tenant / Agency Management API Endpoints (Phase-1 Task #3).
"""

import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import async_session_maker
from app.models.tenant import Tenant
from app.models.ad_account import AdAccount


@pytest.mark.asyncio
async def test_create_tenant_success(client: AsyncClient):
    """Test successful tenant creation with valid E.164 phone and language."""
    payload = {
        "company_name": "Royal Fabrics Lahore",
        "country_code": "PK",
        "currency": "PKR",
        "preferred_language": "roman_urdu",
        "whatsapp_notification_number": "+923001234567",
    }
    response = await client.post("/api/v1/tenants", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["company_name"] == "Royal Fabrics Lahore"
    assert data["preferred_language"] == "roman_urdu"
    assert data["whatsapp_notification_number"] == "+923001234567"
    assert "id" in data

    # Verify directly in DB
    t_uuid = uuid.UUID(data["id"])
    async with async_session_maker() as session:
        t = await session.get(Tenant, t_uuid)
        assert t is not None
        assert t.company_name == "Royal Fabrics Lahore"


@pytest.mark.asyncio
async def test_create_tenant_validation_errors(client: AsyncClient):
    """Test phone format and language validation rules."""
    # Invalid phone (not E.164)
    res_bad_phone = await client.post(
        "/api/v1/tenants",
        json={
            "company_name": "Bad Phone Agency",
            "whatsapp_notification_number": "03001234567",  # Missing + prefix
        },
    )
    assert res_bad_phone.status_code == 422

    # Invalid language
    res_bad_lang = await client.post(
        "/api/v1/tenants",
        json={
            "company_name": "Bad Lang Agency",
            "whatsapp_notification_number": "+923001234567",
            "preferred_language": "french",
        },
    )
    assert res_bad_lang.status_code == 422


@pytest.mark.asyncio
async def test_list_tenants(client: AsyncClient):
    """Test tenant listing with pagination."""
    t_id = uuid.uuid4()
    async with async_session_maker() as session:
        tenant = Tenant(
            id=t_id,
            company_name="Listing Test Brand",
            country_code="PK",
            currency="PKR",
            preferred_language="english",
            whatsapp_notification_number="+923008889999",
        )
        session.add(tenant)
        await session.commit()

    res = await client.get("/api/v1/tenants?limit=10&offset=0")
    assert res.status_code == 200
    data = res.json()
    assert data["total"] >= 1
    assert any(t["id"] == str(t_id) for t in data["tenants"])


@pytest.mark.asyncio
async def test_get_tenant_by_id(client: AsyncClient):
    """Test getting single tenant by ID, 404 for missing, 400 for bad UUID."""
    t_id = uuid.uuid4()
    async with async_session_maker() as session:
        tenant = Tenant(
            id=t_id,
            company_name="Single Brand Detail",
            whatsapp_notification_number="+923007778888",
        )
        session.add(tenant)
        await session.commit()

    # Success
    res = await client.get(f"/api/v1/tenants/{t_id}")
    assert res.status_code == 200
    assert res.json()["company_name"] == "Single Brand Detail"

    # Not found (404)
    res_404 = await client.get(f"/api/v1/tenants/{uuid.uuid4()}")
    assert res_404.status_code == 404

    # Bad UUID (400)
    res_400 = await client.get("/api/v1/tenants/invalid-uuid-string")
    assert res_400.status_code == 400


@pytest.mark.asyncio
async def test_update_tenant(client: AsyncClient):
    """Test partial profile updates (PATCH)."""
    t_id = uuid.uuid4()
    async with async_session_maker() as session:
        tenant = Tenant(
            id=t_id,
            company_name="Original Name LLC",
            preferred_language="english",
            whatsapp_notification_number="+923001112233",
        )
        session.add(tenant)
        await session.commit()

    update_payload = {
        "company_name": "Updated Name LLC",
        "preferred_language": "roman_urdu",
        "whatsapp_notification_number": "+923009990000",
    }
    res = await client.patch(f"/api/v1/tenants/{t_id}", json=update_payload)
    assert res.status_code == 200
    data = res.json()
    assert data["company_name"] == "Updated Name LLC"
    assert data["preferred_language"] == "roman_urdu"
    assert data["whatsapp_notification_number"] == "+923009990000"


@pytest.mark.asyncio
async def test_delete_tenant_cascade(client: AsyncClient):
    """Test tenant deletion cascades to associated ad accounts and metrics snapshots."""
    from app.models.metrics import CampaignMetricsSnapshot
    from datetime import date

    t_id = uuid.uuid4()
    acc_id = uuid.uuid4()
    snap_id = uuid.uuid4()

    async with async_session_maker() as session:
        tenant = Tenant(
            id=t_id,
            company_name="To Be Deleted Brand",
            whatsapp_notification_number="+923004445555",
        )
        session.add(tenant)
        acc = AdAccount(
            id=acc_id,
            tenant_id=t_id,
            platform="META",
            external_account_id="act_del_cascade_1",
            max_budget_ceiling_pkr=10000.0,
        )
        session.add(acc)
        snap = CampaignMetricsSnapshot(
            id=snap_id,
            ad_account_id=acc_id,
            external_campaign_id="camp_cascade_99",
            campaign_name="Cascade Campaign",
            snapshot_date=date.today(),
            spend=5000.0,
            impressions=10000,
            clicks=250,
            conversions=5,
            roas=2.0,
        )
        session.add(snap)
        await session.commit()

    # Delete
    del_res = await client.delete(f"/api/v1/tenants/{t_id}")
    assert del_res.status_code == 200
    assert del_res.json()["status"] == "deleted"

    # Verify tenant, cascaded ad accounts, and cascaded metrics snapshots are all deleted
    async with async_session_maker() as session:
        assert await session.get(Tenant, t_id) is None
        acc_check = await session.execute(select(AdAccount).where(AdAccount.tenant_id == t_id))
        assert acc_check.scalars().first() is None
        snap_check = await session.execute(
            select(CampaignMetricsSnapshot).where(CampaignMetricsSnapshot.id == snap_id)
        )
        assert snap_check.scalars().first() is None
