"""
Meta Ads Schemas.

Pydantic models for Meta Graph API integration — Bronze Tier (read-only).
"""

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field


# ── Request Schemas ──────────────────────────────────────────────────────────

class AdAccountCreate(BaseModel):
    """Request body for registering a new Meta ad account."""
    tenant_id: str = Field(..., description="UUID of the owning tenant")
    external_account_id: str = Field(..., description="Meta ad account ID (act_XXXXXXXXXX)")
    account_name: str = Field(..., description="Human-readable brand/account name")
    max_budget_ceiling_pkr: Decimal = Field(
        ..., gt=0, description="Hard budget ceiling in PKR — never exceeded by any agent"
    )
    target_cpa_pkr: Decimal | None = Field(None, description="Target cost per acquisition in PKR")
    target_roas: float | None = Field(None, description="Target return on ad spend")


class MetricsSyncRequest(BaseModel):
    """Request to trigger a metrics sync from Meta API."""
    account_id: str
    date_start: date | None = None
    date_end: date | None = None


# ── Response Schemas ─────────────────────────────────────────────────────────

class AdAccountResponse(BaseModel):
    """Response after registering or fetching an ad account."""
    status: str
    external_account_id: str
    account_name: str


class CampaignMetrics(BaseModel):
    """Single campaign metrics snapshot from Meta."""
    external_campaign_id: str
    campaign_name: str
    snapshot_date: date
    spend: Decimal
    impressions: int
    clicks: int
    conversions: int
    roas: Decimal
    ctr: float | None = None
    cpc: Decimal | None = None
    cpa: Decimal | None = None


class DailyAccountSummary(BaseModel):
    """
    Aggregated daily summary for a single ad account.

    Used to generate the bilingual WhatsApp executive report.
    """
    account_name: str
    date: date
    total_spend: Decimal
    total_impressions: int
    total_clicks: int
    total_conversions: int
    aggregate_roas: Decimal
    aggregate_ctr: float
    aggregate_cpc: Decimal
    campaigns_count: int
    anomalies: list[str] = Field(default_factory=list)
    campaigns: list[CampaignMetrics] = Field(default_factory=list)
