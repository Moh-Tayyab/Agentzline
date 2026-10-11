"""
AgentZline LangGraph Agent State.

Defines the shared state dictionary that flows through the agent graph.
All nodes read from and write to this state during execution.
"""

from typing import Any, TypedDict


class BronzeAgentState(TypedDict, total=False):
    """
    Unified state for the Bronze Tier LangGraph agent pipeline.

    Flows through: fetch_metrics → aggregate_metrics → detect_anomalies → format_report → send_whatsapp
    """

    # Input context
    tenant_id: str
    ad_account_ids: list[str]
    recipient_whatsapp: str
    target_date: str  # ISO date string (YYYY-MM-DD)
    language: str  # roman_urdu | english
    meta_access_token: str | None
    whatsapp_access_token: str | None

    # Accumulated data
    raw_metrics: list[dict[str, Any]]
    normalized_metrics: list[dict[str, Any]]
    anomalies: list[dict[str, Any]]
    daily_summary: dict[str, Any]
    cod_summary: dict[str, Any] | None

    # Report generation
    report_text: str
    hitl_proposals: list[dict[str, Any]]  # Actions needing human approval

    # Execution tracking
    errors: list[str]
    audit_actions: list[dict[str, Any]]
