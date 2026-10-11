"""
Courier Webhook Receiver (Phase-4 Gold Tier).

Ingests real-time order delivery status updates from Pakistani couriers
(starting with PostEx MVP) and updates order fulfillment & COD reconciliation.
"""

from typing import Any
from fastapi import APIRouter, Request, status
from loguru import logger
from sqlalchemy import or_, select

from app.core.database import async_session_maker
from app.models.audit_log import AuditLog
from app.models.order import CourierEvent, Order
from app.schemas.order import CourierWebhookResponse
from app.skills.courier_normalizer import parse_postex_webhook_payload

router = APIRouter()


@router.post("/webhook/postex", response_model=CourierWebhookResponse, status_code=status.HTTP_200_OK)
async def handle_postex_webhook(request: Request) -> CourierWebhookResponse:
    """
    PostEx Courier Webhook Receiver.

    Accepts status updates from PostEx (Order Placed, In Transit, Delivered, Returned, etc.),
    normalizes the lifecycle state, logs the event trail, and updates the order status.
    """
    try:
        payload: dict[str, Any] = await request.json()
    except Exception as exc:
        logger.error(f"Failed parsing PostEx webhook JSON: {exc}")
        return CourierWebhookResponse(
            status="invalid_payload",
            courier="POSTEX",
        )

    parsed = parse_postex_webhook_payload(payload)
    tracking = parsed["tracking_number"]
    order_ref = parsed["order_reference"]
    norm_status = parsed["normalized_status"]

    logger.info(
        f"📦 PostEx webhook received for tracking: '{tracking}', ref: '{order_ref}', status: {norm_status}"
    )

    if not tracking and not order_ref:
        return CourierWebhookResponse(
            status="missing_identifiers",
            courier="POSTEX",
        )

    async with async_session_maker() as session:
        # Locate order by tracking number or external order reference
        conditions = []
        if tracking:
            conditions.append(Order.tracking_number == tracking)
        if order_ref:
            conditions.append(Order.external_order_id == order_ref)
            conditions.append(Order.order_number == order_ref)

        result = await session.execute(
            select(Order).where(or_(*conditions))
        )
        order = result.scalars().first()

        if order is None:
            logger.warning(
                f"⚠️ Order not found for PostEx update (tracking: {tracking}, ref: {order_ref})"
            )
            return CourierWebhookResponse(
                status="order_not_found",
                courier="POSTEX",
                tracking_number=tracking,
                normalized_status=norm_status,
            )

        # Update order tracking details
        if tracking and not order.tracking_number:
            order.tracking_number = tracking
        order.courier_name = "POSTEX"
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

        # Record immutable CourierEvent
        event = CourierEvent(
            tenant_id=order.tenant_id,
            order_id=order.id,
            courier_name="POSTEX",
            tracking_number=tracking or order.tracking_number or "UNKNOWN",
            raw_status=parsed["raw_status"],
            normalized_status=norm_status,
            event_timestamp=now_dt,
            raw_payload=payload,
        )
        session.add(event)

        # Record audit log for terminal states
        if norm_status in ("DELIVERED", "RETURNED"):
            session.add(
                AuditLog(
                    tenant_id=order.tenant_id,
                    action_type="COURIER_STATUS_UPDATED",
                    action_details={
                        "order_id": str(order.id),
                        "external_order_id": order.external_order_id,
                        "courier": "POSTEX",
                        "tracking_number": tracking,
                        "status": norm_status,
                        "delivery_fee": float(order.courier_fee_pkr),
                        "return_fee": float(order.return_fee_pkr),
                    },
                    executed_by="POSTEX_WEBHOOK",
                )
            )

        await session.commit()

        logger.info(
            f"✅ Order {order.external_order_id} updated to {norm_status} via PostEx webhook"
        )
        return CourierWebhookResponse(
            status="processed",
            courier="POSTEX",
            tracking_number=tracking,
            order_id=str(order.id),
            normalized_status=norm_status,
        )
