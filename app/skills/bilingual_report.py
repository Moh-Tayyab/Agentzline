"""
Bilingual Report Formatter Skill.

Generates clean, WhatsApp-friendly executive summaries in
Roman Urdu / English with proper formatting and bullet points.
"""

from typing import Any


def format_daily_summary(
    summary: dict[str, Any],
    anomalies: list[dict[str, Any]],
    language: str = "roman_urdu",
    cod_summary: dict[str, Any] | None = None,
) -> str:
    """
    Format the daily executive summary for WhatsApp delivery.

    Structure:
    1. Header with date and account name
    2. Key metrics summary (spend, ROAS, CTR, CPC)
    3. Real Net Profit & COD Reconciliation (if courier orders present)
    4. Anomaly alerts (if any)
    5. Action recommendations (if any)

    Args:
        summary: Aggregated daily metrics dictionary.
        anomalies: List of detected anomalies.
        language: roman_urdu | english
        cod_summary: Optional aggregated COD financial totals.

    Returns:
        Formatted WhatsApp message string.
    """
    account_name = summary.get("account_name", "Your Account")
    total_spend = summary.get("total_spend", 0)
    total_impressions = summary.get("total_impressions", 0)
    total_clicks = summary.get("total_clicks", 0)
    total_conversions = summary.get("total_conversions", 0)
    aggregate_roas = summary.get("aggregate_roas", 0)
    aggregate_ctr = summary.get("aggregate_ctr", 0)
    date_str = summary.get("date", "Yesterday")

    if language == "roman_urdu":
        report = _format_roman_urdu(
            account_name=account_name,
            date_str=date_str,
            total_spend=total_spend,
            total_impressions=total_impressions,
            total_clicks=total_clicks,
            total_conversions=total_conversions,
            aggregate_roas=aggregate_roas,
            aggregate_ctr=aggregate_ctr,
            anomalies=anomalies,
            cod_summary=cod_summary,
        )
    else:
        report = _format_english(
            account_name=account_name,
            date_str=date_str,
            total_spend=total_spend,
            total_impressions=total_impressions,
            total_clicks=total_clicks,
            total_conversions=total_conversions,
            aggregate_roas=aggregate_roas,
            aggregate_ctr=aggregate_ctr,
            anomalies=anomalies,
            cod_summary=cod_summary,
        )

    return report


def _format_roman_urdu(
    account_name: str,
    date_str: str,
    total_spend: float,
    total_impressions: int,
    total_clicks: int,
    total_conversions: int,
    aggregate_roas: float,
    aggregate_ctr: float,
    anomalies: list[dict[str, Any]],
    cod_summary: dict[str, Any] | None = None,
) -> str:
    """Format report in Roman Urdu."""

    lines = [
        f"📊 *AgentZline Daily Report*",
        f"📋 {account_name} — {date_str}",
        f"",
        f"💰 Total Spend: *{total_spend:,.0f} PKR*",
        f"👁 Impressions: *{total_impressions:,}*",
        f"👆 Clicks: *{total_clicks:,}*",
        f"🎯 Conversions: *{total_conversions}*",
        f"📈 ROAS: *{aggregate_roas:.2f}x*",
        f"📊 CTR: *{aggregate_ctr:.2f}%*",
    ]

    if cod_summary and (cod_summary.get("total_orders", 0) > 0 or cod_summary.get("total_delivered_revenue", 0) > 0):
        deliv_rev = cod_summary.get("total_delivered_revenue", 0)
        deliv_rate = cod_summary.get("blended_delivery_rate_pct", 0)
        rto_count = cod_summary.get("total_returned_orders", 0)
        courier_fees = cod_summary.get("total_courier_fees", 0)
        net_profit = cod_summary.get("total_net_profit", 0)
        real_roas = cod_summary.get("blended_real_roas", 0)

        lines.append("")
        lines.append("📦 *Real Net Profit & COD Reconciliation:*")
        lines.append(f"• Delivered Cash: *{deliv_rev:,.0f} PKR* (Delivery Rate: *{deliv_rate:.1f}%*)")
        lines.append(f"• RTO Returns: *{rto_count} orders* (Return Loss & Fees: *{courier_fees:,.0f} PKR*)")
        lines.append(f"• Pocket Net Margin: *{net_profit:+,.0f} PKR* (Real RoAS: *{real_roas:.2f}x* vs Paper: *{aggregate_roas:.2f}x*)")

    if anomalies:
        lines.append("")
        lines.append(f"🚨 *Alerts ({len(anomalies)})*")
        for anomaly in anomalies:
            lines.append(f"• {anomaly.get('message', 'Unknown alert')}")

    lines.append("")
    lines.append("_AgentZline — Aapka AI Media Buyer_ 🤖")

    return "\n".join(lines)


def _format_english(
    account_name: str,
    date_str: str,
    total_spend: float,
    total_impressions: int,
    total_clicks: int,
    total_conversions: int,
    aggregate_roas: float,
    aggregate_ctr: float,
    anomalies: list[dict[str, Any]],
    cod_summary: dict[str, Any] | None = None,
) -> str:
    """Format report in English."""

    lines = [
        f"📊 *AgentZline Daily Report*",
        f"📋 {account_name} — {date_str}",
        f"",
        f"💰 Total Spend: *{total_spend:,.0f} PKR*",
        f"👁 Impressions: *{total_impressions:,}*",
        f"👆 Clicks: *{total_clicks:,}*",
        f"🎯 Conversions: *{total_conversions}*",
        f"📈 ROAS: *{aggregate_roas:.2f}x*",
        f"📊 CTR: *{aggregate_ctr:.2f}%*",
    ]

    if cod_summary and (cod_summary.get("total_orders", 0) > 0 or cod_summary.get("total_delivered_revenue", 0) > 0):
        deliv_rev = cod_summary.get("total_delivered_revenue", 0)
        deliv_rate = cod_summary.get("blended_delivery_rate_pct", 0)
        rto_count = cod_summary.get("total_returned_orders", 0)
        courier_fees = cod_summary.get("total_courier_fees", 0)
        net_profit = cod_summary.get("total_net_profit", 0)
        real_roas = cod_summary.get("blended_real_roas", 0)

        lines.append("")
        lines.append("📦 *Real Net Profit & COD Reconciliation:*")
        lines.append(f"• Delivered Cash: *{deliv_rev:,.0f} PKR* (Delivery Rate: *{deliv_rate:.1f}%*)")
        lines.append(f"• RTO Returns: *{rto_count} orders* (Courier Fees & Losses: *{courier_fees:,.0f} PKR*)")
        lines.append(f"• Pocket Net Margin: *{net_profit:+,.0f} PKR* (Real RoAS: *{real_roas:.2f}x* vs Paper: *{aggregate_roas:.2f}x*)")

    if anomalies:
        lines.append("")
        lines.append(f"🚨 *Alerts ({len(anomalies)})*")
        for anomaly in anomalies:
            lines.append(f"• {anomaly.get('message', 'Unknown alert')}")

    lines.append("")
    lines.append("_AgentZline — Your AI Media Buyer_ 🤖")

    return "\n".join(lines)
