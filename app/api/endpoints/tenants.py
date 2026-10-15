"""
Tenant / Agency Management API Endpoints.

CRUD operations for multi-tenant onboarding, language preferences,
and notification configurations.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.security import (
    enforce_tenant_access,
    generate_tenant_api_key,
    verify_api_key_dependency,
)
from app.models.tenant import Tenant
from app.schemas.tenant import TenantCreate, TenantResponse, TenantUpdate

router = APIRouter()


def _parse_tenant_uuid(tenant_id: str) -> uuid.UUID:
    try:
        return uuid.UUID(tenant_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid tenant_id format. Must be a valid UUID.",
        )


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_tenant(
    tenant_data: TenantCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(verify_api_key_dependency),
):
    """
    Onboard a new agency client / tenant.
    Configures bilingual reporting preferences and WhatsApp recipient number.
    """
    logger.info(f"🏢 Onboarding new tenant: {tenant_data.company_name}")

    tenant = Tenant(
        company_name=tenant_data.company_name,
        country_code=tenant_data.country_code,
        currency=tenant_data.currency,
        preferred_language=tenant_data.preferred_language,
        whatsapp_notification_number=tenant_data.whatsapp_notification_number,
    )
    # Issue API key once at onboarding (store only hash)
    raw_key, key_hash = generate_tenant_api_key()
    tenant.api_key_hash = key_hash
    db.add(tenant)
    await db.commit()
    await db.refresh(tenant)

    resp = TenantResponse(
        id=str(tenant.id),
        company_name=tenant.company_name,
        country_code=tenant.country_code,
        currency=tenant.currency,
        preferred_language=tenant.preferred_language,
        whatsapp_notification_number=tenant.whatsapp_notification_number,
        created_at=tenant.created_at,
        updated_at=tenant.updated_at,
        ad_accounts_count=0,
        active_credentials_count=0,
    )
    # Attach raw key out-of-band (only time it is visible)
    return {**resp.model_dump(), "api_key": raw_key}


@router.get("", response_model=dict)
async def list_tenants(
    request: Request,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    _auth=Depends(verify_api_key_dependency),
):
    """
    List registered tenants with pagination and account/credential counts.
    """
    result = await db.execute(
        select(Tenant)
        .options(selectinload(Tenant.ad_accounts), selectinload(Tenant.credentials))
        .offset(offset)
        .limit(limit)
    )
    tenants = result.scalars().all()

    total_count_res = await db.execute(select(func.count(Tenant.id)))
    total = total_count_res.scalar() or 0

    return {
        "tenants": [
            TenantResponse(
                id=str(t.id),
                company_name=t.company_name,
                country_code=t.country_code,
                currency=t.currency,
                preferred_language=t.preferred_language,
                whatsapp_notification_number=t.whatsapp_notification_number,
                created_at=t.created_at,
                updated_at=t.updated_at,
                ad_accounts_count=len(t.ad_accounts),
                active_credentials_count=len([c for c in t.credentials if c.token_status == "ACTIVE"]),
            )
            for t in tenants
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/{tenant_id}", response_model=TenantResponse)
async def get_tenant(
    tenant_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(verify_api_key_dependency),
):
    """
    Retrieve single tenant details.
    """
    enforce_tenant_access(request, tenant_id)
    t_uuid = _parse_tenant_uuid(tenant_id)
    result = await db.execute(
        select(Tenant)
        .options(selectinload(Tenant.ad_accounts), selectinload(Tenant.credentials))
        .where(Tenant.id == t_uuid)
    )
    tenant = result.scalars().first()
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant with id {tenant_id} not found.",
        )

    return TenantResponse(
        id=str(tenant.id),
        company_name=tenant.company_name,
        country_code=tenant.country_code,
        currency=tenant.currency,
        preferred_language=tenant.preferred_language,
        whatsapp_notification_number=tenant.whatsapp_notification_number,
        created_at=tenant.created_at,
        updated_at=tenant.updated_at,
        ad_accounts_count=len(tenant.ad_accounts),
        active_credentials_count=len([c for c in tenant.credentials if c.token_status == "ACTIVE"]),
    )


@router.patch("/{tenant_id}", response_model=TenantResponse)
async def update_tenant(
    tenant_id: str,
    updates: TenantUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(verify_api_key_dependency),
):
    """
    Update tenant profile, notification recipient, or language preference.
    """
    enforce_tenant_access(request, tenant_id)
    t_uuid = _parse_tenant_uuid(tenant_id)
    result = await db.execute(
        select(Tenant)
        .options(selectinload(Tenant.ad_accounts), selectinload(Tenant.credentials))
        .where(Tenant.id == t_uuid)
    )
    tenant = result.scalars().first()
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant with id {tenant_id} not found.",
        )

    if updates.company_name is not None:
        tenant.company_name = updates.company_name
    if updates.preferred_language is not None:
        tenant.preferred_language = updates.preferred_language
    if updates.whatsapp_notification_number is not None:
        tenant.whatsapp_notification_number = updates.whatsapp_notification_number
    if updates.currency is not None:
        tenant.currency = updates.currency

    await db.commit()
    await db.refresh(tenant)

    return TenantResponse(
        id=str(tenant.id),
        company_name=tenant.company_name,
        country_code=tenant.country_code,
        currency=tenant.currency,
        preferred_language=tenant.preferred_language,
        whatsapp_notification_number=tenant.whatsapp_notification_number,
        created_at=tenant.created_at,
        updated_at=tenant.updated_at,
        ad_accounts_count=len(tenant.ad_accounts),
        active_credentials_count=len([c for c in tenant.credentials if c.token_status == "ACTIVE"]),
    )


@router.delete("/{tenant_id}", status_code=status.HTTP_200_OK)
async def delete_tenant(
    tenant_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(verify_api_key_dependency),
):
    """
    Delete a tenant and cascade delete associated accounts and credentials.
    """
    enforce_tenant_access(request, tenant_id)
    t_uuid = _parse_tenant_uuid(tenant_id)
    result = await db.execute(select(Tenant).where(Tenant.id == t_uuid))
    tenant = result.scalars().first()
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant with id {tenant_id} not found.",
        )

    await db.delete(tenant)
    await db.commit()

    return {"status": "deleted", "tenant_id": str(t_uuid)}


@router.post("/{tenant_id}/api-key", status_code=status.HTTP_201_CREATED)
async def rotate_tenant_api_key(
    tenant_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(verify_api_key_dependency),
):
    """Rotate (or issue) a tenant API key. Returns raw key once — store securely."""
    enforce_tenant_access(request, tenant_id)
    t_uuid = _parse_tenant_uuid(tenant_id)
    result = await db.execute(select(Tenant).where(Tenant.id == t_uuid))
    tenant = result.scalars().first()
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant with id {tenant_id} not found.",
        )
    raw_key, key_hash = generate_tenant_api_key()
    tenant.api_key_hash = key_hash
    await db.commit()
    logger.info(f"🔑 Issued API key for tenant {tenant.id}")
    return {"tenant_id": str(tenant.id), "api_key": raw_key}
