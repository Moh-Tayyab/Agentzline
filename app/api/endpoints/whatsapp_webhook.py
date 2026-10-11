"""
WhatsApp Webhook Endpoint.

Handles incoming WhatsApp messages and interactive button responses.
Implements secure signature verification, payload parsing, deduplication,
and asynchronous HITL processing.
"""

import hashlib
import hmac
import json
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Query, Request, Response, status
from loguru import logger

from app.core.config import get_settings

router = APIRouter()

# In-memory deduplication set for processed message IDs (wamid)
# In production with multiple workers, back with Redis
_PROCESSED_MESSAGE_IDS: set[str] = set()
_MAX_SEEN_IDS = 10000


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
    settings = get_settings()

    if hub_mode == "subscribe" and hub_verify_token == settings.WHATSAPP_WEBHOOK_VERIFY_TOKEN:
        logger.info("✅ WhatsApp webhook verified successfully")
        return int(hub_challenge)

    logger.warning("❌ WhatsApp webhook verification failed — token mismatch")
    return Response(status_code=status.HTTP_403_FORBIDDEN)


def _verify_meta_signature(raw_body: bytes, signature_header: str | None, app_secret: str) -> bool:
    """Verify X-Hub-Signature-256 HMAC header from Meta using raw request bytes."""
    if not app_secret:
        # If secret is not yet configured in local dev, log warning but allow dev flow
        logger.warning("⚠️ META_APP_SECRET not set — skipping HMAC signature verification in dev")
        return True

    if not signature_header or not signature_header.startswith("sha256="):
        return False

    expected_sig = "sha256=" + hmac.new(
        key=app_secret.encode("utf-8"),
        msg=raw_body,
        digestmod=hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(signature_header, expected_sig)


@router.post("/webhook")
async def handle_whatsapp_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_hub_signature_256: str | None = Header(default=None, alias="X-Hub-Signature-256"),
):
    """
    WhatsApp webhook receiver (POST).

    1. Validates HMAC-SHA256 signature against META_APP_SECRET using raw bytes.
    2. Parses incoming messages, interactive button clicks, and delivery statuses.
    3. Offloads background processing and immediately returns 200 OK (<5s).
    """
    settings = get_settings()
    raw_body = await request.body()

    # Validate HMAC signature using raw request body
    if not _verify_meta_signature(raw_body, x_hub_signature_256, settings.META_APP_SECRET):
        logger.error("❌ Invalid X-Hub-Signature-256 received on webhook")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid request signature",
        )

    try:
        payload: dict[str, Any] = json.loads(raw_body.decode("utf-8"))
    except Exception as exc:
        logger.error(f"Failed to parse webhook JSON payload: {exc}")
        return {"status": "invalid_json"}

    # Process events in background to ensure fast 200 OK response
    background_tasks.add_task(_process_webhook_payload, payload)
    return {"status": "received"}


async def _process_webhook_payload(payload: dict[str, Any]) -> None:
    """Process WhatsApp entries in background."""
    entry = payload.get("entry", [])
    for e in entry:
        changes = e.get("changes", [])
        for change in changes:
            value = change.get("value", {})

            # 1. Handle message statuses (sent, delivered, read callbacks)
            statuses = value.get("statuses", [])
            for st in statuses:
                logger.debug(f"WhatsApp status update: {st.get('id')} -> {st.get('status')}")

            # 2. Handle incoming messages
            messages = value.get("messages", [])
            for message in messages:
                msg_id = message.get("id")

                # Deduplicate repeated deliveries from Meta retries
                if msg_id:
                    if msg_id in _PROCESSED_MESSAGE_IDS:
                        logger.debug(f"Ignoring duplicate WhatsApp message: {msg_id}")
                        continue
                    if len(_PROCESSED_MESSAGE_IDS) >= _MAX_SEEN_IDS:
                        _PROCESSED_MESSAGE_IDS.clear()
                    _PROCESSED_MESSAGE_IDS.add(msg_id)

                msg_type = message.get("type")

                # Modern interactive button reply
                if msg_type == "interactive":
                    interactive = message.get("interactive", {})
                    if interactive.get("type") == "button_reply":
                        reply = interactive.get("button_reply", {})
                        button_id = reply.get("id", "")
                        button_title = reply.get("title", "")
                        sender = message.get("from", "")
                        await _handle_button_action(button_id, button_title, sender, value)

                # Legacy quick-reply button
                elif msg_type == "button":
                    btn = message.get("button", {})
                    button_payload = btn.get("payload", "")
                    button_text = btn.get("text", "")
                    sender = message.get("from", "")
                    await _handle_button_action(button_payload, button_text, sender, value)

                elif msg_type == "text":
                    text = message.get("text", {}).get("body", "")
                    sender = message.get("from", "")
                    logger.info(f"💬 WhatsApp text from {sender}: {text[:100]}")


async def _handle_button_action(button_id: str, button_text: str, sender: str, value: dict[str, Any]) -> None:
    """Handle interactive button reply action."""
    action = (button_id or button_text).upper()
    logger.info(f"🔘 HITL Button Response: '{action}' from {sender}")

    if "APPROVE" in action:
        logger.info(f"✅ Action APPROVED by {sender} — queuing for execution")
    elif "REJECT" in action:
        logger.info(f"❌ Action REJECTED by {sender} — logging refusal")
    else:
        logger.info(f"🔘 Button selected: {action}")
