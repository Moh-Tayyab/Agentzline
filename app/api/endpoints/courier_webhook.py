"""
Courier Webhook Receiver (Phase-4 Gold Tier).

Ingests real-time order delivery status updates from Pakistani couriers
(starting with PostEx MVP) and updates order fulfillment & COD reconciliation.
"""

import hmac
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, status
from loguru import logger
from sqlalchemy import or_, select

from app.core.config import get_settings
from app.core.database import async_session_maker
from app.models.audit_log import AuditLog
from app.models.order import CourierEvent, Order
from app.schemas.order import CourierWebhookResponse
from app.skills.courier_normalizer import (
    parse_leopards_webhook_payload,
    parse_postex_webhook_payload,
    parse_swyft_webhook_payload,
    parse_trax_webhook_payload,
)

router = APIRouter()


def _tenant_from_header(request: Request) -> uuid.UUID | None:
    """Extract tenant UUID from X-Tenant-Id header if present."""
    raw = request.headers.get("X-Tenant-Id") or request.headers.get("x-tenant-id")
    if not raw:
        return None
    try:
        return uuid.UUID(raw.strip())
    except ValueError:
        return None


def verify_courier_webhook_secret(request: Request) -> None:
    """
    Verify incoming webhook request contains valid shared secret.
    If COURIER_WEBHOOK_SECRET is set, enforces 401 Unauthorized on mismatch.
    Checks:
    1. Headers: X-Webhook-Secret, X-Api-Key
    2. Authorization: Bearer <secret>
    3. Query parameter: ?secret= or ?token=
    """
    settings = get_settings()
    configured_secret = settings.COURIER_WEBHOOK_SECRET
    if not configured_secret:
        if settings.APP_ENV.lower() == "production":
            logger.error("❌ COURIER_WEBHOOK_SECRET not configured in production — rejecting webhook")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Courier webhook secret not configured",
            )
        return

    incoming_secret = (
        request.headers.get("X-Webhook-Secret")
        or request.headers.get("X-Api-Key")
        or request.headers.get("x-webhook-secret")
        or request.headers.get("x-api-key")
    )
    if incoming_secret and hmac.compare_digest(incoming_secret, configured_secret):
        return

    auth_header = request.headers.get("Authorization") or request.headers.get("authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
        if hmac.compare_digest(token, configured_secret):
            return

    query_secret = request.query_params.get("secret") or request.query_params.get("token")
    if query_secret and hmac.compare_digest(query_secret, configured_secret):
        return

    logger.warning("🚨 Unauthorized courier webhook attempt rejected — invalid or missing secret")
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or missing courier webhook secret",
    )


async def _process_courier_lifecycle(
    courier_name: str,
    parsed: dict[str, Any],
    raw_payload: dict[str, Any],
    tenant_id: uuid.UUID | None = None,
) -> CourierWebhookResponse:
    """Shared database order transition, courier event logging, and audit tracking."""
    tracking = parsed["tracking_number"]
    order_ref = parsed["order_reference"]
    norm_status = parsed["normalized_status"]

    logger.info(
        f"📦 {courier_name} webhook received: tracking='{tracking}', ref='{order_ref}', status={norm_status}"
    )

    if not tracking and not order_ref:
        return CourierWebhookResponse(
            status="missing_identifiers",
            courier=courier_name,
        )

    async with async_session_maker() as session:
        conditions = []
        if tracking:
            conditions.append(Order.tracking_number == tracking)
        if order_ref:
            conditions.append(Order.external_order_id == order_ref)
            conditions.append(Order.order_number == order_ref)

        query = select(Order).where(or_(*conditions))
        if tenant_id is not None:
            query = query.where(Order.tenant_id == tenant_id)
        result = await session.execute(query)
        orders = result.scalars().all()

        if not orders:
            logger.warning(
                f"⚠️ Order not found for {courier_name} update (tracking: {tracking}, ref: {order_ref})"
            )
            return CourierWebhookResponse(
                status="order_not_found",
                courier=courier_name,
                tracking_number=tracking,
                normalized_status=norm_status,
            )

        # Tenant isolation: never mutate another brand's order when ref collides
        if tenant_id is None and len(orders) > 1 and not tracking:
            logger.warning(
                f"🚨 Ambiguous order ref '{order_ref}' matches {len(orders)} tenants — tenant_id required"
            )
            return CourierWebhookResponse(
                status="ambiguous_order_ref",
                courier=courier_name,
                tracking_number=tracking,
                normalized_status=norm_status,
            )
        # Prefer exact tracking match when multiple rows match
        order = orders[0]
        if len(orders) > 1 and tracking:
            for candidate in orders:
                if candidate.tracking_number == tracking:
                    order = candidate
                    break

        if tracking and not order.tracking_number:
            order.tracking_number = tracking
        order.courier_name = courier_name
        order.current_status = norm_status

        if parsed["delivery_charges"] > 0:
            order.courier_fee_pkr = float(parsed["delivery_charges"])
        if parsed["return_charges"] > 0:
            order.return_fee_pkr = float(parsed["return_charges"])

        now_dt = parsed["timestamp"]
        if norm_status == "DELIVERED":
            order.delivered_at = now_dt
        elif norm_status == "RETURNED":
            order.returned_at = now_dt

        event = CourierEvent(
            tenant_id=order.tenant_id,
            order_id=order.id,
            courier_name=courier_name,
            tracking_number=tracking or order.tracking_number or "UNKNOWN",
            raw_status=parsed["raw_status"],
            normalized_status=norm_status,
            event_timestamp=now_dt,
            raw_payload=raw_payload,
        )
        session.add(event)

        if norm_status in ("DELIVERED", "RETURNED"):
            session.add(
                AuditLog(
                    tenant_id=order.tenant_id,
                    action_type="COURIER_STATUS_UPDATED",
                    action_details={
                        "order_id": str(order.id),
                        "external_order_id": order.external_order_id,
                        "courier": courier_name,
                        "tracking_number": tracking,
                        "status": norm_status,
                        "delivery_fee": float(order.courier_fee_pkr),
                        "return_fee": float(order.return_fee_pkr),
                    },
                    executed_by=f"{courier_name}_WEBHOOK",
                )
            )

        await session.commit()

        logger.info(
            f"✅ Order {order.external_order_id} updated to {norm_status} via {courier_name} webhook"
        )
        return CourierWebhookResponse(
            status="processed",
            courier=courier_name,
            tracking_number=tracking,
            order_id=str(order.id),
            normalized_status=norm_status,
        )


@router.post("/webhook/postex", response_model=CourierWebhookResponse, status_code=status.HTTP_200_OK)
async def handle_postex_webhook(request: Request, tenant_id: uuid.UUID | None = Query(default=None)) -> CourierWebhookResponse:
    """PostEx courier status webhook."""
    verify_courier_webhook_secret(request)
    tenant_id = tenant_id or _tenant_from_header(request)
    try:
        payload = await request.json()
    except Exception as exc:
        logger.error(f"Failed parsing PostEx webhook JSON: {exc}")
        return CourierWebhookResponse(status="invalid_payload", courier="POSTEX")
    parsed = parse_postex_webhook_payload(payload)
    return await _process_courier_lifecycle("POSTEX", parsed, payload, tenant_id)


@router.post("/webhook/trax", response_model=CourierWebhookResponse, status_code=status.HTTP_200_OK)
async def handle_trax_webhook(request: Request, tenant_id: uuid.UUID | None = Query(default=None)) -> CourierWebhookResponse:
    """Trax Logistics status webhook."""
    verify_courier_webhook_secret(request)
    tenant_id = tenant_id or _tenant_from_header(request)
    try:
        payload = await request.json()
    except Exception as exc:
        logger.error(f"Failed parsing Trax webhook JSON: {exc}")
        return CourierWebhookResponse(status="invalid_payload", courier="TRAX")
    parsed = parse_trax_webhook_payload(payload)
    return await _process_courier_lifecycle("TRAX", parsed, payload, tenant_id)


@router.post("/webhook/leopards", response_model=CourierWebhookResponse, status_code=status.HTTP_200_OK)
async def handle_leopards_webhook(request: Request, tenant_id: uuid.UUID | None = Query(default=None)) -> CourierWebhookResponse:
    """Leopards Courier status webhook."""
    verify_courier_webhook_secret(request)
    tenant_id = tenant_id or _tenant_from_header(request)
    try:
        payload = await request.json()
    except Exception as exc:
        logger.error(f"Failed parsing Leopards webhook JSON: {exc}")
        return CourierWebhookResponse(status="invalid_payload", courier="LEOPARDS")
    parsed = parse_leopards_webhook_payload(payload)
    return await _process_courier_lifecycle("LEOPARDS", parsed, payload, tenant_id)


@router.post("/webhook/swyft", response_model=CourierWebhookResponse, status_code=status.HTTP_200_OK)
async def handle_swyft_webhook(request: Request, tenant_id: uuid.UUID | None = Query(default=None)) -> CourierWebhookResponse:
    """Swyft Logistics status webhook."""
    verify_courier_webhook_secret(request)
    tenant_id = tenant_id or _tenant_from_header(request)
    try:
        payload = await request.json()
    except Exception as exc:
        logger.error(f"Failed parsing Swyft webhook JSON: {exc}")
        return CourierWebhookResponse(status="invalid_payload", courier="SWYFT")
    parsed = parse_swyft_webhook_payload(payload)
    return await _process_courier_lifecycle("SWYFT", parsed, payload, tenant_id)


# Tenant-path aliases: /webhook/{courier}/{tenant_id}
@router.post("/webhook/postex/{tenant_id}", response_model=CourierWebhookResponse, status_code=status.HTTP_200_OK)
async def handle_postex_webhook_tenant(request: Request, tenant_id: uuid.UUID) -> CourierWebhookResponse:
    verify_courier_webhook_secret(request)
    try:
        payload = await request.json()
    except Exception as exc:
        logger.error(f"Failed parsing PostEx webhook JSON: {exc}")
        return CourierWebhookResponse(status="invalid_payload", courier="POSTEX")
    return await _process_courier_lifecycle("POSTEX", parse_postex_webhook_payload(payload), payload, tenant_id)


@router.post("/webhook/trax/{tenant_id}", response_model=CourierWebhookResponse, status_code=status.HTTP_200_OK)
async def handle_trax_webhook_tenant(request: Request, tenant_id: uuid.UUID) -> CourierWebhookResponse:
    verify_courier_webhook_secret(request)
    try:
        payload = await request.json()
    except Exception as exc:
        logger.error(f"Failed parsing Trax webhook JSON: {exc}")
        return CourierWebhookResponse(status="invalid_payload", courier="TRAX")
    return await _process_courier_lifecycle("TRAX", parse_trax_webhook_payload(payload), payload, tenant_id)


@router.post("/webhook/leopards/{tenant_id}", response_model=CourierWebhookResponse, status_code=status.HTTP_200_OK)
async def handle_leopards_webhook_tenant(request: Request, tenant_id: uuid.UUID) -> CourierWebhookResponse:
    verify_courier_webhook_secret(request)
    try:
        payload = await request.json()
    except Exception as exc:
        logger.error(f"Failed parsing Leopards webhook JSON: {exc}")
        return CourierWebhookResponse(status="invalid_payload", courier="LEOPARDS")
    return await _process_courier_lifecycle("LEOPARDS", parse_leopards_webhook_payload(payload), payload, tenant_id)


@router.post("/webhook/swyft/{tenant_id}", response_model=CourierWebhookResponse, status_code=status.HTTP_200_OK)
async def handle_swyft_webhook_tenant(request: Request, tenant_id: uuid.UUID) -> CourierWebhookResponse:
    verify_courier_webhook_secret(request)
    try:
        payload = await request.json()
    except Exception as exc:
        logger.error(f"Failed parsing Swyft webhook JSON: {exc}")
        return CourierWebhookResponse(status="invalid_payload", courier="SWYFT")
    return await _process_courier_lifecycle("SWYFT", parse_swyft_webhook_payload(payload), payload, tenant_id)

