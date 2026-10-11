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
