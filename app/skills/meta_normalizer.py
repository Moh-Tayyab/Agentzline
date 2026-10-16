"""
Meta Insights Metrics Normalizer Skill.

Converts raw Meta Graph API string responses into typed, validated domain models.
Uses Decimal for precise currency math to avoid floating point drift in PKR.
Extracts conversions and purchase values using an allowlist of Meta action types.
Computes blended aggregate metrics for reporting.
"""

from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# Allowlist of conversion actions recognized for e-commerce purchase tracking
PURCHASE_ACTION_TYPES = {
    "purchase",
    "omni_purchase",
    "offsite_conversion.fb_pixel_purchase",
}


def _to_decimal(val: Any) -> Decimal:
    """Safely convert string or numeric value to Decimal."""
    if val is None or val == "":
        return Decimal("0.00")
    try:
        return Decimal(str(val))
    except Exception:
        return Decimal("0.00")


def normalize_campaign_insight(raw: dict[str, Any]) -> dict[str, Any]:
    """
    Normalize a single raw campaign insight dictionary from Meta API.

    Handles:
    - Decimal conversion for spend, cpc, cpa, purchase_value
    - Parsing nested actions and action_values arrays
    - Extraction of purchase count and purchase revenue
    - Calculation of campaign-level ROAS with zero-spend protection
    """
    campaign_id = str(raw.get("campaign_id", ""))
    campaign_name = str(raw.get("campaign_name", "Unnamed Campaign"))

    spend = _to_decimal(raw.get("spend", "0"))
    impressions = int(raw.get("impressions", 0))
    clicks = int(raw.get("clicks", 0))
    frequency = float(raw.get("frequency", 1.0))
    ctr = float(raw.get("ctr", 0.0))

    # Extract conversions (purchases) from nested actions array
    conversions = 0
    actions = raw.get("actions", [])
    if isinstance(actions, list):
        for action in actions:
            if action.get("action_type") in PURCHASE_ACTION_TYPES:
                try:
                    conversions += int(_to_decimal(action.get("value", 0)))
                except (ValueError, TypeError):
                    pass

    # Extract purchase value (revenue) from nested action_values array
    purchase_value = Decimal("0.00")
    action_values = raw.get("action_values", [])
    if isinstance(action_values, list):
        for action_val in action_values:
            if action_val.get("action_type") in PURCHASE_ACTION_TYPES:
                purchase_value += _to_decimal(action_val.get("value", 0))

    # Campaign ROAS: revenue / spend (if spend > 0)
    roas = (purchase_value / spend) if spend > Decimal("0") else Decimal("0.00")

    return {
        "id": campaign_id,
        "name": campaign_name,
        "spend": spend,
        "impressions": impressions,
        "clicks": clicks,
        "conversions": conversions,
        "purchase_value": purchase_value,
        "roas": float(roas.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "frequency": frequency,
        "ctr": ctr,
        "raw_payload": raw,  # Retained for JSONB storage and reprocessing
    }


def normalize_and_aggregate_metrics(
    raw_insights: list[dict[str, Any]],
    account_name: str = "Meta Ad Account",
    target_date: str = "Yesterday",
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """
    Normalize all raw campaign metrics and compute aggregate account summary.

    Returns:
        tuple of (normalized_campaigns, daily_summary)
    """
    normalized_campaigns = [normalize_campaign_insight(r) for r in raw_insights]

    total_spend = sum((c["spend"] for c in normalized_campaigns), Decimal("0.00"))
    total_impressions = sum(c["impressions"] for c in normalized_campaigns)
    total_clicks = sum(c["clicks"] for c in normalized_campaigns)
    total_conversions = sum(c["conversions"] for c in normalized_campaigns)
    total_revenue = sum((c["purchase_value"] for c in normalized_campaigns), Decimal("0.00"))

    # Blended ROAS: total revenue / total spend
    if total_spend > Decimal("0"):
        aggregate_roas = float((total_revenue / total_spend).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    else:
        aggregate_roas = 0.0

    # Aggregate CTR: (clicks / impressions) * 100
    if total_impressions > 0:
        aggregate_ctr = round((total_clicks / total_impressions) * 100, 2)
    else:
        aggregate_ctr = 0.0

    daily_summary = {
        "account_name": account_name,
        "date": target_date,
        "total_spend": float(total_spend.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "total_impressions": total_impressions,
        "total_clicks": total_clicks,
        "total_conversions": total_conversions,
        "aggregate_roas": aggregate_roas,
        "aggregate_ctr": aggregate_ctr,
        "total_revenue": float(total_revenue.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
    }

    logger.info(
        f"📊 Normalized {len(normalized_campaigns)} campaigns: "
        f"Spend={daily_summary['total_spend']} PKR, ROAS={daily_summary['aggregate_roas']}x"
    )

    return normalized_campaigns, daily_summary


async def persist_normalized_snapshots(
    session: AsyncSession,
    tenant_id: Any,
    normalized_metrics: list[dict[str, Any]],
    snapshot_date: date,
    account_map: dict[str, Any] | None = None,
) -> int:
    """Upsert CampaignMetricsSnapshot rows for normalized Meta insights.

    Each raw insight may carry `_ad_account_external_id` (tagged by
    fetch_metrics_node). `account_map` maps external_account_id -> AdAccount DB id.
    When account ownership is unknown, falls back to resolving active tenant
    accounts. Upserts on (ad_account_id, external_campaign_id, snapshot_date)
    so re-syncing the same day never multiplies ad spend.

    Returns:
        Number of snapshots upserted.
    """
    from app.models.ad_account import AdAccount
    from app.models.metrics import CampaignMetricsSnapshot

    if account_map is None:
        account_map = {}
        acc_res = await session.execute(
            select(AdAccount).where(
                AdAccount.tenant_id == tenant_id,
                AdAccount.is_active.is_(True),
            )
        )
        for acc in acc_res.scalars().all():
            account_map[acc.external_account_id] = acc.id
            account_map[str(acc.id)] = acc.id

    # If only one active account, default orphan insights to it
    default_account_id = None
    if len({v for v in account_map.values()}) == 1:
        default_account_id = next(iter(account_map.values()))

    saved = 0
    for norm in normalized_metrics:
        ext_id = norm.get("_ad_account_external_id") or (norm.get("raw_payload") or {}).get(
            "_ad_account_external_id"
        )
        ad_account_id = account_map.get(str(ext_id)) if ext_id else None
        if ad_account_id is None:
            ad_account_id = default_account_id
        if ad_account_id is None:
            continue
        cid = str(norm.get("id", ""))
        if not cid:
            continue
        spend = float(norm.get("spend", 0) or 0)
        clicks = int(norm.get("clicks", 0) or 0)
        conversions = int(norm.get("conversions", 0) or 0)
        cpc = (spend / clicks) if clicks > 0 else 0.0
        cpa = (spend / conversions) if conversions > 0 else 0.0

        existing_res = await session.execute(
            select(CampaignMetricsSnapshot).where(
                CampaignMetricsSnapshot.ad_account_id == ad_account_id,
                CampaignMetricsSnapshot.external_campaign_id == cid,
                CampaignMetricsSnapshot.snapshot_date == snapshot_date,
            )
        )
        existing = existing_res.scalars().first()
        if existing:
            existing.campaign_name = norm.get("name")
            existing.spend = spend
            existing.impressions = int(norm.get("impressions", 0) or 0)
            existing.clicks = clicks
            existing.conversions = conversions
            existing.roas = float(norm.get("roas", 0.0) or 0.0)
            existing.ctr = float(norm.get("ctr", 0.0) or 0.0)
            existing.cpc = cpc
            existing.cpa = cpa
            existing.raw_payload = norm.get("raw_payload")
        else:
            session.add(
                CampaignMetricsSnapshot(
                    ad_account_id=ad_account_id,
                    external_campaign_id=cid,
                    campaign_name=norm.get("name"),
                    snapshot_date=snapshot_date,
                    spend=spend,
                    impressions=int(norm.get("impressions", 0) or 0),
                    clicks=clicks,
                    conversions=conversions,
                    roas=float(norm.get("roas", 0.0) or 0.0),
                    ctr=float(norm.get("ctr", 0.0) or 0.0),
                    cpc=cpc,
                    cpa=cpa,
                    raw_payload=norm.get("raw_payload"),
                )
            )
        saved += 1
    await session.flush()
    return saved
