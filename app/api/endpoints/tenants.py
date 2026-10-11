"""
Tenant / Agency Management API Endpoints.

CRUD operations for multi-tenant onboarding, language preferences,
and notification configurations.
"""

import uuid
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from loguru import logger

from app.core.database import get_db
from app.models.tenant import Tenant
from app.models.ad_account import AdAccount
from app.models.credential import PlatformCredential
from app.schemas.tenant import TenantCreate, TenantUpdate, TenantResponse

router = APIRouter()


def _parse_tenant_uuid(tenant_id: str) -> uuid.UUID:
    try:
        return uuid.UUID(tenant_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid tenant_id format. Must be a valid UUID.",
        )


@router.post("", response_model=TenantResponse, status_code=status.HTTP_201_CREATED)
async def create_tenant(
    tenant_data: TenantCreate,
    db: AsyncSession = Depends(get_db),
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
    db.add(tenant)
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
        ad_accounts_count=0,
        active_credentials_count=0,
    )


@router.get("", response_model=dict)
async def list_tenants(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
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
    db: AsyncSession = Depends(get_db),
):
    """
    Retrieve single tenant details.
    """
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
    db: AsyncSession = Depends(get_db),
):
    """
    Update tenant profile, notification recipient, or language preference.
    """
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
    db: AsyncSession = Depends(get_db),
):
    """
    Delete a tenant and cascade delete associated accounts and credentials.
    """
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
