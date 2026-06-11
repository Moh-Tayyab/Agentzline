"""
Meta Ads Performance Analysis Skill.

Deterministic analysis engine that processes raw Meta campaign metrics
and identifies performance anomalies without requiring AI inference.

This is the core analytical brain of the Bronze Tier.
"""

from typing import Any

from loguru import logger

from app.core.config import get_settings


def detect_performance_anomalies(
    metrics: list[dict[str, Any]],
    language: str = "roman_urdu",
    target_cpa: float | None = None,
    target_roas: float | None = None,
) -> list[dict[str, Any]]:
    """
    Scan campaign metrics for performance anomalies.

    Detection rules:
    1. CPA Surge: CPA exceeds target by >25%
    2. ROAS Drop: ROAS below target threshold
    3. Ad Fatigue: Frequency > 4.0 (high ad exposure)
    4. Budget Bleed: Spend > 3000 PKR with zero conversions

    Args:
        metrics: List of campaign metric dictionaries from Meta API.
        language: Output language for messages (roman_urdu | english).
        target_cpa: Override CPA target (falls back to settings default).
        target_roas: Override ROAS target (falls back to settings default).

    Returns:
        List of anomaly dictionaries with type, campaign info, and message.
    """
    settings = get_settings()
    target_cpa = target_cpa or settings.DEFAULT_TARGET_CPA_PKR
    target_roas = target_roas or settings.DEFAULT_TARGET_ROAS
    surge_pct = settings.CPA_SURGE_THRESHOLD_PERCENT / 100.0

    anomalies: list[dict[str, Any]] = []

    for campaign in metrics:
        campaign_name = campaign.get("name", "Unnamed Campaign")
        campaign_id = campaign.get("id", "")
        spend = float(campaign.get("spend", 0.0))
        conversions = int(campaign.get("conversions", 0))
        roas = float(campaign.get("roas", 0.0))
        ctr = float(campaign.get("ctr", 0.0))
        frequency = float(campaign.get("frequency", 0.0))

        # Calculate CPA
        cpa = spend / conversions if conversions > 0 else float("inf")

        # Rule 1: CPA Surge
        if cpa != float("inf") and cpa > (target_cpa * (1 + surge_pct)) and spend > 3000:
            anomalies.append(
                _build_anomaly(
                    anomaly_type="CPA_SURGE",
                    campaign_id=campaign_id,
                    campaign_name=campaign_name,
                    details={"cpa": cpa, "target_cpa": target_cpa, "spend": spend},
                    language=language,
                )
            )

        # Rule 2: ROAS Drop (ROAS Rescue trigger)
        if roas < target_roas and spend > 3000:
            anomalies.append(
                _build_anomaly(
                    anomaly_type="ROAS_DROP",
                    campaign_id=campaign_id,
                    campaign_name=campaign_name,
                    details={"roas": roas, "target_roas": target_roas, "spend": spend},
                    language=language,
                )
            )

        # Rule 3: Ad Fatigue
        if frequency > 4.0:
            anomalies.append(
                _build_anomaly(
                    anomaly_type="AD_FATIGUE",
                    campaign_id=campaign_id,
                    campaign_name=campaign_name,
                    details={"frequency": frequency, "ctr": ctr},
                    language=language,
                )
            )

        # Rule 4: Budget Bleed
        if spend > 3000 and conversions == 0:
            anomalies.append(
                _build_anomaly(
                    anomaly_type="BUDGET_BLEED",
                    campaign_id=campaign_id,
                    campaign_name=campaign_name,
                    details={"spend": spend, "conversions": 0},
                    language=language,
                )
            )

    logger.info(f"🔍 Detected {len(anomalies)} anomalies across {len(metrics)} campaigns")
    return anomalies


def _build_anomaly(
    anomaly_type: str,
    campaign_id: str,
    campaign_name: str,
    details: dict[str, Any],
    language: str,
) -> dict[str, Any]:
    """Build a single anomaly record with bilingual message."""

    if anomaly_type == "CPA_SURGE":
        if language == "roman_urdu":
            message = (
                f"⚠️ *CPA Alert — {campaign_name}*\n"
                f"Aapki campaign ka CPA *{details['cpa']:.0f} PKR* par hai, "
                f"jo target ({details['target_cpa']:.0f} PKR) se kafi zyada hai. "
                f"Spend: *{details['spend']:.0f} PKR*.\n"
                f"Mashwara: Campaign pause kar dein ya budget reduce karein?"
            )
        else:
            message = (
                f"⚠️ *CPA Alert — {campaign_name}*\n"
                f"CPA is at *{details['cpa']:.0f} PKR*, well above the target of "
                f"*{details['target_cpa']:.0f} PKR*. Spend: *{details['spend']:.0f} PKR*.\n"
                f"Recommendation: Pause or reduce budget immediately."
            )

    elif anomaly_type == "ROAS_DROP":
        if language == "roman_urdu":
            message = (
                f"📉 *ROAS Rescue — {campaign_name}*\n"
                f"ROAS sirf *{details['roas']:.2f}* hai, target ({details['target_roas']:.2f}) se neeche. "
                f"Spend ho chuka: *{details['spend']:.0f} PKR*.\n"
                f"Creative swap ya ad-set pause ki zaroorat hai."
            )
        else:
            message = (
                f"📉 *ROAS Rescue — {campaign_name}*\n"
                f"ROAS is *{details['roas']:.2f}*, below target of *{details['target_roas']:.2f}*. "
                f"Total Spend: *{details['spend']:.0f} PKR*.\n"
                f"Consider a creative swap or ad-set pause."
            )

    elif anomaly_type == "AD_FATIGUE":
        if language == "roman_urdu":
            message = (
                f"🔄 *Ad Fatigue — {campaign_name}*\n"
                f"Frequency *{details['frequency']:.1f}* tak pohanch gayi hai (CTR: {details['ctr']:.2f}%). "
                f"Log bar bar same ad dekh rahe hain.\n"
                f"Naya creative launch karein ya audience refresh karein."
            )
        else:
            message = (
                f"🔄 *Ad Fatigue — {campaign_name}*\n"
                f"Frequency has reached *{details['frequency']:.1f}* (CTR: {details['ctr']:.2f}%). "
                f"Audience is seeing the same ad repeatedly.\n"
                f"Refresh creative or expand audience."
            )

    elif anomaly_type == "BUDGET_BLEED":
        if language == "roman_urdu":
            message = (
                f"💸 *Budget Bleed — {campaign_name}*\n"
                f"*{details['spend']:.0f} PKR* kharch ho chuka hai par koi conversion nahi aaya. "
                f"Yeh campaign clearly underperform kar raha hai.\n"
                f"Turant pause karein aur creative review karayein."
            )
        else:
            message = (
                f"💸 *Budget Bleed — {campaign_name}*\n"
                f"*{details['spend']:.0f} PKR* spent with zero conversions. "
                f"This campaign is bleeding budget.\n"
                f"Pause immediately and review creative."
            )
    else:
        message = f"⚠️ Unknown anomaly: {anomaly_type}"

    return {
        "type": anomaly_type,
        "campaign_id": campaign_id,
        "campaign_name": campaign_name,
        "details": details,
        "message": message,
        "requires_hitl": anomaly_type in ("CPA_SURGE", "ROAS_DROP", "BUDGET_BLEED"),
    }
