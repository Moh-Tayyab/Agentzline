"""
WhatsApp Webhook Endpoint.

Handles incoming WhatsApp messages and interactive button responses.
Implements the Human-In-The-Loop (HITL) approval architecture.

Bronze Tier: Receives APPROVED / REJECTED button clicks from WhatsApp.
No action is executed without explicit user consent.
"""

from fastapi import APIRouter, Query, Response
from loguru import logger

from app.schemas.whatsapp import (
    WhatsAppWebhookVerification,
    WhatsAppButtonPayload,
)

router = APIRouter()


@router.get("/webhook")
async def verify_webhook(
    hub_mode: str = Query(alias="hub.mode"),
    hub_challenge: str = Query(alias="hub.challenge"),
    hub_verify_token: str = Query(alias="hub.verify_token"),
):
    """
    WhatsApp webhook verification (GET).

    Meta calls this endpoint to verify the webhook subscription.
    The verify token must match WHATSAPP_WEBHOOK_VERIFY_TOKEN from .env.
    """
    from app.core.config import get_settings

    settings = get_settings()

    if hub_mode == "subscribe" and hub_verify_token == settings.WHATSAPP_WEBHOOK_VERIFY_TOKEN:
        logger.info("✅ WhatsApp webhook verified successfully")
        return int(hub_challenge)

    logger.warning("❌ WhatsApp webhook verification failed — token mismatch")
    return Response(status_code=403)


@router.post("/webhook")
async def handle_whatsapp_webhook(payload: dict):
    """
    WhatsApp webhook receiver (POST).

    Processes incoming messages and interactive button clicks.
    For Bronze Tier HITL: handles APPROVE / REJECT responses.
    """
    logger.info(f"📩 Received WhatsApp webhook: {payload.get('object')}")

    # Extract entry data from WhatsApp payload structure
    entry = payload.get("entry", [])
    for e in entry:
        changes = e.get("changes", [])
        for change in changes:
            value = change.get("value", {})
            messages = value.get("messages", [])

            for message in messages:
                msg_type = message.get("type")

                if msg_type == "button":
                    await _handle_button_response(message, value)
                elif msg_type == "text":
                    await _handle_text_message(message, value)
                else:
                    logger.debug(f"Unhandled message type: {msg_type}")

    return {"status": "received"}


async def _handle_button_response(message: dict, value: dict):
    """
    Process an interactive button click (HITL approval/rejection).

    This is the core of the Human-In-The-Loop architecture:
    - APPROVED → execute the proposed action via Meta API
    - REJECTED → log refusal, no action taken
    """
    button = message.get("button", {})
    button_text = button.get("text", "")
    sender_number = message.get("from", "")

    logger.info(
        f"🔘 HITL button response: '{button_text}' from {sender_number}"
    )

    if button_text.upper() == "APPROVED":
        # TODO: Fetch pending action from DB by action_token
        # TODO: Execute approved mutation via Meta Graph API
        # TODO: Log to agent_action_audit_logs
        logger.info(f"✅ Action APPROVED by {sender_number} — executing")

    elif button_text.upper() == "REJECTED":
        # Log refusal to audit trail — no execution
        logger.info(f"❌ Action REJECTED by {sender_number} — cancelled")


async def _handle_text_message(message: dict, value: dict):
    """Handle plain text messages (future: natural language commands)."""
    text = message.get("text", {}).get("body", "")
    sender = message.get("from", "")
    logger.info(f"💬 Text message from {sender}: {text[:100]}")
    # TODO: Implement NLP command parsing for future tier
