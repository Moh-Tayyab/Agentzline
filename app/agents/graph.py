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

from datetime import date, datetime
from typing import Any

from langgraph.graph import END, StateGraph
from loguru import logger

from app.agents.state import BronzeAgentState
from app.skills.bilingual_report import format_daily_summary
from app.skills.meta_ads_analysis import detect_performance_anomalies
from app.skills.meta_normalizer import normalize_and_aggregate_metrics
from app.utils.meta_client import MetaAPIError, MetaGraphClient
from app.utils.whatsapp_client import WhatsAppClient

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
                for ins in insights:
                    if isinstance(ins, dict):
                        ins["_ad_account_external_id"] = acc_id
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


# ── Node 2b: Persist Snapshots + Compute COD P&L ────────────────────────────

async def compute_cod_pnl_node(state: BronzeAgentState) -> dict[str, Any]:
    """Persist normalized snapshots (upsert) then compute COD reconciliation.

    Placed right after aggregate_metrics so fetch_and_compute_tenant_pnl sees
    today's Meta spend. Best-effort: never fails the report on DB errors.
    """
    from datetime import timedelta

    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from app.core.database import async_session_maker
    from app.models.tenant import Tenant
    from app.skills.campaign_pnl import fetch_and_compute_tenant_pnl
    from app.skills.meta_normalizer import persist_normalized_snapshots

    tenant_id_str = state.get("tenant_id", "")
    normalized = state.get("normalized_metrics", [])
    target_date_str = state.get("target_date")
    try:
        from datetime import date as _date

        snapshot_date = (
            datetime.strptime(target_date_str, "%Y-%m-%d").date()
            if target_date_str
            else _date.today()
        )
    except Exception:
        from datetime import date as _date

        snapshot_date = _date.today()

    cod_summary = state.get("cod_summary")
    try:
        import uuid as _uuid

        tenant_uuid = _uuid.UUID(tenant_id_str)
    except Exception:
        return {"cod_summary": cod_summary}

    try:
        async with async_session_maker() as session:
            # Resolve account map for snapshot ownership
            t_res = await session.execute(
                select(Tenant)
                .where(Tenant.id == tenant_uuid)
                .options(selectinload(Tenant.ad_accounts))
            )
            tenant = t_res.scalars().first()
            account_map: dict[str, Any] = {}
            if tenant is not None:
                for acc in tenant.ad_accounts:
                    account_map[acc.external_account_id] = acc.id
                    account_map[str(acc.id)] = acc.id
            if normalized and account_map:
                try:
                    await persist_normalized_snapshots(
                        session, tenant_uuid, normalized, snapshot_date, account_map
                    )
                    await session.commit()
                except Exception as persist_err:
                    logger.warning(f"Snapshot persistence skipped for {tenant_id_str}: {persist_err}")
                    await session.rollback()
            # Compute COD P&L after snapshots are persisted
            try:
                pnl = await fetch_and_compute_tenant_pnl(
                    session=session,
                    tenant_id=tenant_uuid,
                    start_date=snapshot_date - timedelta(days=1),
                    end_date=snapshot_date,
                )
                totals = pnl.get("totals", {})
                if totals.get("total_orders", 0) > 0 or totals.get("total_delivered_revenue", 0) > 0:
                    cod_summary = totals
            except Exception as pnl_err:
                logger.warning(f"COD P&L compute skipped for {tenant_id_str}: {pnl_err}")
        return {"cod_summary": cod_summary}
    except Exception as exc:
        logger.warning(f"compute_cod_pnl_node skipped for {tenant_id_str}: {exc}")
        return {"cod_summary": cod_summary}


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

    cod_summary = state.get("cod_summary")

    report_text = format_daily_summary(
        summary=daily_summary,
        anomalies=anomalies,
        language=language,
        cod_summary=cod_summary,
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
      fetch_metrics -> aggregate_metrics -> compute_cod_pnl -> detect_anomalies -> format_report -> send_whatsapp -> END
    """
    graph = StateGraph(BronzeAgentState)

    graph.add_node("fetch_metrics", fetch_metrics_node)
    graph.add_node("aggregate_metrics", aggregate_metrics_node)
    graph.add_node("compute_cod_pnl", compute_cod_pnl_node)
    graph.add_node("detect_anomalies", detect_anomalies_node)
    graph.add_node("format_report", format_report_node)
    graph.add_node("send_whatsapp", send_whatsapp_node)

    graph.set_entry_point("fetch_metrics")
    graph.add_edge("fetch_metrics", "aggregate_metrics")
    graph.add_edge("aggregate_metrics", "compute_cod_pnl")
    graph.add_edge("compute_cod_pnl", "detect_anomalies")
    graph.add_edge("detect_anomalies", "format_report")
    graph.add_edge("format_report", "send_whatsapp")
    graph.add_edge("send_whatsapp", END)

    return graph.compile()
