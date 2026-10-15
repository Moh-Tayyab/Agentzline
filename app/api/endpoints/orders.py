"""
Orders and Product Costs Management Endpoints (Phase-4 Gold Tier).

Allows merchants to sync orders, register product COGS by SKU,
and view true net profit accounting for COD return rates (RTO).
"""

import uuid
from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session_maker, get_db
from app.core.security import enforce_tenant_access, verify_api_key_dependency
from app.models.order import Order
from app.models.product_cost import ProductCost
from app.models.tenant import Tenant
from app.schemas.order import (
    OrderCreate,
    OrderResponse,
    ProductCostCreate,
    ProductCostResponse,
)
from app.skills.campaign_pnl import fetch_and_compute_tenant_pnl
from app.skills.courier_normalizer import compute_net_order_profit

router = APIRouter()


@router.post("", response_model=OrderResponse, status_code=status.HTTP_201_CREATED)
async def create_order(
    payload: OrderCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(verify_api_key_dependency),
) -> OrderResponse:
    """Ingest a new order with attribution and COD financial details (idempotent)."""
    enforce_tenant_access(request, payload.tenant_id)
    async with async_session_maker() as session:
        # Check tenant exists
        t_res = await session.execute(select(Tenant).where(Tenant.id == payload.tenant_id))
        if t_res.scalars().first() is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Tenant {payload.tenant_id} not found",
            )

        # Idempotency: upsert on (tenant_id, external_order_id)
        existing_res = await session.execute(
            select(Order).where(
                Order.tenant_id == payload.tenant_id,
                Order.external_order_id == payload.external_order_id,
            )
        )
        existing = existing_res.scalars().first()
        # Auto-lookup SKU COGS when not supplied
        resolved_cogs = payload.cogs_amount_pkr
        if (not resolved_cogs or resolved_cogs == 0.0) and payload.sku:
            cost_res = await session.execute(
                select(ProductCost).where(
                    ProductCost.tenant_id == payload.tenant_id,
                    ProductCost.sku == payload.sku,
                )
            )
            cost_row = cost_res.scalars().first()
            if cost_row is not None:
                resolved_cogs = float(cost_row.cost_price_pkr) * int(payload.quantity or 1)

        if existing:
            # Update mutable fields idempotently
            existing.order_number = payload.order_number or existing.order_number
            existing.customer_phone = payload.customer_phone or existing.customer_phone
            existing.city = payload.city or existing.city
            existing.payment_method = payload.payment_method.upper()
            existing.total_amount_pkr = payload.total_amount_pkr
            existing.cogs_amount_pkr = resolved_cogs
            existing.courier_fee_pkr = payload.courier_fee_pkr
            existing.return_fee_pkr = payload.return_fee_pkr
            if payload.tracking_number:
                existing.tracking_number = payload.tracking_number
            if payload.courier_name:
                existing.courier_name = payload.courier_name
            if payload.campaign_id:
                existing.campaign_id = payload.campaign_id
            if payload.ad_id:
                existing.ad_id = payload.ad_id
            if payload.utm_source:
                existing.utm_source = payload.utm_source
            if payload.utm_medium:
                existing.utm_medium = payload.utm_medium
            if payload.utm_campaign:
                existing.utm_campaign = payload.utm_campaign
            if payload.fbclid:
                existing.fbclid = payload.fbclid
            await session.commit()
            await session.refresh(existing)
            logger.info(f"♻️ Idempotent order upsert {existing.external_order_id} for tenant {existing.tenant_id}")
            return OrderResponse.model_validate(existing)

        order = Order(
            tenant_id=payload.tenant_id,
            external_order_id=payload.external_order_id,
            order_number=payload.order_number or payload.external_order_id,
            customer_phone=payload.customer_phone,
            city=payload.city,
            payment_method=payload.payment_method.upper(),
            total_amount_pkr=payload.total_amount_pkr,
            cogs_amount_pkr=resolved_cogs,
            courier_fee_pkr=payload.courier_fee_pkr,
            return_fee_pkr=payload.return_fee_pkr,
            courier_name=payload.courier_name,
            tracking_number=payload.tracking_number,
            campaign_id=payload.campaign_id,
            ad_id=payload.ad_id,
            utm_source=payload.utm_source,
            utm_medium=payload.utm_medium,
            utm_campaign=payload.utm_campaign,
            fbclid=payload.fbclid,
        )
        session.add(order)
        await session.commit()
        await session.refresh(order)
        logger.info(f"🛒 Created order {order.external_order_id} for tenant {order.tenant_id}")
        return OrderResponse.model_validate(order)


@router.get("", response_model=list[OrderResponse])
async def list_orders(
    request: Request,
    tenant_id: uuid.UUID = Query(...),
    db: AsyncSession = Depends(get_db),
    _auth=Depends(verify_api_key_dependency),
) -> list[OrderResponse]:
    """List orders for a tenant."""
    enforce_tenant_access(request, tenant_id)
    async with async_session_maker() as session:
        res = await session.execute(
            select(Order).where(Order.tenant_id == tenant_id).order_by(Order.created_at.desc())
        )
        orders = res.scalars().all()
        return [OrderResponse.model_validate(o) for o in orders]


@router.get("/pnl")
async def get_tenant_campaign_pnl(
    request: Request,
    tenant_id: uuid.UUID = Query(...),
    date_start: date | None = Query(default=None),
    date_end: date | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _auth=Depends(verify_api_key_dependency),
) -> dict[str, Any]:
    """
    Get aggregated Campaign P&L, COD delivery reconciliation, and net pocket margins.
    Defaults to last 30 days if date_start/date_end are omitted.
    """
    enforce_tenant_access(request, tenant_id)
    end = date_end or date.today()
    start = date_start or (end - timedelta(days=30))
    if start > end:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="date_start cannot be after date_end",
        )

    async with async_session_maker() as session:
        t_res = await session.execute(select(Tenant).where(Tenant.id == tenant_id))
        if t_res.scalars().first() is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Tenant {tenant_id} not found",
            )
        pnl_data = await fetch_and_compute_tenant_pnl(
            session=session,
            tenant_id=tenant_id,
            start_date=start,
            end_date=end,
        )
        return {
            "tenant_id": str(tenant_id),
            "date_start": str(start),
            "date_end": str(end),
            **pnl_data,
        }


@router.get("/{order_id}/profit")
async def get_order_profit(
    order_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(verify_api_key_dependency),
) -> dict[str, Any]:
    """
    Compute true net profit for an order accounting for delivery state,
    COGS, and courier delivery / RTO return fees.
    """
    async with async_session_maker() as session:
        res = await session.execute(select(Order).where(Order.id == order_id))
        order = res.scalars().first()
        if order is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Order {order_id} not found",
            )
        enforce_tenant_access(request, order.tenant_id)

        profit_summary = compute_net_order_profit(
            status=order.current_status,
            total_amount_pkr=order.total_amount_pkr,
            cogs_amount_pkr=order.cogs_amount_pkr,
            courier_fee_pkr=order.courier_fee_pkr,
            return_fee_pkr=order.return_fee_pkr,
        )
        return {
            "order_id": str(order.id),
            "external_order_id": order.external_order_id,
            "campaign_id": order.campaign_id,
            **profit_summary,
        }


@router.post("/product-costs", response_model=ProductCostResponse, status_code=status.HTTP_201_CREATED)
async def upsert_product_cost(
    payload: ProductCostCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(verify_api_key_dependency),
) -> ProductCostResponse:
    """Set or update Cost of Goods Sold (COGS) for a product SKU."""
    enforce_tenant_access(request, payload.tenant_id)
    async with async_session_maker() as session:
        res = await session.execute(
            select(ProductCost).where(
                ProductCost.tenant_id == payload.tenant_id,
                ProductCost.sku == payload.sku,
            )
        )
        existing = res.scalars().first()

        if existing:
            existing.product_name = payload.product_name or existing.product_name
            existing.cost_price_pkr = payload.cost_price_pkr
            if payload.selling_price_pkr is not None:
                existing.selling_price_pkr = payload.selling_price_pkr
            await session.commit()
            await session.refresh(existing)
            logger.info(f"🏷️ Updated COGS for SKU {existing.sku}: {existing.cost_price_pkr} PKR")
            return ProductCostResponse.model_validate(existing)

        item = ProductCost(
            tenant_id=payload.tenant_id,
            sku=payload.sku,
            product_name=payload.product_name,
            cost_price_pkr=payload.cost_price_pkr,
            selling_price_pkr=payload.selling_price_pkr,
        )
        session.add(item)
        await session.commit()
        await session.refresh(item)
        logger.info(f"🏷️ Registered COGS for SKU {item.sku}: {item.cost_price_pkr} PKR")
        return ProductCostResponse.model_validate(item)


@router.get("/product-costs", response_model=list[ProductCostResponse])
async def list_product_costs(
    request: Request,
    tenant_id: uuid.UUID = Query(...),
    db: AsyncSession = Depends(get_db),
    _auth=Depends(verify_api_key_dependency),
) -> list[ProductCostResponse]:
    """List product SKUs and COGS for a tenant."""
    enforce_tenant_access(request, tenant_id)
    async with async_session_maker() as session:
        res = await session.execute(
            select(ProductCost).where(ProductCost.tenant_id == tenant_id)
        )
        items = res.scalars().all()
        return [ProductCostResponse.model_validate(i) for i in items]
