"""
Unit and integration tests for AgentZline Bronze Tier LangGraph workflow.
"""

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.agents.graph import (
    aggregate_metrics_node,
    build_bronze_graph,
    detect_anomalies_node,
    fetch_metrics_node,
    format_report_node,
    send_whatsapp_node,
)
from app.agents.scheduler import run_daily_report_job
from app.agents.state import BronzeAgentState
from app.core.database import async_session_maker
from app.models.ad_account import AdAccount
from app.models.audit_log import AuditLog
from app.models.tenant import Tenant


@pytest.fixture
def sample_raw_insights():
    return [
        {
            "campaign_id": "camp_surge",
            "campaign_name": "Summer Collection - Conversions",
            "spend": "15000.00",
            "impressions": "35000",
            "clicks": "1200",
            "actions": [{"action_type": "purchase", "value": "10"}],  # CPA = 1500
            "action_values": [{"action_type": "omni_purchase", "value": "20000.00"}],  # ROAS = 1.33
        },
        {
            "campaign_id": "camp_healthy",
            "campaign_name": "Eid Festival - Retargeting",
            "spend": "8000.00",
            "impressions": "15000",
            "clicks": "900",
            "actions": [{"action_type": "purchase", "value": "20"}],  # CPA = 400
            "action_values": [{"action_type": "omni_purchase", "value": "40000.00"}],  # ROAS = 5.0
        },
    ]


@pytest.mark.asyncio
async def test_fetch_metrics_node(sample_raw_insights):
    """Test fetch_metrics_node pulls insights via MetaGraphClient."""
    state: BronzeAgentState = {
        "tenant_id": "tenant-123",
        "ad_account_ids": ["act_111", "act_222"],
        "target_date": "2026-10-10",
        "raw_metrics": [],
        "normalized_metrics": [],
        "daily_summary": {},
        "anomalies": [],
        "report_text": "",
        "recipient_whatsapp": "+923001234567",
        "language": "roman_urdu",
        "audit_actions": [],
        "errors": [],
    }

    with patch("app.agents.graph.MetaGraphClient") as mock_client_cls:
        mock_instance = AsyncMock()
        mock_instance.get_account_insights.return_value = sample_raw_insights
        mock_client_cls.return_value = mock_instance

        result = await fetch_metrics_node(state)

        assert len(result["raw_metrics"]) == 4  # 2 accounts * 2 insights each
        assert result["errors"] == []
        mock_instance.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_aggregate_metrics_node(sample_raw_insights):
    """Test metrics normalization and aggregation node."""
    state: BronzeAgentState = {
        "tenant_id": "tenant-abc",
        "ad_account_ids": ["act_111"],
        "target_date": "2026-10-10",
        "raw_metrics": sample_raw_insights,
        "normalized_metrics": [],
        "daily_summary": {},
        "anomalies": [],
        "report_text": "",
        "recipient_whatsapp": "+923001234567",
        "language": "roman_urdu",
        "audit_actions": [],
        "errors": [],
    }

    result = await aggregate_metrics_node(state)
    assert "normalized_metrics" in result
    assert "daily_summary" in result
    assert len(result["normalized_metrics"]) == 2
    assert result["daily_summary"]["total_spend"] == Decimal("23000.00")
    assert result["daily_summary"]["total_conversions"] == 30


@pytest.mark.asyncio
async def test_detect_anomalies_node(sample_raw_insights):
    """Test anomaly detection identifies CPA surge and ROAS drops."""
    from app.skills.meta_normalizer import normalize_and_aggregate_metrics
    normalized, summary = normalize_and_aggregate_metrics(sample_raw_insights, "Test Tenant")

    state: BronzeAgentState = {
        "tenant_id": "tenant-abc",
        "ad_account_ids": ["act_111"],
        "target_date": "2026-10-10",
        "raw_metrics": sample_raw_insights,
        "normalized_metrics": normalized,
        "daily_summary": summary,
        "anomalies": [],
        "report_text": "",
        "recipient_whatsapp": "+923001234567",
        "language": "roman_urdu",
        "audit_actions": [],
        "errors": [],
    }

    result = await detect_anomalies_node(state)
    assert len(result["anomalies"]) >= 1
    # Check that anomaly description or type exists
    assert any(a["campaign_id"] == "camp_surge" for a in result["anomalies"])


@pytest.mark.asyncio
async def test_format_report_node():
    """Test bilingual report formatting for Roman Urdu and English."""
    summary = {
        "account_name": "Al-Karam Studio",
        "date": "2026-10-10",
        "total_spend": Decimal("23000.00"),
        "total_revenue": Decimal("60000.00"),
        "total_conversions": 30,
        "overall_roas": Decimal("2.61"),
        "overall_cpa": Decimal("766.67"),
    }
    anomalies = [
        {
            "campaign_id": "camp_surge",
            "campaign_name": "Summer Sale",
            "type": "CPA_SURGE",
            "message": "⚠️ CPA Alert: CPA PKR 1500 target se zyada hai.",
        }
    ]

    # Roman Urdu
    state_urdu: BronzeAgentState = {
        "tenant_id": "tenant-1",
        "ad_account_ids": [],
        "target_date": "2026-10-10",
        "raw_metrics": [],
        "normalized_metrics": [],
        "daily_summary": summary,
        "anomalies": anomalies,
        "report_text": "",
        "recipient_whatsapp": "+923001234567",
        "language": "roman_urdu",
        "audit_actions": [],
        "errors": [],
    }
    result_urdu = await format_report_node(state_urdu)
    assert "AgentZline Daily Report" in result_urdu["report_text"]
    assert "Al-Karam Studio" in result_urdu["report_text"]
    assert "Total Spend" in result_urdu["report_text"]
    assert "Alerts" in result_urdu["report_text"]
    assert "CPA Alert" in result_urdu["report_text"]

    # English
    state_en: BronzeAgentState = {**state_urdu, "language": "english"}
    result_en = await format_report_node(state_en)
    assert "AgentZline Daily Report" in result_en["report_text"]
    assert "Total Spend" in result_en["report_text"]
    assert "Alerts" in result_en["report_text"]


@pytest.mark.asyncio
async def test_send_whatsapp_node():
    """Test WhatsApp dispatch node."""
    state: BronzeAgentState = {
        "tenant_id": "tenant-1",
        "ad_account_ids": [],
        "target_date": "2026-10-10",
        "raw_metrics": [],
        "normalized_metrics": [],
        "daily_summary": {},
        "anomalies": [],
        "report_text": "Test Report Content",
        "recipient_whatsapp": "+923001234567",
        "language": "roman_urdu",
        "audit_actions": [],
        "errors": [],
    }

    with patch("app.agents.graph.WhatsAppClient") as mock_wa_cls:
        mock_instance = AsyncMock()
        mock_wa_cls.return_value = mock_instance

        res = await send_whatsapp_node(state)
        mock_instance.send_text_message.assert_awaited_once_with(
            recipient_number="+923001234567",
            message_text="Test Report Content",
        )
        assert len(res["audit_actions"]) == 1
        assert res["audit_actions"][0]["action_type"] == "REPORT_SENT"


@pytest.mark.asyncio
async def test_bronze_graph_pipeline_e2e(sample_raw_insights):
    """End-to-end execution of the LangGraph Bronze workflow."""
    graph = build_bronze_graph()

    initial_state: BronzeAgentState = {
        "tenant_id": "test-tenant-uuid",
        "ad_account_ids": ["act_test_100"],
        "target_date": "2026-10-10",
        "raw_metrics": [],
        "normalized_metrics": [],
        "daily_summary": {},
        "anomalies": [],
        "report_text": "",
        "recipient_whatsapp": "+923009999999",
        "language": "roman_urdu",
        "audit_actions": [],
        "errors": [],
    }

    with patch("app.agents.graph.MetaGraphClient") as mock_meta_cls, \
         patch("app.agents.graph.WhatsAppClient") as mock_wa_cls:

        mock_meta = AsyncMock()
        mock_meta.get_account_insights.return_value = sample_raw_insights
        mock_meta_cls.return_value = mock_meta

        mock_wa = AsyncMock()
        mock_wa_cls.return_value = mock_wa

        final_state = await graph.ainvoke(initial_state)

        # Assert full workflow completion
        assert len(final_state["raw_metrics"]) == 2
        assert len(final_state["normalized_metrics"]) == 2
        assert final_state["daily_summary"]["total_spend"] == Decimal("23000.00")
        assert len(final_state["report_text"]) > 0
        assert any(action["action_type"] == "REPORT_SENT" for action in final_state["audit_actions"])
        mock_wa.send_text_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_scheduler_run_daily_report_job(sample_raw_insights):
    """Test scheduler job queries active tenants and runs graph with DB persistence."""
    tenant_id = uuid.uuid4()
    ad_account_id = uuid.uuid4()

    async with async_session_maker() as session:
        # Create tenant
        tenant = Tenant(
            id=tenant_id,
            company_name="Scheduler Test Brand",
            country_code="PK",
            currency="PKR",
            preferred_language="roman_urdu",
            whatsapp_notification_number="+923001112233",
        )
        session.add(tenant)

        # Create ad account
        ad_account = AdAccount(
            id=ad_account_id,
            tenant_id=tenant_id,
            platform="META",
            external_account_id="act_sched_1",
            account_name="Sched Main Adset",
            is_active=True,
            max_budget_ceiling_pkr=100000.0,
        )
        session.add(ad_account)
        await session.commit()

    with patch("app.agents.graph.MetaGraphClient") as mock_meta_cls, \
         patch("app.agents.graph.WhatsAppClient") as mock_wa_cls:

        mock_meta = AsyncMock()
        mock_meta.get_account_insights.return_value = sample_raw_insights
        mock_meta_cls.return_value = mock_meta

        mock_wa = AsyncMock()
        mock_wa_cls.return_value = mock_wa

        await run_daily_report_job()

        mock_wa.send_text_message.assert_awaited_once()

    # Verify audit log was recorded in the database
    async with async_session_maker() as session:
        result = await session.execute(
            select(AuditLog).where(AuditLog.tenant_id == tenant_id)
        )
        logs = result.scalars().all()
        assert len(logs) >= 1
        assert logs[0].action_type == "REPORT_SENT"
        assert logs[0].executed_by == "AGENTZLINE_SCHEDULER"


@pytest.mark.asyncio
async def test_scheduler_resolves_tenant_vault_credentials(sample_raw_insights):
    """Test scheduler decrypts tenant-specific access tokens from vault."""
    from app.core.security import encrypt_token
    from app.models.credential import PlatformCredential

    tenant_id = uuid.uuid4()
    ad_account_id = uuid.uuid4()
    secret_vault_token = "vault_meta_secret_token_abc123"

    async with async_session_maker() as session:
        tenant = Tenant(
            id=tenant_id,
            company_name="Vault Encrypted Brand",
            country_code="PK",
            currency="PKR",
            preferred_language="roman_urdu",
            whatsapp_notification_number="+923005557788",
        )
        session.add(tenant)

        ad_account = AdAccount(
            id=ad_account_id,
            tenant_id=tenant_id,
            platform="META",
            external_account_id="act_vault_99",
            account_name="Vault Adset",
            is_active=True,
            max_budget_ceiling_pkr=50000.0,
        )
        session.add(ad_account)

        cred = PlatformCredential(
            tenant_id=tenant_id,
            platform_name="META",
            encrypted_access_token=encrypt_token(secret_vault_token),
            token_status="ACTIVE",
        )
        session.add(cred)
        await session.commit()

    with patch("app.agents.graph.MetaGraphClient") as mock_meta_cls, \
         patch("app.agents.graph.WhatsAppClient") as mock_wa_cls:

        mock_meta = AsyncMock()
        mock_meta.get_account_insights.return_value = sample_raw_insights
        mock_meta_cls.return_value = mock_meta

        mock_wa = AsyncMock()
        mock_wa_cls.return_value = mock_wa

        await run_daily_report_job()

        # Check MetaGraphClient was called with the decrypted vault token!
        mock_meta_cls.assert_called_with(access_token=secret_vault_token)

