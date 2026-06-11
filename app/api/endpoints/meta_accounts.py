"""
Meta Ad Accounts API Endpoints.

CRUD operations for managed Meta ad accounts.
Bronze Tier: Register accounts, list campaigns, fetch metrics (read-only).
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger

from app.core.database import get_db
from app.schemas.meta import AdAccountCreate, AdAccountResponse

router = APIRouter()


@router.post("/accounts", response_model=AdAccountResponse)
async def register_ad_account(
    account_data: AdAccountCreate,
    db: AsyncSession = Depends(get_db),
):
    """
    Register a new Meta ad account for monitoring.

    Stores the external account ID and budget ceiling.
    The Meta access token is encrypted before database storage.
    """
    logger.info(f"📋 Registering ad account: {account_data.external_account_id}")
    # TODO: Implement with SQLAlchemy model
    return {
        "status": "registered",
        "external_account_id": account_data.external_account_id,
        "account_name": account_data.account_name,
    }


@router.get("/accounts")
async def list_ad_accounts(db: AsyncSession = Depends(get_db)):
    """List all registered ad accounts for the current tenant."""
    # TODO: Implement with SQLAlchemy model
    return {"accounts": [], "total": 0}


@router.get("/accounts/{account_id}/metrics")
async def get_account_metrics(
    account_id: str,
    date_start: str | None = None,
    date_end: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """
    Fetch cached metrics for an ad account.

    Returns spend, impressions, clicks, conversions, and ROAS
    for the specified date range. Defaults to yesterday if no dates provided.
    """
    logger.info(f"📊 Fetching metrics for account: {account_id}")
    # TODO: Query campaign_metrics_snapshots table
    return {"account_id": account_id, "metrics": [], "date_range": None}


@router.post("/accounts/{account_id}/sync")
async def trigger_metrics_sync(
    account_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Manually trigger a metrics sync from Meta Graph API.

    Pulls fresh data from Meta and stores in campaign_metrics_snapshots.
    """
    logger.info(f"🔄 Manual sync triggered for account: {account_id}")
    # TODO: Enqueue background task for Meta API data pull
    return {"status": "sync_enqueued", "account_id": account_id}
