"""
Intraday Pacing Detection Skill (Phase-2).

Deterministic early-warning detector for intraday budget bleed:
a campaign that has already burned a large fraction of its daily budget
with zero conversions and weak CTR deserves an urgent same-day alert —
not a next-morning post-mortem.

Strict rule (all three must hold):
  1. intraday spend > INTRADAY_BLEED_SPEND_RATIO × daily budget
  2. conversions == 0
  3. CTR < INTRADAY_BLEED_CTR_THRESHOLD

Campaigns without a known daily budget are skipped (no alert) to
eliminate false positives.
"""

import time
from decimal import Decimal
from typing import Any

from loguru import logger

_BUDGET_CACHE: dict[str, tuple[Decimal, float]] = {}


def get_cached_budget(campaign_id: str) -> Decimal | None:
    """Retrieve cached daily budget for a campaign if not expired."""
    entry = _BUDGET_CACHE.get(str(campaign_id))
    if not entry:
        return None
    val, expires_at = entry
    if time.time() > expires_at:
        _BUDGET_CACHE.pop(str(campaign_id), None)
        return None
    return val


def set_cached_budget(campaign_id: str, budget: Decimal, ttl_seconds: float = 43200.0) -> None:
    """Cache daily budget with TTL (default 12 hours)."""
    _BUDGET_CACHE[str(campaign_id)] = (budget, time.time() + ttl_seconds)


def clear_budget_cache() -> None:
    """Clear all cached campaign budgets."""
    _BUDGET_CACHE.clear()


def parse_meta_budget_to_pkr(raw_budget: Any) -> Decimal | None:
    """
    Parse a Meta daily_budget / lifetime_budget value to PKR.

    Meta returns budgets in minor currency units as strings
    (e.g. "500000" = 5000.00 PKR). Returns None when unparseable.
    """
    if raw_budget is None or raw_budget == "":
        return None
    try:
        return (Decimal(str(raw_budget)) / Decimal("100")).quantize(Decimal("0.01"))
    except Exception:
        return None


def detect_intraday_pacing_alerts(
    metrics: list[dict[str, Any]],
    budgets_by_campaign: dict[str, Decimal],
    spend_ratio: float = 0.5,
    ctr_threshold: float = 0.6,
) -> list[dict[str, Any]]:
    """
    Scan normalized intraday campaign metrics for pacing bleed.

    Args:
        metrics: Normalized campaign dicts (from normalize_campaign_insight).
        budgets_by_campaign: Daily budget per campaign id (PKR Decimal).
        spend_ratio: Alert when spend exceeds this fraction of daily budget.
        ctr_threshold: Alert only when CTR is strictly below this %.

    Returns:
        List of pacing alert dicts with type, campaign info, and details.
    """
    alerts: list[dict[str, Any]] = []

    for campaign in metrics:
        campaign_id = str(campaign.get("id", ""))
        campaign_name = str(campaign.get("name", "Unnamed Campaign"))
        spend_raw = campaign.get("spend", 0)
        spend = spend_raw if isinstance(spend_raw, Decimal) else Decimal(str(spend_raw or 0))
        conversions = int(campaign.get("conversions", 0) or 0)
        ctr = float(campaign.get("ctr", 0.0) or 0.0)

        budget = budgets_by_campaign.get(campaign_id)
        if budget is None or budget <= Decimal("0"):
            continue  # unknown budget → skip (no false positives)

        spend_fraction = float(spend / budget) if budget > 0 else 0.0
        if spend_fraction > spend_ratio and conversions == 0 and ctr < ctr_threshold:
            alerts.append({
                "type": "INTRADAY_PACING_BLEED",
                "campaign_id": campaign_id,
                "campaign_name": campaign_name,
                "details": {
                    "spend": float(spend),
                    "daily_budget": float(budget),
                    "spend_fraction": round(spend_fraction, 3),
                    "conversions": 0,
                    "ctr": ctr,
                },
            })

    logger.info(f"⏱️ Intraday pacing scan: {len(alerts)} bleed alerts across {len(metrics)} campaigns")
    return alerts


def format_pacing_alert(
    alert: dict[str, Any],
    language: str = "roman_urdu",
) -> str:
    """
    Format a single pacing alert as a bilingual urgent WhatsApp message.
    """
    details = alert.get("details", {})
    name = alert.get("campaign_name", "Unnamed Campaign")
    spend = details.get("spend", 0)
    budget = details.get("daily_budget", 0)
    pct = details.get("spend_fraction", 0) * 100
    ctr = details.get("ctr", 0.0)

    if language == "english":
        return (
            f"🚨 *Intraday Pacing Alert — {name}*\n"
            f"Already spent *{spend:,.0f} PKR* ({pct:.0f}% of {budget:,.0f} PKR daily budget) "
            f"with *zero conversions* (CTR {ctr:.2f}%).\n"
            f"Projected waste by tonight can be huge — pause or cut budget now?"
        )
    return (
        f"🚨 *Intraday Pacing Alert — {name}*\n"
        f"Abhi tak *{spend:,.0f} PKR* kharch ({budget:,.0f} PKR budget ka {pct:.0f}%) "
        f"lekin *koi conversion nahi* (CTR {ctr:.2f}%).\n"
        f"Raat tak bara waste ho sakta hai — foran pause ya budget cut karein?"
    )
