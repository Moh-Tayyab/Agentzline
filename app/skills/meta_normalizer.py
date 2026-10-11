"""
Meta Insights Metrics Normalizer Skill.

Converts raw Meta Graph API string responses into typed, validated domain models.
Uses Decimal for precise currency math to avoid floating point drift in PKR.
Extracts conversions and purchase values using an allowlist of Meta action types.
Computes blended aggregate metrics for reporting.
"""

from decimal import Decimal, ROUND_HALF_UP
from typing import Any
from loguru import logger

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
