"""
Credential Vault API Endpoints.

Phase-1 Task #2: Multi-tenant PlatformCredential management.
All tokens are encrypted at rest via app.core.security.encrypt_token().
Plaintext tokens are never persisted or returned.
"""

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import encrypt_token, enforce_tenant_access, verify_api_key_dependency
from app.models.credential import PlatformCredential
from app.models.tenant import Tenant

router = APIRouter()

VALID_PLATFORMS = ("META", "WHATSAPP")


class CredentialCreate(BaseModel):
    """Request body for registering a vault credential."""

    tenant_id: str = Field(..., description="UUID of the owning tenant")
    platform_name: str = Field(..., description="META | WHATSAPP")
    access_token: str = Field(..., min_length=1, description="Plaintext token (encrypted at rest)")
    refresh_token: str | None = Field(None, description="Optional plaintext refresh token")
    meta_business_id: str | None = Field(None, description="Meta Business ID (META only)")
    expires_in_days: int | None = Field(
        None, ge=0, description="Days until expiry. None = no expiry (e.g. permanent WhatsApp token)"
    )


class CredentialRotate(BaseModel):
    """Request body for rotating a vault credential."""

    access_token: str = Field(..., min_length=1)
    refresh_token: str | None = None
    expires_in_days: int | None = Field(None, ge=0)


def _credential_to_status(cred: PlatformCredential) -> dict:
    """Serialize a credential row to a status dict (never includes plaintext)."""
    now = datetime.now(UTC)
    expires_at = cred.expires_at
    if expires_at is not None and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    days_left: int | None = None
    if expires_at is not None:
        days_left = (expires_at - now).days
    return {
        "id": str(cred.id),
        "tenant_id": str(cred.tenant_id),
        "platform_name": cred.platform_name,
        "token_status": cred.token_status,
        "expires_at": expires_at.isoformat() if expires_at else None,
        "days_left": days_left,
        "meta_business_id": cred.meta_business_id,
        "last_rotated_at": cred.last_rotated_at.isoformat() if cred.last_rotated_at else None,
    }


async def _get_tenant_or_404(tenant_id: str, db: AsyncSession) -> Tenant:
    try:
        t_uuid = uuid.UUID(tenant_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid tenant_id format. Must be a valid UUID.")
    res = await db.execute(select(Tenant).where(Tenant.id == t_uuid))
    tenant = res.scalars().first()
    if not tenant:
        raise HTTPException(status_code=404, detail=f"Tenant with id {tenant_id} not found.")
    return tenant


@router.post("", status_code=status.HTTP_201_CREATED)
async def register_credential(
    payload: CredentialCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(verify_api_key_dependency),
):
    """Register (or upsert) a vault credential for a tenant. Encrypts tokens at rest."""
    enforce_tenant_access(request, payload.tenant_id)
    platform = payload.platform_name.upper()
    if platform not in VALID_PLATFORMS:
        raise HTTPException(status_code=400, detail=f"platform_name must be one of {VALID_PLATFORMS}.")

    tenant = await _get_tenant_or_404(payload.tenant_id, db)

    expires_at = None
    if payload.expires_in_days is not None:
        expires_at = datetime.now(UTC) + timedelta(days=payload.expires_in_days)

    # Upsert: one ACTIVE credential per (tenant, platform)
    existing_res = await db.execute(
        select(PlatformCredential).where(
            PlatformCredential.tenant_id == tenant.id,
            PlatformCredential.platform_name == platform,
            PlatformCredential.token_status == "ACTIVE",
        )
    )
    existing = existing_res.scalars().first()

    encrypted_access = encrypt_token(payload.access_token)
    encrypted_refresh = encrypt_token(payload.refresh_token) if payload.refresh_token else None

    if existing:
        existing.encrypted_access_token = encrypted_access
        if encrypted_refresh is not None:
            existing.encrypted_refresh_token = encrypted_refresh
        if payload.meta_business_id is not None:
            existing.meta_business_id = payload.meta_business_id
        existing.expires_at = expires_at
        existing.token_status = "ACTIVE"
        existing.last_rotated_at = datetime.now(UTC)
        await db.commit()
        await db.refresh(existing)
        logger.info(f"🔁 Rotated existing {platform} credential for tenant {tenant.id}")
        return {"status": "rotated", "credential": _credential_to_status(existing)}

    cred = PlatformCredential(
        tenant_id=tenant.id,
        platform_name=platform,
        encrypted_access_token=encrypted_access,
        encrypted_refresh_token=encrypted_refresh,
        meta_business_id=payload.meta_business_id,
        token_status="ACTIVE",
        expires_at=expires_at,
    )
    db.add(cred)
    await db.commit()
    await db.refresh(cred)
    logger.info(f"🔐 Registered {platform} credential for tenant {tenant.id}")
    return {"status": "registered", "credential": _credential_to_status(cred)}


@router.post("/{credential_id}/rotate")
async def rotate_credential(
    credential_id: str,
    payload: CredentialRotate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(verify_api_key_dependency),
):
    """Rotate an existing credential with a new token value."""
    try:
        c_uuid = uuid.UUID(credential_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid credential_id format.")
    res = await db.execute(select(PlatformCredential).where(PlatformCredential.id == c_uuid))
    cred = res.scalars().first()
    if not cred:
        raise HTTPException(status_code=404, detail=f"Credential {credential_id} not found.")
    enforce_tenant_access(request, cred.tenant_id)

    cred.encrypted_access_token = encrypt_token(payload.access_token)
    if payload.refresh_token is not None:
        cred.encrypted_refresh_token = encrypt_token(payload.refresh_token)
    if payload.expires_in_days is not None:
        cred.expires_at = datetime.now(UTC) + timedelta(days=payload.expires_in_days)
    cred.token_status = "ACTIVE"
    cred.last_rotated_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(cred)
    logger.info(f"🔁 Rotated credential {cred.id} ({cred.platform_name})")
    return {"status": "rotated", "credential": _credential_to_status(cred)}


@router.get("/status")
async def credential_status(
    request: Request,
    tenant_id: str | None = Query(None, description="Optional tenant UUID filter"),
    db: AsyncSession = Depends(get_db),
    _auth=Depends(verify_api_key_dependency),
):
    """List credential lifecycle status (no plaintext). Includes days_left."""
    query = select(PlatformCredential)
    if tenant_id:
        try:
            t_uuid = uuid.UUID(tenant_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid tenant_id UUID format.")
        query = query.where(PlatformCredential.tenant_id == t_uuid)
    res = await db.execute(query)
    creds = res.scalars().all()
    items = [_credential_to_status(c) for c in creds]
    return {"credentials": items, "total": len(items)}
