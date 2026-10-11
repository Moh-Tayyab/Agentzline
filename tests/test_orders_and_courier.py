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
