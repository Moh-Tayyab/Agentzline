"""
Unit tests for Meta metrics normalizer skill.
"""

from decimal import Decimal

from app.skills.meta_normalizer import (
    normalize_and_aggregate_metrics,
    normalize_campaign_insight,
)


class TestMetaNormalizer:
    """Test suite for raw Meta payload normalization and aggregation."""

    def test_normalizes_string_metrics_with_decimal_precision(self):
        raw = {
            "campaign_id": "123456",
            "campaign_name": "Summer Lawn Sale",
            "spend": "1520.40",
            "impressions": "25000",
            "clicks": "450",
            "frequency": "2.1",
            "ctr": "1.8",
            "actions": [
                {"action_type": "link_click", "value": "450"},
                {"action_type": "omni_purchase", "value": "6"},
            ],
            "action_values": [
                {"action_type": "omni_purchase", "value": "18244.80"},
            ],
        }

        normalized = normalize_campaign_insight(raw)

        assert normalized["id"] == "123456"
        assert normalized["name"] == "Summer Lawn Sale"
        assert normalized["spend"] == Decimal("1520.40")
        assert normalized["impressions"] == 25000
        assert normalized["clicks"] == 450
        assert normalized["conversions"] == 6
        assert normalized["purchase_value"] == Decimal("18244.80")
        # ROAS = 18244.80 / 1520.40 = 12.0
        assert normalized["roas"] == 12.0
        assert normalized["raw_payload"] == raw

    def test_aggregates_multiple_campaigns_correctly(self):
        raw_insights = [
            {
                "campaign_id": "c1",
                "campaign_name": "Camp 1",
                "spend": "5000.00",
                "impressions": "50000",
                "clicks": "1000",
                "actions": [{"action_type": "purchase", "value": "10"}],
                "action_values": [{"action_type": "purchase", "value": "15000.00"}],
            },
            {
                "campaign_id": "c2",
                "campaign_name": "Camp 2",
                "spend": "5000.00",
                "impressions": "50000",
                "clicks": "1000",
                "actions": [{"action_type": "offsite_conversion.fb_pixel_purchase", "value": "5"}],
                "action_values": [{"action_type": "offsite_conversion.fb_pixel_purchase", "value": "10000.00"}],
            },
        ]

        normalized, summary = normalize_and_aggregate_metrics(
            raw_insights,
            account_name="Fashion Brand",
            target_date="2026-10-09",
        )

        assert len(normalized) == 2
        assert summary["total_spend"] == 10000.00
        assert summary["total_impressions"] == 100000
        assert summary["total_clicks"] == 2000
        assert summary["total_conversions"] == 15
        assert summary["total_revenue"] == 25000.00
        # Blended ROAS = 25000 / 10000 = 2.50
        assert summary["aggregate_roas"] == 2.50
        # Aggregate CTR = (2000 / 100000) * 100 = 2.0%
        assert summary["aggregate_ctr"] == 2.0

    def test_handles_zero_spend_without_division_by_zero(self):
        raw = {
            "campaign_id": "c_zero",
            "campaign_name": "New Campaign Zero Spend",
            "spend": "0.00",
            "impressions": "0",
            "clicks": "0",
            "actions": [],
            "action_values": [],
        }

        normalized, summary = normalize_and_aggregate_metrics([raw])

        assert normalized[0]["roas"] == 0.0
        assert summary["total_spend"] == 0.0
        assert summary["aggregate_roas"] == 0.0
        assert summary["aggregate_ctr"] == 0.0
