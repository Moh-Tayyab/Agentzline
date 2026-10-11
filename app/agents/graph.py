"""
AgentZline Bronze Tier Agent Graph.

LangGraph workflow that orchestrates the daily reporting pipeline:
  1. Fetch Metrics from Meta API
  2. Normalize & Aggregate Metrics (Decimal precision + summary generation)
  3. Run Deterministic Anomaly Detection (CPA surge, ROAS drop, fatigue, bleed)
  4. Format Bilingual Executive Summary (Roman Urdu / English)
  5. Deliver via WhatsApp Business API
  6. Record audit trail
"""

from datetime import datetime, date
from typing import Any
from loguru import logger
from langgraph.graph import StateGraph, END

from app.agents.state import BronzeAgentState
from app.utils.meta_client import MetaGraphClient, MetaAPIError
from app.utils.whatsapp_client import WhatsAppClient
from app.skills.meta_normalizer import normalize_and_aggregate_metrics
from app.skills.meta_ads_analysis import detect_performance_anomalies
from app.skills.bilingual_report import format_daily_summary


# ── Node 1: Fetch Metrics ───────────────────────────────────────────────────

async def fetch_metrics_node(state: BronzeAgentState) -> dict[str, Any]:
    """Pull target date campaign metrics from Meta Graph API for all tenant accounts."""
    ad_account_ids = state.get("ad_account_ids", [])
    target_date_str = state.get("target_date")
    
    if target_date_str:
        target_date = datetime.strptime(target_date_str, "%Y-%m-%d").date()
    else:
        target_date = date.today()

    logger.info(f"📊 Fetching Meta metrics for {len(ad_account_ids)} accounts, date={target_date}")

    meta_token = state.get("meta_access_token")
    client = MetaGraphClient(access_token=meta_token)
    raw_metrics: list[dict[str, Any]] = []
    errors: list[str] = list(state.get("errors", []))

    try:
        for acc_id in ad_account_ids:
            try:
                insights = await client.get_account_insights(
                    ad_account_id=acc_id,
                    date_start=target_date,
                    date_end=target_date,
                )
                raw_metrics.extend(insights)
            except MetaAPIError as err:
                msg = f"Failed to fetch insights for {acc_id}: {err}"
                logger.error(msg)
                errors.append(msg)
    finally:
        await client.close()

    return {
        "raw_metrics": raw_metrics,
        "errors": errors,
    }


# ── Node 2: Normalize & Aggregate Metrics ───────────────────────────────────

async def aggregate_metrics_node(state: BronzeAgentState) -> dict[str, Any]:
    """Normalize raw Meta string payloads with Decimal math and compute daily summary."""
    raw_metrics = state.get("raw_metrics", [])
    target_date = state.get("target_date", "Yesterday")

    normalized, daily_summary = normalize_and_aggregate_metrics(
        raw_insights=raw_metrics,
        account_name=f"Tenant {state.get('tenant_id', '')[:8]}",
        target_date=target_date,
    )

    return {
        "normalized_metrics": normalized,
        "daily_summary": daily_summary,
    }


# ── Node 3: Detect Anomalies ────────────────────────────────────────────────

async def detect_anomalies_node(state: BronzeAgentState) -> dict[str, Any]:
    """
    Run deterministic anomaly detection on normalized metrics.
    Detects CPA surges, ROAS drops, ad fatigue, and budget bleed.
    """
    metrics_to_analyze = state.get("normalized_metrics", state.get("raw_metrics", []))
    language = state.get("language", "roman_urdu")

    logger.info(f"🔍 Running anomaly detection on {len(metrics_to_analyze)} campaigns")

    anomalies = detect_performance_anomalies(
        metrics=metrics_to_analyze,
        language=language,
    )

    return {"anomalies": anomalies}


# ── Node 4: Format Bilingual Report ─────────────────────────────────────────

async def format_report_node(state: BronzeAgentState) -> dict[str, Any]:
    """Format daily executive summary into WhatsApp-ready Roman Urdu / English text."""
    daily_summary = state.get("daily_summary", {})
    anomalies = state.get("anomalies", [])
    language = state.get("language", "roman_urdu")

    logger.info(f"📝 Formatting report (lang={language})")

    report_text = format_daily_summary(
        summary=daily_summary,
        anomalies=anomalies,
        language=language,
    )

    return {"report_text": report_text}


# ── Node 5: Send via WhatsApp ───────────────────────────────────────────────

async def send_whatsapp_node(state: BronzeAgentState) -> dict[str, Any]:
    """Deliver formatted report to tenant WhatsApp recipient."""
    report_text = state.get("report_text", "")
    recipient = state.get("recipient_whatsapp", "")
    audit_actions = list(state.get("audit_actions", []))
    errors = list(state.get("errors", []))

    if not recipient:
        logger.warning("⚠️ No recipient_whatsapp configured in state — skipping delivery")
        audit_actions.append({
            "action_type": "REPORT_SKIPPED",
            "reason": "Missing recipient_whatsapp",
        })
        return {"audit_actions": audit_actions}

    wa_token = state.get("whatsapp_access_token")
    client = WhatsAppClient(access_token=wa_token)
    try:
        logger.info(f"📤 Delivering WhatsApp report to {recipient} ({len(report_text)} chars)")
        await client.send_text_message(recipient_number=recipient, message_text=report_text)
        audit_actions.append({
            "action_type": "REPORT_SENT",
            "recipient": recipient,
            "characters": len(report_text),
        })
    except Exception as exc:
        err_msg = f"Failed to send WhatsApp message to {recipient}: {exc}"
        logger.error(err_msg)
        errors.append(err_msg)
        audit_actions.append({
            "action_type": "REPORT_FAILED",
            "error": str(exc),
        })
    finally:
        await client.close()

    return {
        "audit_actions": audit_actions,
        "errors": errors,
    }


# ── Graph Construction ──────────────────────────────────────────────────────

def build_bronze_graph():
    """
    Construct the Bronze Tier LangGraph workflow.

    Pipeline:
      fetch_metrics -> aggregate_metrics -> detect_anomalies -> format_report -> send_whatsapp -> END
    """
    graph = StateGraph(BronzeAgentState)

    graph.add_node("fetch_metrics", fetch_metrics_node)
    graph.add_node("aggregate_metrics", aggregate_metrics_node)
    graph.add_node("detect_anomalies", detect_anomalies_node)
    graph.add_node("format_report", format_report_node)
    graph.add_node("send_whatsapp", send_whatsapp_node)

    graph.set_entry_point("fetch_metrics")
    graph.add_edge("fetch_metrics", "aggregate_metrics")
    graph.add_edge("aggregate_metrics", "detect_anomalies")
    graph.add_edge("detect_anomalies", "format_report")
    graph.add_edge("format_report", "send_whatsapp")
    graph.add_edge("send_whatsapp", END)

    return graph.compile()
