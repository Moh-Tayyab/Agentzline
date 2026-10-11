"""
Tests for Phase-4 Gold Tier: Orders, Product Costs, and PostEx Courier Webhook.
"""

import uuid
from decimal import Decimal
from datetime import datetime, timezone
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.database import async_session_maker
from app.main import app
from app.models.audit_log import AuditLog
from app.models.order import CourierEvent, Order
from app.models.product_cost import ProductCost
from app.models.tenant import Tenant
from app.skills.courier_normalizer import (
    compute_net_order_profit,
    normalize_courier_status,
    parse_postex_webhook_payload,
)


class TestCourierNormalizer:
    def test_postex_status_string_mapping(self):
        assert normalize_courier_status("POSTEX", "Order Placed") == "BOOKED"
        assert normalize_courier_status("POSTEX", "Picked Up") == "IN_TRANSIT"
        assert normalize_courier_status("POSTEX", "In Transit") == "IN_TRANSIT"
        assert normalize_courier_status("POSTEX", "Out for Delivery") == "OUT_FOR_DELIVERY"
        assert normalize_courier_status("POSTEX", "Delivered") == "DELIVERED"
        assert normalize_courier_status("POSTEX", "Delivered to Customer") == "DELIVERED"
        assert normalize_courier_status("POSTEX", "Returned to Merchant") == "RETURNED"
        assert normalize_courier_status("POSTEX", "RTO") == "RETURNED"
        assert normalize_courier_status("POSTEX", "Cancelled") == "CANCELLED"

    def test_postex_status_code_mapping(self):
        assert normalize_courier_status("POSTEX", 1) == "BOOKED"
        assert normalize_courier_status("POSTEX", "2") == "IN_TRANSIT"
        assert normalize_courier_status("POSTEX", 3) == "OUT_FOR_DELIVERY"
        assert normalize_courier_status("POSTEX", 4) == "DELIVERED"
        assert normalize_courier_status("POSTEX", 5) == "RETURNED"
        assert normalize_courier_status("POSTEX", 6) == "CANCELLED"
        assert normalize_courier_status("POSTEX", 99) == "UNKNOWN"

    def test_parse_postex_webhook_payload(self):
        payload = {
            "trackingNumber": "PE-889900",
            "orderRefNumber": "ORD-5544",
            "transactionStatus": "Delivered",
            "invoiceDeliveryCharges": "230.50",
            "invoiceReturnCharges": "0",
            "transactionTimestamp": "2026-10-11T12:00:00Z",
        }
        res = parse_postex_webhook_payload(payload)
        assert res["tracking_number"] == "PE-889900"
        assert res["order_reference"] == "ORD-5544"
        assert res["normalized_status"] == "DELIVERED"
        assert res["delivery_charges"] == Decimal("230.50")
        assert res["return_charges"] == Decimal("0.00")


class TestNetOrderProfitCalculation:
    def test_delivered_order_profit(self):
        # 5,000 gross revenue, 1,500 COGS, 250 delivery fee, 500 Meta ad spend
        res = compute_net_order_profit(
            status="DELIVERED",
            total_amount_pkr=5000.0,
            cogs_amount_pkr=1500.0,
            courier_fee_pkr=250.0,
            return_fee_pkr=0.0,
            allocated_ad_spend_pkr=500.0,
        )
        assert res["is_profitable"] is True
        assert res["delivered_revenue"] == 5000.0
        assert res["net_profit"] == 2750.0  # 5000 - 1500 - 250 - 500
        assert res["margin_percentage"] == 55.0

    def test_returned_order_loss_rto(self):
        # RTO returns: 0 revenue, 250 delivery fee + 150 return fee + 500 ad spend = 900 loss
        res = compute_net_order_profit(
            status="RETURNED",
            total_amount_pkr=5000.0,
            cogs_amount_pkr=1500.0,
            courier_fee_pkr=250.0,
            return_fee_pkr=150.0,
            allocated_ad_spend_pkr=500.0,
        )
        assert res["is_profitable"] is False
        assert res["delivered_revenue"] == 0.0
        assert res["net_profit"] == -900.0
        assert res["courier_fees"] == 400.0


@pytest.fixture
async def courier_test_tenant():
    t_id = uuid.uuid4()
    async with async_session_maker() as session:
        tenant = Tenant(
            id=t_id,
            company_name="Courier Brand PK",
            country_code="PK",
            currency="PKR",
            preferred_language="roman_urdu",
            whatsapp_notification_number="+923007778899",
        )
        session.add(tenant)
        await session.commit()
    return tenant


@pytest.mark.asyncio
async def test_orders_api_lifecycle(courier_test_tenant):
    """Test order creation, attribution, and profit calculation endpoints."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Create order
        create_payload = {
            "tenant_id": str(courier_test_tenant.id),
            "external_order_id": "ORD-PKG-1001",
            "order_number": "1001",
            "customer_phone": "+923211112233",
            "city": "Lahore",
            "payment_method": "COD",
            "total_amount_pkr": 4200.0,
            "cogs_amount_pkr": 1400.0,
            "courier_fee_pkr": 220.0,
            "tracking_number": "PE-1001-XYZ",
            "campaign_id": "meta_camp_lawn_sale",
            "utm_campaign": "lawn_summer_2026",
            "fbclid": "fb.1.test_click_id",
        }
        res = await client.post("/api/v1/orders", json=create_payload)
        assert res.status_code == 201
        data = res.json()
        order_id = data["id"]
        assert data["external_order_id"] == "ORD-PKG-1001"
        assert data["current_status"] == "PENDING"
        assert data["campaign_id"] == "meta_camp_lawn_sale"

        # 2. List orders
        list_res = await client.get(f"/api/v1/orders?tenant_id={courier_test_tenant.id}")
        assert list_res.status_code == 200
        assert len(list_res.json()) >= 1

        # 3. Check profit for pending order
        profit_res = await client.get(f"/api/v1/orders/{order_id}/profit")
        assert profit_res.status_code == 200
        prof = profit_res.json()
        assert prof["delivered_revenue"] == 0.0
        assert prof["status"] == "PENDING"


@pytest.mark.asyncio
async def test_product_costs_api(courier_test_tenant):
    """Test product COGS upsert and list."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Create COGS
        cost_payload = {
            "tenant_id": str(courier_test_tenant.id),
            "sku": "SKU-KURTI-BLUE-M",
            "product_name": "Embroidered Kurti Blue Medium",
            "cost_price_pkr": 950.0,
            "selling_price_pkr": 2500.0,
        }
        res = await client.post("/api/v1/orders/product-costs", json=cost_payload)
        assert res.status_code == 201
        assert res.json()["cost_price_pkr"] == 950.0

        # Update COGS (upsert same SKU)
        cost_payload["cost_price_pkr"] = 990.0
        res2 = await client.post("/api/v1/orders/product-costs", json=cost_payload)
        assert res2.status_code == 201
        assert res2.json()["cost_price_pkr"] == 990.0

        # List COGS
        res3 = await client.get(f"/api/v1/orders/product-costs?tenant_id={courier_test_tenant.id}")
        assert res3.status_code == 200
        assert any(item["sku"] == "SKU-KURTI-BLUE-M" for item in res3.json())


@pytest.mark.asyncio
async def test_postex_webhook_marks_delivered(courier_test_tenant):
    """PostEx Delivered webhook updates order, sets delivered_at, logs event and audit."""
    o_id = uuid.uuid4()
    tracking = "PE-DELIV-999"

    async with async_session_maker() as session:
        order = Order(
            id=o_id,
            tenant_id=courier_test_tenant.id,
            external_order_id="ORD-999",
            payment_method="COD",
            total_amount_pkr=6000.0,
            cogs_amount_pkr=2000.0,
            tracking_number=tracking,
            courier_name="POSTEX",
            current_status="IN_TRANSIT",
        )
        session.add(order)
        await session.commit()

    webhook_payload = {
        "trackingNumber": tracking,
        "orderRefNumber": "ORD-999",
        "transactionStatus": "Delivered to Customer",
        "invoiceDeliveryCharges": "250.00",
        "invoiceReturnCharges": "0",
    }

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post("/api/v1/courier/webhook/postex", json=webhook_payload)
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "processed"
        assert data["normalized_status"] == "DELIVERED"

    # Verify DB state
    async with async_session_maker() as session:
        r = await session.execute(select(Order).where(Order.id == o_id))
        updated_order = r.scalars().first()
        assert updated_order.current_status == "DELIVERED"
        assert updated_order.delivered_at is not None
        assert updated_order.courier_fee_pkr == 250.0

        # Verify CourierEvent was added
        ev_r = await session.execute(select(CourierEvent).where(CourierEvent.order_id == o_id))
        events = ev_r.scalars().all()
        assert len(events) == 1
        assert events[0].normalized_status == "DELIVERED"

        # Verify AuditLog was recorded
        aud_r = await session.execute(
            select(AuditLog).where(
                AuditLog.action_type == "COURIER_STATUS_UPDATED",
                AuditLog.tenant_id == courier_test_tenant.id,
            )
        )
        auds = aud_r.scalars().all()
        assert len(auds) == 1
        assert auds[0].action_details.get("status") == "DELIVERED"


@pytest.mark.asyncio
async def test_postex_webhook_marks_returned_rto(courier_test_tenant):
    """PostEx RTO webhook updates order to RETURNED, sets return fees, logs event and audit."""
    o_id = uuid.uuid4()
    tracking = "PE-RTO-777"

    async with async_session_maker() as session:
        order = Order(
            id=o_id,
            tenant_id=courier_test_tenant.id,
            external_order_id="ORD-777",
            payment_method="COD",
            total_amount_pkr=3500.0,
            cogs_amount_pkr=1100.0,
            tracking_number=tracking,
            courier_name="POSTEX",
            current_status="IN_TRANSIT",
        )
        session.add(order)
        await session.commit()

    webhook_payload = {
        "trackingNumber": tracking,
        "orderRefNumber": "ORD-777",
        "transactionStatus": "Returned to Merchant",
        "invoiceDeliveryCharges": "220.00",
        "invoiceReturnCharges": "140.00",
    }

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post("/api/v1/courier/webhook/postex", json=webhook_payload)
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "processed"
        assert data["normalized_status"] == "RETURNED"

    # Verify DB state
    async with async_session_maker() as session:
        r = await session.execute(select(Order).where(Order.id == o_id))
        updated_order = r.scalars().first()
        assert updated_order.current_status == "RETURNED"
        assert updated_order.returned_at is not None
        assert updated_order.courier_fee_pkr == 220.0
        assert updated_order.return_fee_pkr == 140.0


@pytest.mark.asyncio
async def test_trax_and_leopards_and_swyft_webhooks(courier_test_tenant):
    """Test webhooks for Trax, Leopards, and Swyft updating order lifecycles."""
    o1_id = uuid.uuid4()
    o2_id = uuid.uuid4()
    o3_id = uuid.uuid4()

    async with async_session_maker() as session:
        session.add_all([
            Order(
                id=o1_id,
                tenant_id=courier_test_tenant.id,
                external_order_id="ORD-TRX-1",
                payment_method="COD",
                total_amount_pkr=3000.0,
                tracking_number="TRX-101",
                current_status="IN_TRANSIT",
            ),
            Order(
                id=o2_id,
                tenant_id=courier_test_tenant.id,
                external_order_id="ORD-LEO-2",
                payment_method="COD",
                total_amount_pkr=4000.0,
                tracking_number="LEO-202",
                current_status="IN_TRANSIT",
            ),
            Order(
                id=o3_id,
                tenant_id=courier_test_tenant.id,
                external_order_id="ORD-SWYFT-3",
                payment_method="COD",
                total_amount_pkr=5000.0,
                tracking_number="SWYFT-303",
                current_status="IN_TRANSIT",
            ),
        ])
        await session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Trax Delivered
        r1 = await client.post("/api/v1/courier/webhook/trax", json={
            "tracking_number": "TRX-101",
            "order_id": "ORD-TRX-1",
            "status": "delivered",
            "charges": 210.0,
        })
        assert r1.status_code == 200
        assert r1.json()["normalized_status"] == "DELIVERED"

        # 2. Leopards Delivered
        r2 = await client.post("/api/v1/courier/webhook/leopards", json={
            "consignment_no": "LEO-202",
            "booked_packet_order_id": "ORD-LEO-2",
            "status": "delivered",
            "delivery_charges": 240.0,
        })
        assert r2.status_code == 200
        assert r2.json()["normalized_status"] == "DELIVERED"

        # 3. Swyft Returned
        r3 = await client.post("/api/v1/courier/webhook/swyft", json={
            "tracking_code": "SWYFT-303",
            "reference_id": "ORD-SWYFT-3",
            "status": "returned",
            "shipping_fee": 190.0,
            "return_fee": 120.0,
        })
        assert r3.status_code == 200
        assert r3.json()["normalized_status"] == "RETURNED"


@pytest.mark.asyncio
async def test_campaign_pnl_aggregator_endpoint(courier_test_tenant):
    """Test full Campaign P&L API aggregating ad spend and COD fulfillment."""
    from datetime import date
    from app.models.ad_account import AdAccount
    from app.models.metrics import CampaignMetricsSnapshot

    acc_id = uuid.uuid4()
    async with async_session_maker() as session:
        acc = AdAccount(
            id=acc_id,
            tenant_id=courier_test_tenant.id,
            platform="META",
            external_account_id="act_pnl_test",
            max_budget_ceiling_pkr=100000.0,
            is_active=True,
        )
        session.add(acc)
        await session.flush()

        # Ad spend for campaign 'c_lawn_01'
        today_d = date.today()
        snap = CampaignMetricsSnapshot(
            ad_account_id=acc_id,
            external_campaign_id="c_lawn_01",
            campaign_name="Summer Lawn Sale 2026",
            snapshot_date=today_d,
            spend=5000.0,
            impressions=20000,
            clicks=400,
            conversions=8,
            roas=3.5,
        )
        session.add(snap)

        # Attributed delivered order
        o1 = Order(
            tenant_id=courier_test_tenant.id,
            external_order_id="ORD-ATTRIB-1",
            campaign_id="c_lawn_01",
            payment_method="COD",
            total_amount_pkr=12000.0,
            cogs_amount_pkr=4000.0,
            courier_fee_pkr=300.0,
            current_status="DELIVERED",
        )
        # Attributed returned order
        o2 = Order(
            tenant_id=courier_test_tenant.id,
            external_order_id="ORD-ATTRIB-2",
            campaign_id="c_lawn_01",
            payment_method="COD",
            total_amount_pkr=6000.0,
            cogs_amount_pkr=2000.0,
            courier_fee_pkr=300.0,
            return_fee_pkr=150.0,
            current_status="RETURNED",
        )
        session.add_all([o1, o2])
        await session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get(f"/api/v1/orders/pnl?tenant_id={courier_test_tenant.id}")
        assert res.status_code == 200
        data = res.json()
        assert len(data["campaigns"]) == 1
        c_stat = data["campaigns"][0]
        assert c_stat["campaign_id"] == "c_lawn_01"
        assert c_stat["ad_spend"] == 5000.0
        assert c_stat["delivered_orders"] == 1
        assert c_stat["returned_orders"] == 1
        assert c_stat["delivery_rate_pct"] == 50.0
        assert c_stat["delivered_revenue"] == 12000.0
        # Net profit = 12000 - 4000 (cogs) - (300+450 fees) - 5000 spend = 2250
        assert c_stat["net_profit"] == 2250.0
        assert c_stat["is_profitable"] is True


def test_bilingual_daily_report_with_cod_summary():
    """Verify bilingual report formats COD section cleanly when cod_summary is supplied."""
    from app.skills.bilingual_report import format_daily_summary

    summary = {
        "account_name": "Gul Ahmed PK",
        "date": "2026-10-11",
        "total_spend": 20000.0,
        "total_impressions": 50000,
        "total_clicks": 1200,
        "total_conversions": 25,
        "aggregate_roas": 3.8,
        "aggregate_ctr": 2.4,
    }
    cod_summary = {
        "total_orders": 30,
        "total_delivered_orders": 24,
        "total_returned_orders": 6,
        "blended_delivery_rate_pct": 80.0,
        "total_delivered_revenue": 76000.0,
        "total_courier_fees": 6200.0,
        "total_net_profit": 28500.0,
        "blended_real_roas": 3.8,
    }

    # Roman Urdu
    ru = format_daily_summary(summary, anomalies=[], language="roman_urdu", cod_summary=cod_summary)
    assert "Real Net Profit & COD Reconciliation" in ru
    assert "76,000 PKR" in ru
    assert "80.0%" in ru
    assert "Pocket Net Margin" in ru

    # English
    en = format_daily_summary(summary, anomalies=[], language="english", cod_summary=cod_summary)
    assert "Real Net Profit & COD Reconciliation" in en
    assert "Delivered Cash" in en
    assert "76,000 PKR" in en


@pytest.mark.asyncio
class TestCourierWebhookAuthentication:
    """Verify security guardrails on courier endpoints with shared secret."""

    async def test_webhook_unauthorized_when_secret_set_and_missing_in_request(self, monkeypatch):
        from app.core.config import get_settings

        settings = get_settings()
        monkeypatch.setattr(settings, "COURIER_WEBHOOK_SECRET", "test_vault_secret_999")

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            res = await client.post(
                "/api/v1/courier/webhook/postex",
                json={"trackingNumber": "T-1", "transactionStatus": "Delivered"},
            )
            assert res.status_code == 401
            assert "Invalid or missing courier webhook secret" in res.json()["detail"]

    async def test_webhook_unauthorized_on_wrong_secret(self, monkeypatch):
        from app.core.config import get_settings

        settings = get_settings()
        monkeypatch.setattr(settings, "COURIER_WEBHOOK_SECRET", "test_vault_secret_999")

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            res = await client.post(
                "/api/v1/courier/webhook/postex",
                headers={"X-Webhook-Secret": "wrong_value"},
                json={"trackingNumber": "T-1", "transactionStatus": "Delivered"},
            )
            assert res.status_code == 401

    async def test_webhook_authorized_via_header_or_bearer_or_query(self, monkeypatch):
        from app.core.config import get_settings

        settings = get_settings()
        monkeypatch.setattr(settings, "COURIER_WEBHOOK_SECRET", "test_vault_secret_999")

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # 1. Via X-Webhook-Secret
            res1 = await client.post(
                "/api/v1/courier/webhook/postex",
                headers={"X-Webhook-Secret": "test_vault_secret_999"},
                json={"trackingNumber": "UNKNOWN-99", "transactionStatus": "Delivered"},
            )
            assert res1.status_code == 200

            # 2. Via Authorization: Bearer
            res2 = await client.post(
                "/api/v1/courier/webhook/trax",
                headers={"Authorization": "Bearer test_vault_secret_999"},
                json={"tracking_number": "UNKNOWN-99", "status": "Delivered"},
            )
            assert res2.status_code == 200

            # 3. Via Query param ?secret=
            res3 = await client.post(
                "/api/v1/courier/webhook/leopards?secret=test_vault_secret_999",
                json={"track_id": "UNKNOWN-99", "status": "Delivered"},
            )
            assert res3.status_code == 200

