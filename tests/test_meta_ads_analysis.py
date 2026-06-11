"""
Tests for the Meta Ads anomaly detection skill.
"""

import pytest

from app.skills.meta_ads_analysis import detect_performance_anomalies


class TestCPASurgeDetection:
    """Tests for CPA surge anomaly detection."""

    def test_detects_cpa_surge(self, sample_campaign_metrics):
        """Should flag campaigns where CPA exceeds target by >25%."""
        anomalies = detect_performance_anomalies(
            metrics=sample_campaign_metrics,
            language="english",
            target_cpa=500.0,
        )

        cpa_surges = [a for a in anomalies if a["type"] == "CPA_SURGE"]
        assert len(cpa_surges) >= 1
        assert any(c["campaign_name"] == "Retargeting - Cart Abandon" for c in cpa_surges)

    def test_no_cpa_surge_when_within_target(self):
        """Should not flag campaigns with CPA within acceptable range."""
        metrics = [
            {
                "id": "camp_ok",
                "name": "Good Campaign",
                "spend": 5000.0,
                "impressions": 100000,
                "clicks": 500,
                "conversions": 15,
                "roas": 2.5,
                "ctr": 0.5,
                "frequency": 1.8,
            }
        ]
        anomalies = detect_performance_anomalies(
            metrics=metrics,
            target_cpa=500.0,
        )

        cpa_surges = [a for a in anomalies if a["type"] == "CPA_SURGE"]
        assert len(cpa_surges) == 0

    def test_no_cpa_surge_below_spend_threshold(self):
        """Should not flag campaigns with spend below 3000 PKR even if CPA is high."""
        metrics = [
            {
                "id": "camp_low",
                "name": "Low Spend Campaign",
                "spend": 2000.0,
                "impressions": 50000,
                "clicks": 100,
                "conversions": 1,
                "roas": 0.5,
                "ctr": 0.2,
                "frequency": 1.0,
            }
        ]
        anomalies = detect_performance_anomalies(
            metrics=metrics,
            target_cpa=100.0,
        )

        cpa_surges = [a for a in anomalies if a["type"] == "CPA_SURGE"]
        assert len(cpa_surges) == 0


class TestBudgetBleedDetection:
    """Tests for budget bleed detection (spend > 3K, zero conversions)."""

    def test_detects_budget_bleed(self, sample_campaign_metrics):
        """Should flag campaigns with spend > 3000 and zero conversions."""
        anomalies = detect_performance_anomalies(
            metrics=sample_campaign_metrics,
            target_roas=1.5,
        )

        bleeds = [a for a in anomalies if a["type"] == "BUDGET_BLEED"]
        assert len(bleeds) >= 1
        assert any(
            c["campaign_name"] == "Eid Collection - Video" for c in bleeds
        )


class TestAdFatigueDetection:
    """Tests for ad fatigue detection (frequency > 4.0)."""

    def test_detects_ad_fatigue(self, sample_campaign_metrics):
        """Should flag campaigns with frequency above 4.0."""
        anomalies = detect_performance_anomalies(
            metrics=sample_campaign_metrics,
            target_roas=1.5,
        )

        fatigue = [a for a in anomalies if a["type"] == "AD_FATIGUE"]
        assert len(fatigue) >= 1
        assert any(
            c["campaign_name"] == "Eid Collection - Video" for c in fatigue
        )


class TestROASDropDetection:
    """Tests for ROAS drop detection (below target)."""

    def test_detects_roas_drop(self, sample_campaign_metrics):
        """Should flag campaigns with ROAS below target and spend > 3000."""
        anomalies = detect_performance_anomalies(
            metrics=sample_campaign_metrics,
            target_roas=1.5,
        )

        roas_drops = [a for a in anomalies if a["type"] == "ROAS_DROP"]
        assert len(roas_drops) >= 1


class TestBilingualMessages:
    """Tests for bilingual (Roman Urdu / English) message generation."""

    def test_roman_urdu_messages(self, sample_campaign_metrics):
        """Anomaly messages should contain Roman Urdu text."""
        anomalies = detect_performance_anomalies(
            metrics=sample_campaign_metrics,
            language="roman_urdu",
            target_cpa=500.0,
            target_roas=1.5,
        )

        assert len(anomalies) > 0
        for anomaly in anomalies:
            assert "message" in anomaly
            # Roman Urdu messages should contain common Urdu words in roman script
            msg = anomaly["message"]
            assert any(
                keyword in msg
                for keyword in ["Aapka", "Aapki", "hai", "hai.", "PKR", "Campaign", "Alert"]
            )

    def test_english_messages(self, sample_campaign_metrics):
        """Anomaly messages should contain English text."""
        anomalies = detect_performance_anomalies(
            metrics=sample_campaign_metrics,
            language="english",
            target_cpa=500.0,
            target_roas=1.5,
        )

        assert len(anomalies) > 0
        for anomaly in anomalies:
            msg = anomaly["message"]
            assert any(
                keyword in msg
                for keyword in [
                    "Alert", "ROAS", "CPA", "Spend", "Recommendation",
                    "Fatigue", "Frequency", "Bleed", "Rescue",
                ]
            )

    def test_empty_metrics_returns_no_anomalies(self):
        """Should return empty list when no metrics provided."""
        anomalies = detect_performance_anomalies(metrics=[])
        assert anomalies == []
