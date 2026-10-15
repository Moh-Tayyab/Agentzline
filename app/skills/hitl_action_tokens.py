"""
Human-In-The-Loop (HITL) Cryptographic Action Tokens (Phase-3 Silver Tier).

Generates and validates tamper-proof, time-bound action tokens embedded
in WhatsApp interactive button replies (e.g., [🔴 Pause Ad] / [Keep Running]).

Guarantees:
1. Integrity & Authenticity: HMAC-SHA256 signature prevents tampering or forgery.
2. Time-bounded: 15-minute TTL prevents stale actions.
3. Compact: Fits comfortably under WhatsApp Cloud API's 256-character button ID limit.
4. Nonce-protected: Each token contains random entropy for replay protection.
"""

import hashlib
import hmac
import secrets
import time
from typing import Any

from loguru import logger

from app.core.config import get_settings


class ActionTokenError(Exception):
    """Base error for action token failures."""


class InvalidTokenError(ActionTokenError):
    """Token is malformed or signature is invalid."""


class ExpiredTokenError(ActionTokenError):
    """Token timestamp is older than allowed TTL."""


def _get_signing_key() -> bytes:
    """Resolve secret key used for token signing."""
    settings = get_settings()
    raw = (
        settings.ACTION_TOKEN_SECRET
        or settings.FERNET_ENCRYPTION_KEY
        or settings.META_APP_SECRET
        or "default-agentzline-hitl-secret-key"
    )
    return raw.encode("utf-8")


def generate_action_token(
    tenant_id: str,
    campaign_id: str,
    action: str,
    ttl_seconds: int | None = None,
) -> str:
    """
    Generate an HMAC-signed action token for WhatsApp interactive buttons.

    Format: v1.<action>.<tenant_id>.<campaign_id>.<nonce>.<exp>.<signature>

    Args:
        tenant_id: Tenant UUID string.
        campaign_id: External Meta campaign ID.
        action: Permitted action string (e.g., 'PAUSE', 'DISMISS').
        ttl_seconds: Optional expiration in seconds (defaults to ACTION_TOKEN_EXPIRY_MINUTES * 60).

    Returns:
        Signed token string (<160 chars).
    """
    settings = get_settings()
    action_norm = action.strip().upper()
    if action_norm not in ("PAUSE", "DISMISS"):
        raise ValueError(f"Unsupported action for action token: {action}")

    if ttl_seconds is None:
        ttl_seconds = int(settings.ACTION_TOKEN_EXPIRY_MINUTES) * 60

    nonce = secrets.token_hex(4)  # 8 hex characters
    exp = int(time.time()) + int(ttl_seconds)

    payload = f"v1.{action_norm}.{tenant_id.strip()}.{campaign_id.strip()}.{nonce}.{exp}"
    key = _get_signing_key()
    sig = hmac.new(key, payload.encode("utf-8"), hashlib.sha256).hexdigest()

    token = f"{payload}.{sig}"
    logger.debug(f"🔑 Generated action token for {action_norm} (campaign: {campaign_id}, len: {len(token)})")
    return token


def verify_action_token(token: str) -> dict[str, Any]:
    """
    Verify and unpack a signed action token.

    Args:
        token: Token string returned by WhatsApp button reply.

    Returns:
        Dict with keys: action, tenant_id, campaign_id, nonce, exp.

    Raises:
        InvalidTokenError: If malformed or signature mismatch.
        ExpiredTokenError: If expired.
    """
    if not token or not isinstance(token, str):
        raise InvalidTokenError("Empty or invalid token format")

    parts = token.strip().split(".")
    if len(parts) != 7 or parts[0] != "v1":
        raise InvalidTokenError("Malformed action token structure")

    _, action, tenant_id, campaign_id, nonce, exp_str, sig = parts
    payload = f"v1.{action}.{tenant_id}.{campaign_id}.{nonce}.{exp_str}"

    key = _get_signing_key()
    expected_sig = hmac.new(key, payload.encode("utf-8"), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(sig, expected_sig):
        logger.warning(f"❌ Action token signature mismatch for campaign {campaign_id}")
        raise InvalidTokenError("Action token signature verification failed")

    try:
        exp = int(exp_str)
    except ValueError:
        raise InvalidTokenError("Invalid token expiration timestamp")

    now = int(time.time())
    if now > exp:
        logger.warning(f"⏰ Action token expired (exp: {exp}, now: {now})")
        raise ExpiredTokenError(f"Action token expired at {exp} (now: {now})")

    return {
        "version": "v1",
        "action": action,
        "tenant_id": tenant_id,
        "campaign_id": campaign_id,
        "nonce": nonce,
        "exp": exp,
    }


async def execute_hitl_token_action(token: str, sender: str | None = None) -> dict[str, Any]:
    """Execute a HITL action token end-to-end with zero duplication.

    Shared by WhatsApp webhook button handler and POST /api/v1/actions/pause.
    Performs cryptographic verification, indexed nonce replay check,
    tenant + sender authorization, Meta mutation (PAUSE), immutable AuditLog
    with `token_nonce`, and returns a result dict.

    Returns:
        {"status": "paused"|"dismissed"|"duplicate"|"expired"|..., ...}
    """
    import uuid as _uuid

    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    token_data = verify_action_token(token)
    action = token_data["action"]
    tenant_id_str = token_data["tenant_id"]
    campaign_id = token_data["campaign_id"]
    nonce = token_data["nonce"]

    try:
        tenant_uuid = _uuid.UUID(tenant_id_str)
    except ValueError as exc:
        raise InvalidTokenError(f"Malformed tenant UUID in token: {tenant_id_str}") from exc

    from app.core.database import async_session_maker
    from app.core.security import decrypt_token
    from app.models.audit_log import AuditLog
    from app.models.tenant import Tenant
    from app.utils.meta_client import MetaGraphClient

    async with async_session_maker() as session:
        t_res = await session.execute(
            select(Tenant)
            .where(Tenant.id == tenant_uuid)
            .options(selectinload(Tenant.ad_accounts), selectinload(Tenant.credentials))
        )
        tenant = t_res.scalars().first()
        if tenant is None:
            raise InvalidTokenError(f"Tenant {tenant_uuid} not found")

        # Optional sender authorization (WhatsApp path supplies sender)
        if sender:
            from app.api.endpoints.whatsapp_webhook import _normalize_phone

            if _normalize_phone(sender) != _normalize_phone(tenant.whatsapp_notification_number):
                raise InvalidTokenError("Unauthorized sender for this tenant")

        existing_nonce = await session.execute(
            select(AuditLog.id).where(AuditLog.token_nonce == nonce).limit(1)
        )
        if existing_nonce.scalars().first() is not None:
            return {"status": "duplicate", "nonce": nonce, "tenant_id": tenant_id_str}

        meta_token = None
        for cred in tenant.credentials:
            if cred.token_status == "ACTIVE" and cred.platform_name == "META" and meta_token is None:
                try:
                    meta_token = decrypt_token(cred.encrypted_access_token)
                except Exception as err:
                    logger.error(f"Failed decrypting Meta token: {err}")

        matched_acc_id = tenant.ad_accounts[0].id if tenant.ad_accounts else None

        if action == "PAUSE":
            meta_client = MetaGraphClient(access_token=meta_token)
            try:
                await meta_client.update_campaign_status(campaign_id=campaign_id, status="PAUSED")
            finally:
                await meta_client.close()
            session.add(
                AuditLog(
                    tenant_id=tenant.id,
                    ad_account_id=matched_acc_id,
                    action_type="USER_APPROVED",
                    action_details={
                        "action": "PAUSE_CAMPAIGN",
                        "campaign_id": campaign_id,
                        "token_nonce": nonce,
                        "status": "PAUSED",
                    },
                    executed_by="HITL_ACTION_API" if sender is None else "WHATSAPP_HITL",
                    executed_by_whatsapp_num=sender,
                    token_nonce=nonce,
                )
            )
            await session.commit()
            return {"status": "paused", "campaign_id": campaign_id, "tenant_id": tenant_id_str, "nonce": nonce}
        elif action == "DISMISS":
            session.add(
                AuditLog(
                    tenant_id=tenant.id,
                    ad_account_id=matched_acc_id,
                    action_type="USER_REJECTED",
                    action_details={
                        "action": "KEEP_RUNNING",
                        "campaign_id": campaign_id,
                        "token_nonce": nonce,
                        "status": "ACTIVE",
                    },
                    executed_by="HITL_ACTION_API" if sender is None else "WHATSAPP_HITL",
                    executed_by_whatsapp_num=sender,
                    token_nonce=nonce,
                )
            )
            await session.commit()
            return {"status": "dismissed", "campaign_id": campaign_id, "tenant_id": tenant_id_str, "nonce": nonce}
        else:
            raise InvalidTokenError(f"Unsupported HITL action: {action}")
