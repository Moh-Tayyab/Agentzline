"""
Tests for Phase-3 Silver Tier Human-In-The-Loop (HITL) Mutation Engine.

Covers:
- Cryptographic action token generation, verification, and tamper detection.
- 15-minute TTL expiration enforcement.
- Meta campaign pause mutation via WhatsApp interactive button webhook.
- Rejection / dismissal flow (no mutation executed).
- Replay protection & idempotency via token nonce check against AuditLog.
- Unauthorized sender defense (phone number validation).
- Meta API error handling during mutation.
"""

import hashlib
import hmac
import time
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.database import async_session_maker
from app.core.security import encrypt_token
from app.main import app
from app.models.ad_account import AdAccount
from app.models.audit_log import AuditLog
from app.models.credential import PlatformCredential
from app.models.tenant import Tenant
from app.skills.hitl_action_tokens import (
    ExpiredTokenError,
    InvalidTokenError,
    generate_action_token,
    verify_action_token,
)
from app.utils.meta_client import MetaAPIError


class TestActionTokens:
    def test_token_generation_and_verification(self):
        t_id = str(uuid.uuid4())
        cid = "1203456789"
        token = generate_action_token(tenant_id=t_id, campaign_id=cid, action="PAUSE", ttl_seconds=900)

        assert token.startswith("v1.PAUSE.")
        assert len(token) < 160

        payload = verify_action_token(token)
        assert payload["action"] == "PAUSE"
        assert payload["tenant_id"] == t_id
        assert payload["campaign_id"] == cid
        assert payload["exp"] > time.time()
        assert len(payload["nonce"]) == 8

    def test_tampered_payload_rejected(self):
        t_id = str(uuid.uuid4())
        token = generate_action_token(tenant_id=t_id, campaign_id="12345", action="DISMISS")

        # Tamper: change DISMISS to PAUSE
        tampered = token.replace("DISMISS", "PAUSE", 1)
        with pytest.raises(InvalidTokenError, match="signature verification failed"):
            verify_action_token(tampered)

    def test_expired_token_rejected(self):
        t_id = str(uuid.uuid4())
        # Generate token with negative TTL
        token = generate_action_token(tenant_id=t_id, campaign_id="12345", action="PAUSE", ttl_seconds=-10)
        with pytest.raises(ExpiredTokenError, match="expired"):
            verify_action_token(token)

    def test_malformed_token_rejected(self):
        with pytest.raises(InvalidTokenError):
            verify_action_token("not.a.valid.token")

        with pytest.raises(InvalidTokenError):
            verify_action_token("")


@pytest.fixture
async def hitl_test_setup():
    """Create a fully-wired tenant with credentials and ad account."""
    t_id = uuid.uuid4()
    sender_phone = "+923001234567"
    raw_sender = "923001234567"

    async with async_session_maker() as session:
        tenant = Tenant(
            id=t_id,
            company_name="HITL Apparel PK",
            country_code="PK",
            currency="PKR",
            preferred_language="roman_urdu",
            whatsapp_notification_number=sender_phone,
        )
        session.add(tenant)
        await session.flush()

        ad_acc = AdAccount(
            tenant_id=t_id,
            platform="META",
            external_account_id="act_hitl_999",
            account_name="HITL Ad Account",
            max_budget_ceiling_pkr=200000.0,
            is_active=True,
        )
        session.add(ad_acc)

        cred = PlatformCredential(
            tenant_id=t_id,
            platform_name="META",
            token_status="ACTIVE",
            encrypted_access_token=encrypt_token("meta_hitl_secret_token"),
            meta_business_id="biz_hitl_999",
        )
        session.add(cred)
        await session.commit()

    return {
        "tenant_id": str(t_id),
        "sender": raw_sender,
        "campaign_id": "camp_bleed_888",
    }


def _build_whatsapp_button_webhook_payload(button_id: str, sender: str, title: str = "Button") -> dict:
    """Build canonical WhatsApp interactive button reply webhook payload."""
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "waba_1",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "messages": [
                                {
                                    "from": sender,
                                    "id": f"wamid.test.{uuid.uuid4().hex[:8]}",
                                    "timestamp": str(int(time.time())),
                                    "type": "interactive",
                                    "interactive": {
                                        "type": "button_reply",
                                        "button_reply": {
                                            "id": button_id,
                                            "title": title,
                                        },
                                    },
                                }
                            ],
                        },
                    }
                ],
            }
        ],
    }


@pytest.mark.asyncio
async def test_hitl_webhook_pause_approval(hitl_test_setup):
    """User clicks [🔴 Pause Ad] -> Meta mutation executed -> AuditLog recorded -> WhatsApp confirmation."""
    data = hitl_test_setup
    token = generate_action_token(
        tenant_id=data["tenant_id"],
        campaign_id=data["campaign_id"],
        action="PAUSE",
    )
    payload = _build_whatsapp_button_webhook_payload(
        button_id=token,
        sender=data["sender"],
        title="🔴 Pause Ad",
    )

    with patch("app.api.endpoints.whatsapp_webhook.MetaGraphClient") as mock_meta_cls, \
         patch("app.api.endpoints.whatsapp_webhook.WhatsAppClient") as mock_wa_cls:
        meta_inst = AsyncMock()
        meta_inst.update_campaign_status.return_value = {"success": True}
        mock_meta_cls.return_value = meta_inst

        wa_inst = AsyncMock()
        mock_wa_cls.return_value = wa_inst

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/v1/whatsapp/webhook", json=payload)
            assert resp.status_code == 200

        # Verify Meta campaign was paused
        meta_inst.update_campaign_status.assert_awaited_once_with(
            campaign_id=data["campaign_id"],
            status="PAUSED",
        )

        # Verify WhatsApp confirmation was sent
        wa_inst.send_text_message.assert_awaited_once()
        conf_body = wa_inst.send_text_message.await_args.kwargs["message_text"]
        assert "Campaign Paused" in conf_body

    # Verify AuditLog entry in database
    async with async_session_maker() as session:
        r = await session.execute(
            select(AuditLog).where(
                AuditLog.action_type == "USER_APPROVED",
                AuditLog.tenant_id == uuid.UUID(data["tenant_id"]),
            )
        )
        logs = r.scalars().all()
        assert len(logs) == 1
        log = logs[0]
        assert log.action_details.get("action") == "PAUSE_CAMPAIGN"
        assert log.action_details.get("campaign_id") == data["campaign_id"]
        assert log.executed_by == "WHATSAPP_HITL"
        assert log.executed_by_whatsapp_num == data["sender"]


@pytest.mark.asyncio
async def test_hitl_webhook_dismiss_rejection(hitl_test_setup):
    """User clicks [Keep Running] -> NO Meta mutation -> AuditLog recorded -> WhatsApp acknowledged."""
    data = hitl_test_setup
    token = generate_action_token(
        tenant_id=data["tenant_id"],
        campaign_id=data["campaign_id"],
        action="DISMISS",
    )
    payload = _build_whatsapp_button_webhook_payload(
        button_id=token,
        sender=data["sender"],
        title="Keep Running",
    )

    with patch("app.api.endpoints.whatsapp_webhook.MetaGraphClient") as mock_meta_cls, \
         patch("app.api.endpoints.whatsapp_webhook.WhatsAppClient") as mock_wa_cls:
        meta_inst = AsyncMock()
        mock_meta_cls.return_value = meta_inst

        wa_inst = AsyncMock()
        mock_wa_cls.return_value = wa_inst

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/v1/whatsapp/webhook", json=payload)
            assert resp.status_code == 200

        # Verify Meta campaign was NOT touched
        meta_inst.update_campaign_status.assert_not_awaited()

        # Verify WhatsApp acknowledgement was sent
        wa_inst.send_text_message.assert_awaited_once()
        conf_body = wa_inst.send_text_message.await_args.kwargs["message_text"]
        assert "active rahegi" in conf_body

    # Verify AuditLog entry for rejection
    async with async_session_maker() as session:
        r = await session.execute(
            select(AuditLog).where(
                AuditLog.action_type == "USER_REJECTED",
                AuditLog.tenant_id == uuid.UUID(data["tenant_id"]),
            )
        )
        logs = r.scalars().all()
        assert len(logs) == 1
        log = logs[0]
        assert log.action_details.get("action") == "KEEP_RUNNING"
        assert log.action_details.get("campaign_id") == data["campaign_id"]


@pytest.mark.asyncio
async def test_hitl_replay_protection_idempotency(hitl_test_setup):
    """Second delivery of the same signed action token must be ignored and not re-execute Meta mutation."""
    data = hitl_test_setup
    token = generate_action_token(
        tenant_id=data["tenant_id"],
        campaign_id=data["campaign_id"],
        action="PAUSE",
    )
    payload1 = _build_whatsapp_button_webhook_payload(button_id=token, sender=data["sender"])
    payload2 = _build_whatsapp_button_webhook_payload(button_id=token, sender=data["sender"])

    with patch("app.api.endpoints.whatsapp_webhook.MetaGraphClient") as mock_meta_cls, \
         patch("app.api.endpoints.whatsapp_webhook.WhatsAppClient") as mock_wa_cls:
        meta_inst = AsyncMock()
        mock_meta_cls.return_value = meta_inst
        wa_inst = AsyncMock()
        mock_wa_cls.return_value = wa_inst

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # First execution
            resp1 = await client.post("/api/v1/whatsapp/webhook", json=payload1)
            assert resp1.status_code == 200
            assert meta_inst.update_campaign_status.await_count == 1

            # Second execution with same token
            meta_inst.update_campaign_status.reset_mock()
            resp2 = await client.post("/api/v1/whatsapp/webhook", json=payload2)
            assert resp2.status_code == 200

            # Must NOT call Meta mutation again
            meta_inst.update_campaign_status.assert_not_awaited()


@pytest.mark.asyncio
async def test_hitl_unauthorized_sender_rejected(hitl_test_setup):
    """Button click from an unknown phone number must NOT mutate anything."""
    data = hitl_test_setup
    token = generate_action_token(
        tenant_id=data["tenant_id"],
        campaign_id=data["campaign_id"],
        action="PAUSE",
    )
    payload = _build_whatsapp_button_webhook_payload(
        button_id=token,
        sender="923339998877",  # Intruder number
    )

    with patch("app.api.endpoints.whatsapp_webhook.MetaGraphClient") as mock_meta_cls, \
         patch("app.api.endpoints.whatsapp_webhook.WhatsAppClient") as mock_wa_cls:
        meta_inst = AsyncMock()
        mock_meta_cls.return_value = meta_inst
        wa_inst = AsyncMock()
        mock_wa_cls.return_value = wa_inst

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/v1/whatsapp/webhook", json=payload)
            assert resp.status_code == 200

        # Mutation must be blocked
        meta_inst.update_campaign_status.assert_not_awaited()


@pytest.mark.asyncio
async def test_hitl_meta_api_error_logged(hitl_test_setup):
    """When Meta API returns error during pause, records ACTION_FAILED in AuditLog and notifies user."""
    data = hitl_test_setup
    token = generate_action_token(
        tenant_id=data["tenant_id"],
        campaign_id=data["campaign_id"],
        action="PAUSE",
    )
    payload = _build_whatsapp_button_webhook_payload(button_id=token, sender=data["sender"])

    with patch("app.api.endpoints.whatsapp_webhook.MetaGraphClient") as mock_meta_cls, \
         patch("app.api.endpoints.whatsapp_webhook.WhatsAppClient") as mock_wa_cls:
        meta_inst = AsyncMock()
        meta_inst.update_campaign_status.side_effect = MetaAPIError("Permissions error", code=200)
        mock_meta_cls.return_value = meta_inst
        wa_inst = AsyncMock()
        mock_wa_cls.return_value = wa_inst

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/v1/whatsapp/webhook", json=payload)
            assert resp.status_code == 200

        # User is notified of error
        wa_inst.send_text_message.assert_awaited()
        err_msg = wa_inst.send_text_message.await_args.kwargs["message_text"]
        assert "Meta Error" in err_msg

    # Verify AuditLog has ACTION_FAILED
    async with async_session_maker() as session:
        r = await session.execute(
            select(AuditLog).where(
                AuditLog.action_type == "ACTION_FAILED",
                AuditLog.tenant_id == uuid.UUID(data["tenant_id"]),
            )
        )
        logs = r.scalars().all()
        assert len(logs) == 1
        assert "Permissions error" in logs[0].action_details.get("error", "")
