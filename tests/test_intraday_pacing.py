"""
Tests for Phase-2 Intraday Pacing Engine.

Covers: deterministic detector rules, bilingual formatting,
suppression (24h dedup), and end-to-end pacing job with mocked APIs.
"""

import uuid
from datetime import date, datetime, timezone, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest

from app.core.database import async_session_maker
from app.models.tenant import Tenant
from app.models.ad_account import AdAccount
from app.models.audit_log import AuditLog
from app.skills.intraday_pacing import (
    detect_intraday_pacing_alerts,
    format_pacing_alert,
    parse_meta_budget_to_pkr,
)
from app.agents.scheduler import run_intraday_pacing_job


def _norm(cid: str, spend: float, conv: int, ctr: float) -> dict:
    return {
        "id": cid, "name": f"Campaign {cid}",
        "spend": Decimal(str(spend)), "impressions": 10000,
        "clicks": 50, "conversions": conv,
        "purchase_value": Decimal("0.00"),
        "roas": 0.0, "frequency": 1.5, "ctr": ctr,
    }


class TestPacingDetector:
    def test_triggers_on_bleed(self):
        alerts = detect_intraday_pacing_alerts(
            metrics=[_norm("c1", 6000.0, 0, 0.4)],
            budgets_by_campaign={"c1": Decimal("10000")},
        )
        assert len(alerts) == 1
        assert alerts[0]["type"] == "INTRADAY_PACING_BLEED"
        assert alerts[0]["campaign_id"] == "c1"

    def test_no_trigger_with_conversions(self):
        alerts = detect_intraday_pacing_alerts(
            metrics=[_norm("c1", 9000.0, 3, 0.2)],
            budgets_by_campaign={"c1": Decimal("10000")},
        )
        assert alerts == []

    def test_no_trigger_when_ctr_healthy(self):
        alerts = detect_intraday_pacing_alerts(
            metrics=[_norm("c1", 9000.0, 0, 1.2)],
            budgets_by_campaign={"c1": Decimal("10000")},
        )
        assert alerts == []

    def test_no_trigger_below_spend_ratio(self):
        alerts = detect_intraday_pacing_alerts(
            metrics=[_norm("c1", 3000.0, 0, 0.2)],
            budgets_by_campaign={"c1": Decimal("10000")},
        )
        assert alerts == []

    def test_skips_unknown_budget(self):
        alerts = detect_intraday_pacing_alerts(
            metrics=[_norm("c1", 9000.0, 0, 0.1)],
            budgets_by_campaign={},
        )
        assert alerts == []

    def test_parse_meta_budget_cents(self):
        assert parse_meta_budget_to_pkr("500000") == Decimal("5000.00")
        assert parse_meta_budget_to_pkr(None) is None
        assert parse_meta_budget_to_pkr("junk") is None


class TestPacingFormatting:
    def _alert(self) -> dict:
        return {
            "type": "INTRADAY_PACING_BLEED",
            "campaign_id": "c1", "campaign_name": "Lawn Sale",
            "details": {"spend": 6000.0, "daily_budget": 10000.0,
                        "spend_fraction": 0.6, "conversions": 0, "ctr": 0.4},
        }

    def test_roman_urdu(self):
        msg = format_pacing_alert(self._alert(), language="roman_urdu")
        assert "Lawn Sale" in msg and "conversion nahi" in msg

    def test_english(self):
        msg = format_pacing_alert(self._alert(), language="english")
        assert "zero conversions" in msg


@pytest.fixture
async def pacing_tenant():
    t_id = uuid.uuid4()
    async with async_session_maker() as session:
        tenant = Tenant(
            id=t_id, company_name="Pacing Co", country_code="PK",
            currency="PKR", preferred_language="roman_urdu",
            whatsapp_notification_number="+923004445556",
        )
        session.add(tenant)
        await session.flush()
        acc = AdAccount(
            tenant_id=t_id, platform="META",
            external_account_id="act_pacing_001",
            account_name="Pacing Account",
            max_budget_ceiling_pkr=100000.0, is_active=True,
        )
        session.add(acc)
        await session.commit()
    return tenant


def _raw_insight_bleed() -> dict:
    return {
        "campaign_id": "camp_bleed_1",
        "campaign_name": "Bleed Campaign",
        "spend": "6000.00", "impressions": "20000",
        "clicks": "60", "ctr": "0.30", "frequency": "1.2",
        "actions": [], "action_values": [],
    }


@pytest.mark.asyncio
async def test_pacing_job_sends_alert(pacing_tenant):
    """End-to-end: bleed conditions → WhatsApp urgent alert + audit row."""
    with patch("app.agents.scheduler.MetaGraphClient") as mock_meta, \
         patch("app.agents.scheduler.WhatsAppClient") as mock_wa:
        meta_inst = AsyncMock()
        meta_inst.get_account_insights.return_value = [_raw_insight_bleed()]
        meta_inst.get_campaign_details.return_value = {"daily_budget": "1000000"}  # 10000 PKR
        mock_meta.return_value = meta_inst
        wa_inst = AsyncMock()
        mock_wa.return_value = wa_inst

        totals = await run_intraday_pacing_job()

    assert totals["alerts"] >= 1
    wa_inst.send_text_message.assert_awaited()
    body = wa_inst.send_text_message.await_args.kwargs["message_text"]
    assert "Bleed Campaign" in body

    async with async_session_maker() as session:
        from sqlalchemy import select
        r = await session.execute(select(AuditLog).where(
            AuditLog.action_type == "INTRADAY_PACING_ALERT",
        ))
        rows = r.scalars().all()
        assert any(
            (row.action_details or {}).get("campaign_id") == "camp_bleed_1" for row in rows
        )


@pytest.mark.asyncio
async def test_pacing_job_suppresses_duplicate_within_24h(pacing_tenant):
    """Second sweep within 24h must not re-send for the same campaign."""
    async with async_session_maker() as session:
        session.add(AuditLog(
            tenant_id=pacing_tenant.id,
            action_type="INTRADAY_PACING_ALERT",
            action_details={"campaign_id": "camp_bleed_1", "spend": 6000.0},
            executed_by="AGENTZLINE_PACING",
            created_at=datetime.now(timezone.utc),
        ))
        await session.commit()

    with patch("app.agents.scheduler.MetaGraphClient") as mock_meta, \
         patch("app.agents.scheduler.WhatsAppClient") as mock_wa:
        meta_inst = AsyncMock()
        meta_inst.get_account_insights.return_value = [_raw_insight_bleed()]
        meta_inst.get_campaign_details.return_value = {"daily_budget": "1000000"}
        mock_meta.return_value = meta_inst
        wa_inst = AsyncMock()
        mock_wa.return_value = wa_inst

        totals = await run_intraday_pacing_job()

    assert totals["alerts"] == 0
    assert totals["skipped_suppressed"] >= 1
    wa_inst.send_text_message.assert_not_awaited()
