"""
Tests for the bilingual report formatter skill.
"""

import pytest

from app.skills.bilingual_report import format_daily_summary


class TestDailySummaryFormat:
    """Tests for the daily summary report formatter."""

    def test_roman_urdu_report_structure(self, sample_daily_summary):
        """Roman Urdu report should contain key sections and metrics."""
        report = format_daily_summary(
            summary=sample_daily_summary,
            anomalies=[],
            language="roman_urdu",
        )

        assert "AgentZline Daily Report" in report
        assert "BrandX Pakistan" in report
        assert "28,500" in report  # Total spend
        assert "450,000" in report  # Impressions
        assert "2,800" in report  # Clicks
        assert "33" in report  # Conversions
        assert "ROAS" in report
        assert "CTR" in report
        assert "AgentZline" in report

    def test_english_report_structure(self, sample_daily_summary):
        """English report should contain key sections and metrics."""
        report = format_daily_summary(
            summary=sample_daily_summary,
            anomalies=[],
            language="english",
        )

        assert "AgentZline Daily Report" in report
        assert "BrandX Pakistan" in report
        assert "28,500" in report
        assert "ROAS" in report

    def test_report_includes_anomalies(self, sample_daily_summary):
        """Report should list anomaly alerts when present."""
        anomalies = [
            {
                "type": "BUDGET_BLEED",
                "campaign_name": "Test Campaign",
                "message": "💸 Budget Bleed detected",
            }
        ]

        report = format_daily_summary(
            summary=sample_daily_summary,
            anomalies=anomalies,
            language="english",
        )

        assert "Alerts" in report
        assert "Budget Bleed detected" in report

    def test_report_without_anomalies(self, sample_daily_summary):
        """Report should not show alerts section when no anomalies exist."""
        report = format_daily_summary(
            summary=sample_daily_summary,
            anomalies=[],
            language="english",
        )

        assert "Alerts" not in report

    def test_empty_summary_still_formats(self):
        """Report should format gracefully even with empty summary."""
        report = format_daily_summary(
            summary={},
            anomalies=[],
            language="english",
        )

        assert "AgentZline Daily Report" in report
        assert len(report) > 0
