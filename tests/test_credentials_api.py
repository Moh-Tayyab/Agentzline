"""
Tests for Credential Vault API + Token Expiry Watchdog (Phase-1 Task #2).
"""

import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import async_session_maker
from app.core.security import decrypt_token
from app.models.tenant import Tenant
from app.models.credential import PlatformCredential
from app.models.audit_log import AuditLog
from app.agents.scheduler import run_token_expiry_watchdog


@pytest.fixture
async def vault_tenant():
    """Seed a tenant for vault tests."""
    t_id = uuid.uuid4()
    async with async_session_maker() as session:
        tenant = Tenant(
            id=t_id,
            company_name="Vault Test Co",
            country_code="PK",
            currency="PKR",
            preferred_language="roman_urdu",
            whatsapp_notification_number="+923001112223",
        )
        session.add(tenant)
        await session.commit()
    return tenant


@pytest.mark.asyncio
async def test_register_credential_encrypts_at_rest(client: AsyncClient, vault_tenant):
    """POST /credentials encrypts the token — DB must not contain plaintext."""
    payload = {
        "tenant_id": str(vault_tenant.id),
        "platform_name": "META",
        "access_token": "super-secret-meta-token-123",
        "expires_in_days": 60,
        "meta_business_id": "biz_001",
    }
    res = await client.post("/api/v1/credentials", json=payload)
    assert res.status_code == 201
    data = res.json()
    assert data["status"] == "registered"
    cred = data["credential"]
    assert cred["platform_name"] == "META"
    assert cred["token_status"] == "ACTIVE"
    assert cred["days_left"] is not None and 59 <= cred["days_left"] <= 60

    async with async_session_maker() as session:
        r = await session.execute(
            select(PlatformCredential).where(PlatformCredential.tenant_id == vault_tenant.id)
        )
        row = r.scalars().first()
        assert row is not None
        assert row.encrypted_access_token != "super-secret-meta-token-123"
        assert decrypt_token(row.encrypted_access_token) == "super-secret-meta-token-123"


@pytest.mark.asyncio
async def test_register_credential_invalid_tenant(client: AsyncClient):
    """Unknown tenant_id returns 404."""
    res = await client.post("/api/v1/credentials", json={
        "tenant_id": str(uuid.uuid4()),
        "platform_name": "META",
        "access_token": "x",
    })
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_rotate_credential(client: AsyncClient, vault_tenant):
    """POST /credentials/{id}/rotate swaps the stored token."""
    await client.post("/api/v1/credentials", json={
        "tenant_id": str(vault_tenant.id),
        "platform_name": "WHATSAPP",
        "access_token": "old-token",
    })
    async with async_session_maker() as session:
        r = await session.execute(select(PlatformCredential).where(
            PlatformCredential.tenant_id == vault_tenant.id,
            PlatformCredential.platform_name == "WHATSAPP",
        ))
        row = r.scalars().first()
        cred_id = str(row.id)

    rot = await client.post(f"/api/v1/credentials/{cred_id}/rotate", json={
        "access_token": "new-token-456",
    })
    assert rot.status_code == 200
    assert rot.json()["status"] == "rotated"

    async with async_session_maker() as session:
        r = await session.execute(select(PlatformCredential).where(
            PlatformCredential.id == uuid.UUID(cred_id)
        ))
        row = r.scalars().first()
        assert decrypt_token(row.encrypted_access_token) == "new-token-456"


@pytest.mark.asyncio
async def test_credential_status_lists(client: AsyncClient, vault_tenant):
    """GET /credentials/status returns lifecycle info without plaintext."""
    await client.post("/api/v1/credentials", json={
        "tenant_id": str(vault_tenant.id),
        "platform_name": "META",
        "access_token": "tok",
        "expires_in_days": 10,
    })
    res = await client.get(f"/api/v1/credentials/status?tenant_id={vault_tenant.id}")
    assert res.status_code == 200
    body = res.json()
    assert body["total"] >= 1
    for item in body["credentials"]:
        assert "encrypted_access_token" not in item
        assert "access_token" not in item
        assert "days_left" in item


@pytest.mark.asyncio
async def test_watchdog_warns_expiring_token(vault_tenant):
    """Watchdog sends bilingual WhatsApp alert + TOKEN_EXPIRY_WARNING audit for <7d tokens."""
    async with async_session_maker() as session:
        from app.core.security import encrypt_token as enc
        cred = PlatformCredential(
            tenant_id=vault_tenant.id,
            platform_name="META",
            encrypted_access_token=enc("expiring-token"),
            token_status="ACTIVE",
            expires_at=datetime.now(timezone.utc) + timedelta(days=5, hours=2),
        )
        session.add(cred)
        await session.commit()

    with patch("app.agents.scheduler.WhatsAppClient") as mock_cls:
        mock_inst = AsyncMock()
        mock_cls.return_value = mock_inst
        stats = await run_token_expiry_watchdog()

    assert stats["warned"] >= 1
    mock_inst.send_text_message.assert_awaited_once()
    kwargs = mock_inst.send_text_message.await_args.kwargs
    assert kwargs["recipient_number"] == "+923001112223"
    assert "5 din" in kwargs["message_text"]  # Roman Urdu per tenant preference

    async with async_session_maker() as session:
        r = await session.execute(select(AuditLog).where(
            AuditLog.tenant_id == vault_tenant.id,
            AuditLog.action_type == "TOKEN_EXPIRY_WARNING",
        ))
        assert r.scalars().first() is not None


@pytest.mark.asyncio
async def test_watchdog_expires_past_due_token(vault_tenant):
    """Watchdog marks past-due tokens EXPIRED + TOKEN_EXPIRED audit, no WhatsApp send."""
    async with async_session_maker() as session:
        from app.core.security import encrypt_token as enc
        cred = PlatformCredential(
            tenant_id=vault_tenant.id,
            platform_name="META",
            encrypted_access_token=enc("dead-token"),
            token_status="ACTIVE",
            expires_at=datetime.now(timezone.utc) - timedelta(days=1),
        )
        session.add(cred)
        await session.commit()
        cred_id = cred.id

    with patch("app.agents.scheduler.WhatsAppClient") as mock_cls:
        mock_inst = AsyncMock()
        mock_cls.return_value = mock_inst
        stats = await run_token_expiry_watchdog()

    assert stats["expired"] >= 1
    mock_inst.send_text_message.assert_not_awaited()

    async with async_session_maker() as session:
        row = (await session.execute(select(PlatformCredential).where(
            PlatformCredential.id == cred_id
        ))).scalars().first()
        assert row.token_status == "EXPIRED"
        r = await session.execute(select(AuditLog).where(
            AuditLog.action_type == "TOKEN_EXPIRED",
        ))
        assert r.scalars().first() is not None
