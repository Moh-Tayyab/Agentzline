"""
Meta Ad Accounts API Endpoints.

CRUD operations for managed Meta ad accounts.
Bronze/Phase-1: Register accounts, list accounts, fetch cached metrics, trigger live sync.
"""

import uuid
from datetime import date, datetime
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from loguru import logger

from app.core.database import get_db
from app.models.tenant import Tenant
from app.models.ad_account import AdAccount
from app.models.metrics import CampaignMetricsSnapshot
from app.schemas.meta import AdAccountCreate, AdAccountResponse
from app.utils.meta_client import MetaGraphClient

router = APIRouter()


@router.post("/accounts", response_model=AdAccountResponse, status_code=status.HTTP_201_CREATED)
async def register_ad_account(
    account_data: AdAccountCreate,
    db: AsyncSession = Depends(get_db),
):
    """
    Register a new Meta ad account for monitoring and persist in database.
    """
    logger.info(f"📋 Registering ad account: {account_data.external_account_id} for tenant: {account_data.tenant_id}")

    # Validate tenant UUID
    try:
        tenant_uuid = uuid.UUID(account_data.tenant_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid tenant_id format. Must be a valid UUID.",
        )

    # Check tenant existence
    tenant_res = await db.execute(select(Tenant).where(Tenant.id == tenant_uuid))
    tenant = tenant_res.scalars().first()
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant with id {account_data.tenant_id} not found.",
        )

    # Check for duplicate external account
    existing = await db.execute(
        select(AdAccount).where(AdAccount.external_account_id == account_data.external_account_id)
    )
    if existing.scalars().first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Ad account with external_id {account_data.external_account_id} already registered.",
        )

    new_account = AdAccount(
        tenant_id=tenant_uuid,
        platform="META",
        external_account_id=account_data.external_account_id,
        account_name=account_data.account_name,
        max_budget_ceiling_pkr=float(account_data.max_budget_ceiling_pkr),
        target_cpa_pkr=float(account_data.target_cpa_pkr) if account_data.target_cpa_pkr is not None else None,
        target_roas=float(account_data.target_roas) if account_data.target_roas is not None else None,
        is_active=True,
    )
    db.add(new_account)
    await db.commit()
    await db.refresh(new_account)

    return AdAccountResponse(
        status="registered",
        external_account_id=new_account.external_account_id,
        account_name=new_account.account_name or "",
    )


@router.get("/accounts")
async def list_ad_accounts(
    tenant_id: str | None = Query(None, description="Optional tenant UUID filter"),
    db: AsyncSession = Depends(get_db),
):
    """List all registered ad accounts from database."""
    query = select(AdAccount)
    if tenant_id:
        try:
            t_uuid = uuid.UUID(tenant_id)
            query = query.where(AdAccount.tenant_id == t_uuid)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid tenant_id UUID format.",
            )

    result = await db.execute(query)
    accounts = result.scalars().all()

    return {
        "accounts": [
            {
                "id": str(acc.id),
                "tenant_id": str(acc.tenant_id),
                "external_account_id": acc.external_account_id,
                "account_name": acc.account_name,
                "platform": acc.platform,
                "is_active": acc.is_active,
                "max_budget_ceiling_pkr": float(acc.max_budget_ceiling_pkr),
                "target_cpa_pkr": float(acc.target_cpa_pkr) if acc.target_cpa_pkr else None,
                "target_roas": float(acc.target_roas) if acc.target_roas else None,
            }
            for acc in accounts
        ],
        "total": len(accounts),
    }


from app.skills.meta_normalizer import normalize_campaign_insight
from app.utils.meta_client import MetaGraphClient, MetaAPIError


async def _get_account_by_identifier(identifier: str, db: AsyncSession) -> AdAccount | None:
    """Resolve an AdAccount by either its internal UUID or external_account_id."""
    try:
        acc_uuid = uuid.UUID(identifier)
        condition = (AdAccount.id == acc_uuid) | (AdAccount.external_account_id == identifier)
    except ValueError:
        condition = (AdAccount.external_account_id == identifier)

    result = await db.execute(select(AdAccount).where(condition))
    return result.scalars().first()


@router.get("/accounts/{account_id}/metrics")
async def get_account_metrics(
    account_id: str,
    date_start: str | None = Query(None, description="Start date (YYYY-MM-DD)"),
    date_end: str | None = Query(None, description="End date (YYYY-MM-DD)"),
    db: AsyncSession = Depends(get_db),
):
    """
    Fetch cached campaign metrics snapshots from the database for an ad account.
    Resolves by either internal UUID or external_account_id.
    """
    logger.info(f"📊 Fetching metrics for account: {account_id}")

    account = await _get_account_by_identifier(account_id, db)
    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Ad account {account_id} not found.",
        )

    filters = [CampaignMetricsSnapshot.ad_account_id == account.id]
    if date_start:
        try:
            d_start = datetime.strptime(date_start, "%Y-%m-%d").date()
            filters.append(CampaignMetricsSnapshot.snapshot_date >= d_start)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date_start format (use YYYY-MM-DD).")
    if date_end:
        try:
            d_end = datetime.strptime(date_end, "%Y-%m-%d").date()
            filters.append(CampaignMetricsSnapshot.snapshot_date <= d_end)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date_end format (use YYYY-MM-DD).")

    metrics_res = await db.execute(select(CampaignMetricsSnapshot).where(and_(*filters)))
    snapshots = metrics_res.scalars().all()

    return {
        "account_id": account.external_account_id,
        "account_name": account.account_name,
        "metrics": [
            {
                "id": str(s.id),
                "external_campaign_id": s.external_campaign_id,
                "campaign_name": s.campaign_name,
                "snapshot_date": s.snapshot_date.isoformat(),
                "spend": float(s.spend),
                "impressions": s.impressions,
                "clicks": s.clicks,
                "conversions": s.conversions,
                "roas": float(s.roas),
                "ctr": float(s.ctr) if s.ctr is not None else None,
                "cpc": float(s.cpc) if s.cpc is not None else None,
                "cpa": float(s.cpa) if s.cpa is not None else None,
            }
            for s in snapshots
        ],
        "total": len(snapshots),
    }


@router.post("/accounts/{account_id}/sync")
async def trigger_metrics_sync(
    account_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Trigger immediate metrics pull from Meta Graph API and persist snapshots in DB.
    Uses canonical normalize_campaign_insight for identical metric calculations.
    Maps upstream Meta API failures to HTTP 502 Bad Gateway.
    """
    logger.info(f"🔄 Manual sync triggered for account: {account_id}")

    account = await _get_account_by_identifier(account_id, db)
    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Ad account {account_id} not found.",
        )

    client = MetaGraphClient()
    today = date.today()
    try:
        raw_insights = await client.get_account_insights(
            ad_account_id=account.external_account_id,
            date_start=today,
            date_end=today,
        )
    except MetaAPIError as meta_err:
        logger.error(f"Upstream Meta API failure during sync: {meta_err}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Meta Graph API error: {str(meta_err)}",
        )
    finally:
        await client.close()

    saved_count = 0
    for insight in raw_insights:
        norm = normalize_campaign_insight(insight)
        spend = float(norm["spend"])
        clicks = norm["clicks"]
        conversions = norm["conversions"]

        cpc = (spend / clicks) if clicks > 0 else 0.0
        cpa = (spend / conversions) if conversions > 0 else 0.0

        snapshot = CampaignMetricsSnapshot(
            ad_account_id=account.id,
            external_campaign_id=norm["id"],
            campaign_name=norm["name"],
            snapshot_date=today,
            spend=spend,
            impressions=norm["impressions"],
            clicks=clicks,
            conversions=conversions,
            roas=norm["roas"],
            ctr=norm["ctr"],
            cpc=cpc,
            cpa=cpa,
            raw_payload=insight,
        )
        db.add(snapshot)
        saved_count += 1

    await db.commit()

    return {
        "status": "synced",
        "account_id": account.external_account_id,
        "snapshots_saved": saved_count,
    }

