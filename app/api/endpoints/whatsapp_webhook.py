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


import re
import uuid
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.database import async_session_maker
from app.core.security import decrypt_token
from app.models.tenant import Tenant
from app.models.audit_log import AuditLog
from app.skills.hitl_action_tokens import (
    verify_action_token,
    InvalidTokenError,
    ExpiredTokenError,
)
from app.utils.meta_client import MetaGraphClient, MetaAPIError
from app.utils.whatsapp_client import WhatsAppClient


def _normalize_phone(number: str | None) -> str:
    """Normalize phone number to digits only, mapping leading 0 to 92 for PK."""
    if not number:
        return ""
    digits = re.sub(r"\D", "", number)
    if digits.startswith("0") and len(digits) == 11:
        digits = "92" + digits[1:]
    return digits


async def _handle_button_action(
    button_id: str,
    button_text: str,
    sender: str,
    value: dict[str, Any],
) -> None:
    """
    Handle interactive button reply action with Phase-3 Silver Tier HITL security.

    1. Validates and unpacks cryptographically signed action token.
    2. Enforces 15-minute TTL expiration.
    3. Guarantees idempotency via token nonce check against AuditLog.
    4. Authorizes sender against tenant notification number.
    5. Dispatches mutation (e.g. status='PAUSED' on Meta Graph API).
    6. Writes immutable AuditLog and sends bilingual WhatsApp confirmation.
    """
    token_str = button_id or ""
    if not token_str.startswith("v1."):
        # Legacy or non-token button click
        action = (button_id or button_text).upper()
        logger.info(f"🔘 Legacy WhatsApp button clicked: '{action}' by {sender}")
        return

    try:
        token_data = verify_action_token(token_str)
    except ExpiredTokenError:
        logger.warning(f"⏰ Received expired action token from {sender}")
        wa_client = WhatsAppClient()
        try:
            await wa_client.send_text_message(
                recipient_number=sender,
                message_text="⚠️ *Request Expired*\nYeh button expire ho chuka hai (15-min limit). Baraye meherbani Ads Manager check karein.",
            )
        except Exception as exc:
            logger.error(f"Failed to send expiration notice: {exc}")
        finally:
            await wa_client.close()
        return
    except InvalidTokenError as exc:
        logger.warning(f"❌ Invalid action token rejected from {sender}: {exc}")
        return

    action = token_data["action"]
    tenant_id_str = token_data["tenant_id"]
    campaign_id = token_data["campaign_id"]
    nonce = token_data["nonce"]

    try:
        tenant_uuid = uuid.UUID(tenant_id_str)
    except ValueError:
        logger.error(f"Malformed tenant UUID in token: {tenant_id_str}")
        return

    async with async_session_maker() as session:
        t_res = await session.execute(
            select(Tenant)
            .where(Tenant.id == tenant_uuid)
            .options(selectinload(Tenant.ad_accounts), selectinload(Tenant.credentials))
        )
        tenant = t_res.scalars().first()
        if tenant is None:
            logger.error(f"Tenant {tenant_uuid} not found for HITL action")
            return

        # Sender authorization check
        if _normalize_phone(sender) != _normalize_phone(tenant.whatsapp_notification_number):
            logger.warning(
                f"🚨 Unauthorized sender {sender} attempted HITL action for tenant {tenant.id} "
                f"(expected {tenant.whatsapp_notification_number})"
            )
            return

        # Idempotency / Replay Protection via AuditLog
        audit_res = await session.execute(
            select(AuditLog).where(
                AuditLog.tenant_id == tenant.id,
                AuditLog.action_type.in_(["USER_APPROVED", "USER_REJECTED"]),
            )
        )
        for log_entry in audit_res.scalars().all():
            details = log_entry.action_details or {}
            if details.get("token_nonce") == nonce:
                logger.info(f"🔁 Duplicate action token nonce {nonce} ignored")
                language = tenant.preferred_language or "roman_urdu"
                dup_msg = (
                    "ℹ️ *Action Already Processed*\nThis action was already executed."
                    if language == "english"
                    else "ℹ️ *Pehle Hi Process Ho Chuka Hai*\nYeh action pehle hi execute ho chuka hai."
                )
                wa_client = WhatsAppClient()
                try:
                    await wa_client.send_text_message(recipient_number=sender, message_text=dup_msg)
                finally:
                    await wa_client.close()
                return

        # Resolve credentials
        meta_token = None
        wa_token = None
        for cred in tenant.credentials:
            if cred.token_status == "ACTIVE":
                if cred.platform_name == "META" and meta_token is None:
                    try:
                        meta_token = decrypt_token(cred.encrypted_access_token)
                    except Exception as err:
                        logger.error(f"Failed decrypting Meta token: {err}")
                elif cred.platform_name == "WHATSAPP" and wa_token is None:
                    try:
                        wa_token = decrypt_token(cred.encrypted_access_token)
                    except Exception as err:
                        logger.error(f"Failed decrypting WhatsApp token: {err}")

        # Link ad account if known
        matched_acc_id = tenant.ad_accounts[0].id if tenant.ad_accounts else None
        language = tenant.preferred_language or "roman_urdu"
        wa_client = WhatsAppClient(access_token=wa_token)

        try:
            if action == "PAUSE":
                meta_client = MetaGraphClient(access_token=meta_token)
                try:
                    await meta_client.update_campaign_status(campaign_id=campaign_id, status="PAUSED")
                    logger.info(f"🛑 Successfully paused campaign {campaign_id} for tenant {tenant.id}")
                finally:
                    await meta_client.close()

                session.add(AuditLog(
                    tenant_id=tenant.id,
                    ad_account_id=matched_acc_id,
                    action_type="USER_APPROVED",
                    action_details={
                        "action": "PAUSE_CAMPAIGN",
                        "campaign_id": campaign_id,
                        "token_nonce": nonce,
                        "status": "PAUSED",
                    },
                    executed_by="WHATSAPP_HITL",
                    executed_by_whatsapp_num=sender,
                ))
                await session.commit()

                confirm_msg = (
                    f"✅ *Campaign Paused*\nCampaign *{campaign_id}* has been paused successfully. Ad spend has stopped."
                    if language == "english"
                    else f"✅ *Campaign Paused*\nCampaign *{campaign_id}* ko successfully pause kar diya gaya hai. Mazeed spend ruk gaya hai."
                )
                await wa_client.send_text_message(recipient_number=sender, message_text=confirm_msg)

            elif action == "DISMISS":
                session.add(AuditLog(
                    tenant_id=tenant.id,
                    ad_account_id=matched_acc_id,
                    action_type="USER_REJECTED",
                    action_details={
                        "action": "KEEP_RUNNING",
                        "campaign_id": campaign_id,
                        "token_nonce": nonce,
                        "status": "ACTIVE",
                    },
                    executed_by="WHATSAPP_HITL",
                    executed_by_whatsapp_num=sender,
                ))
                await session.commit()

                confirm_msg = (
                    f"👍 *Acknowledged*\nCampaign *{campaign_id}* kept active. No changes made."
                    if language == "english"
                    else f"👍 *Samajh Aa Gaya*\nCampaign *{campaign_id}* active rahegi. Koi tabdeeli nahi ki gayi."
                )
                await wa_client.send_text_message(recipient_number=sender, message_text=confirm_msg)

        except MetaAPIError as exc:
            logger.error(f"Meta API mutation failed for campaign {campaign_id}: {exc}")
            session.add(AuditLog(
                tenant_id=tenant.id,
                ad_account_id=matched_acc_id,
                action_type="ACTION_FAILED",
                action_details={
                    "action": "PAUSE_CAMPAIGN",
                    "campaign_id": campaign_id,
                    "token_nonce": nonce,
                    "error": str(exc),
                },
                executed_by="WHATSAPP_HITL",
                executed_by_whatsapp_num=sender,
            ))
            await session.commit()

            err_msg = (
                f"⚠️ *Meta Error*\nFailed to pause campaign *{campaign_id}*: {exc}"
                if language == "english"
                else f"⚠️ *Meta Error*\nCampaign *{campaign_id}* pause karne mein error aya: {exc}"
            )
            await wa_client.send_text_message(recipient_number=sender, message_text=err_msg)
        finally:
            await wa_client.close()
