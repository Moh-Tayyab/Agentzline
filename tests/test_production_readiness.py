"""Production-readiness regression tests (Phases 1-5 verification gates)."""

import uuid
from datetime import date
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.database import async_session_maker
from app.main import app
from app.models.ad_account import AdAccount
from app.models.audit_log import AuditLog
from app.models.credential import PlatformCredential
from app.models.metrics import CampaignMetricsSnapshot
from app.models.order import Order
from app.models.tenant import Tenant


async def _make_tenant(name="Readiness Brand", lang="english", wa="+923001234567"):
    tid = uuid.uuid4()
    async with async_session_maker() as s:
        t = Tenant(
            id=tid, company_name=name, country_code="PK", currency="PKR",
            preferred_language=lang, whatsapp_notification_number=wa,
        )
        s.add(t)
        await s.commit()
    return tid


@pytest.mark.asyncio
async def test_daily_report_includes_cod_reconciliation():
    """Gate 1: run_daily_report_job embeds cod_summary + persists snapshots."""
    from app.agents.scheduler import run_daily_report_job

    tid = await _make_tenant("COD Report Brand")
    aid = uuid.uuid4()
    async with async_session_maker() as s:
        s.add(AdAccount(
            id=aid, tenant_id=tid, platform="META",
            external_account_id="act_cod_ready_1", account_name="COD Main",
            is_active=True, max_budget_ceiling_pkr=100000.0,
        ))
        # Seeded orders: 1 delivered, 1 returned
        s.add_all([
            Order(tenant_id=tid, external_order_id="ORD-COD-1", payment_method="COD",
                  total_amount_pkr=10000.0, cogs_amount_pkr=3000.0,
                  courier_fee_pkr=250.0, campaign_id="camp_cod_1",
                  current_status="DELIVERED"),
            Order(tenant_id=tid, external_order_id="ORD-COD-2", payment_method="COD",
                  total_amount_pkr=6000.0, cogs_amount_pkr=2000.0,
                  courier_fee_pkr=250.0, return_fee_pkr=150.0,
                  campaign_id="camp_cod_1", current_status="RETURNED"),
        ])
        await s.commit()

    insights = [{
        "campaign_id": "camp_cod_1", "campaign_name": "COD Campaign",
        "spend": "5000.00", "impressions": "20000", "clicks": "800",
        "actions": [{"action_type": "purchase", "value": "10"}],
        "action_values": [{"action_type": "purchase", "value": "20000.00"}],
    }]
    with patch("app.agents.graph.MetaGraphClient") as mg, \
         patch("app.agents.graph.WhatsAppClient") as wg:
        mm = AsyncMock()
        mm.get_account_insights.return_value = insights
        mg.return_value = mm
        wm = AsyncMock()
        wg.return_value = wm
        await run_daily_report_job()
        assert wm.send_text_message.await_count >= 1
        sent_text = wm.send_text_message.await_args_list[0].kwargs.get(
            "message_text", "") or wm.send_text_message.await_args_list[0].args[0]
        assert "Real Net Profit & COD Reconciliation" in sent_text

    async with async_session_maker() as s:
        r = await s.execute(select(CampaignMetricsSnapshot).where(
            CampaignMetricsSnapshot.external_campaign_id == "camp_cod_1"))
        assert len(r.scalars().all()) >= 1


@pytest.mark.asyncio
async def test_sync_uses_tenant_vault_token_and_is_idempotent(client):
    """Gate 2: /sync decrypts vault token + upsert is idempotent."""
    from app.core.security import encrypt_token

    tid = await _make_tenant("Sync Vault Brand")
    raw_token = "vault_meta_secret_xyz_123"
    async with async_session_maker() as s:
        acc = AdAccount(tenant_id=tid, platform="META",
                        external_account_id="act_sync_vault_1",
                        account_name="Sync Vault", is_active=True,
                        max_budget_ceiling_pkr=50000.0)
        s.add(acc)
        await s.flush()
        s.add(PlatformCredential(tenant_id=tid, platform_name="META",
                                 encrypted_access_token=encrypt_token(raw_token),
                                 token_status="ACTIVE"))
        await s.commit()

    insights = [{
        "campaign_id": "camp_vault_1", "campaign_name": "Vault Camp",
        "spend": "4500.00", "impressions": "20000", "clicks": "800",
        "actions": [{"action_type": "purchase", "value": "15"}],
        "action_values": [{"action_type": "purchase", "value": "13500.00"}],
    }]
    with patch("app.api.endpoints.meta_accounts.MetaGraphClient") as mc:
        mi = AsyncMock()
        mi.get_account_insights.return_value = insights
        mc.return_value = mi
        r1 = await client.post("/api/v1/meta/accounts/act_sync_vault_1/sync")
        assert r1.status_code == 200
        # Vault token used
        assert mc.call_args is not None
        assert mc.call_args.kwargs.get("access_token") == raw_token
        r2 = await client.post("/api/v1/meta/accounts/act_sync_vault_1/sync")
        assert r2.status_code == 200

    async with async_session_maker() as s:
        today = date.today()
        r = await s.execute(select(CampaignMetricsSnapshot).where(
            CampaignMetricsSnapshot.external_campaign_id == "camp_vault_1",
            CampaignMetricsSnapshot.snapshot_date == today))
        assert len(r.scalars().all()) == 1


@pytest.mark.asyncio
async def test_api_key_authentication_and_tenant_isolation(monkeypatch):
    """Gate 4: 401 unauthenticated, 403 cross-tenant, 200 valid."""
    from app.core.config import get_settings
    from app.core.security import generate_tenant_api_key, hash_api_key

    settings = get_settings()
    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr(settings, "ADMIN_API_KEY", "test-admin-key-1234567890")

    ta = await _make_tenant("Tenant A Iso")
    tb = await _make_tenant("Tenant B Iso")
    raw_a, hash_a = generate_tenant_api_key()
    raw_b, _ = generate_tenant_api_key()
    async with async_session_maker() as s:
        ra = await s.execute(select(Tenant).where(Tenant.id == ta))
        ra.scalars().first().api_key_hash = hash_a
        rb = await s.execute(select(Tenant).where(Tenant.id == tb))
        rb.scalars().first().api_key_hash = hash_api_key(raw_b)
        await s.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get(f"/api/v1/orders?tenant_id={ta}")
        assert r.status_code == 401
        r2 = await c.get(f"/api/v1/orders?tenant_id={tb}",
                         headers={"X-API-Key": raw_a})
        assert r2.status_code == 403
        r3 = await c.get(f"/api/v1/orders?tenant_id={ta}",
                         headers={"X-API-Key": raw_a})
        assert r3.status_code == 200
        r4 = await c.get(f"/api/v1/orders?tenant_id={tb}",
                         headers={"X-API-Key": "test-admin-key-1234567890"})
        assert r4.status_code == 200


@pytest.mark.asyncio
async def test_courier_webhook_tenant_isolation():
    """Gate 5: scoped webhook never mutates sibling tenant order."""
    ta = await _make_tenant("Courier A", wa="+923001111111")
    tb = await _make_tenant("Courier B", wa="+923002222222")
    async with async_session_maker() as s:
        s.add_all([
            Order(tenant_id=ta, external_order_id="1001", payment_method="COD",
                  total_amount_pkr=5000.0, current_status="PENDING"),
            Order(tenant_id=tb, external_order_id="1001", payment_method="COD",
                  total_amount_pkr=5000.0, current_status="PENDING"),
        ])
        await s.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post(f"/api/v1/courier/webhook/postex?tenant_id={tb}",
                         json={"trackingNumber": "PE-ISO-1", "orderRefNumber": "1001",
                               "transactionStatus": "Delivered"})
        assert r.status_code == 200
        assert r.json()["status"] == "processed"

    async with async_session_maker() as s:
        ra = await s.execute(select(Order).where(Order.tenant_id == ta,
                                                 Order.external_order_id == "1001"))
        rb = await s.execute(select(Order).where(Order.tenant_id == tb,
                                                 Order.external_order_id == "1001"))
        assert ra.scalars().first().current_status == "PENDING"
        assert rb.scalars().first().current_status == "DELIVERED"


@pytest.mark.asyncio
async def test_direct_pause_endpoint_and_nonce_uniqueness():
    """Gate 8a: POST /actions/pause works + replay rejected."""
    from app.skills.hitl_action_tokens import generate_action_token

    tid = await _make_tenant("HITL Direct Brand")
    token = generate_action_token(str(tid), "camp_hitl_1", "PAUSE", ttl_seconds=600)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        with patch("app.utils.meta_client.MetaGraphClient") as mc:
            mi = AsyncMock()
            mi.update_campaign_status.return_value = {"success": True}
            mc.return_value = mi
            r1 = await c.post("/api/v1/actions/pause", json={"token": token})
            assert r1.status_code == 200, r1.text
            assert r1.json()["status"] == "paused"
            r2 = await c.post("/api/v1/actions/pause", json={"token": token})
            assert r2.status_code == 409

    async with async_session_maker() as s:
        r = await s.execute(select(AuditLog).where(AuditLog.tenant_id == tid))
        logs = r.scalars().all()
        assert any(getattr(lg, "token_nonce", None) for lg in logs)


@pytest.mark.asyncio
async def test_order_auto_populates_sku_cogs():
    """Gate 7: SKU COGS auto-fill + duplicate external_order_id upsert."""
    from app.models.product_cost import ProductCost

    tid = await _make_tenant("SKU COGS Brand")
    async with async_session_maker() as s:
        s.add(ProductCost(tenant_id=tid, sku="SKU-1", product_name="Test",
                          cost_price_pkr=1200.0))
        await s.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/api/v1/orders", json={
            "tenant_id": str(tid), "external_order_id": "ORD-SKU-1",
            "total_amount_pkr": 5000.0, "cogs_amount_pkr": 0,
            "sku": "SKU-1", "quantity": 2})
        assert r.status_code == 201, r.text
        assert r.json()["cogs_amount_pkr"] == 2400.0
        r2 = await c.post("/api/v1/orders", json={
            "tenant_id": str(tid), "external_order_id": "ORD-SKU-1",
            "total_amount_pkr": 5000.0, "cogs_amount_pkr": 0,
            "sku": "SKU-1", "quantity": 2,
            "tracking_number": "PE-DUP-1"})
        assert r2.status_code == 201

    async with async_session_maker() as s:
        r = await s.execute(select(Order).where(Order.tenant_id == tid,
                                                Order.external_order_id == "ORD-SKU-1"))
        assert len(r.scalars().all()) == 1
