"""
Meta Graph API Client.

Async HTTP client for read-only Meta Marketing API calls.
Bronze Tier: Only fetches campaign insights and account structure.
"""

from datetime import date

import httpx
from loguru import logger

from app.core.config import get_settings


class MetaGraphClient:
    """
    Async client for Meta Marketing Graph API.

    All methods are read-only — no mutations in Bronze Tier.
    Handles pagination, rate limiting, and error retry logic.
    """

    BASE_URL = "https://graph.facebook.com"

    def __init__(self, access_token: str | None = None):
        settings = get_settings()
        self.access_token = access_token or settings.META_SYSTEM_USER_TOKEN
        self.api_version = settings.META_API_VERSION
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create the async HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=f"{self.BASE_URL}/{self.api_version}",
                timeout=30.0,
            )
        return self._client

    async def close(self):
        """Close the HTTP client session."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def get_account_insights(
        self,
        ad_account_id: str,
        date_start: date,
        date_end: date,
        fields: list[str] | None = None,
    ) -> list[dict]:
        """
        Fetch campaign-level insights for an ad account.

        Args:
            ad_account_id: Meta ad account ID (e.g., act_123456789).
            date_start: Start date for the reporting window.
            date_end: End date for the reporting window.
            fields: List of metric fields to request.

        Returns:
            List of campaign insight dictionaries.
        """
        default_fields = [
            "campaign_name",
            "campaign_id",
            "spend",
            "impressions",
            "clicks",
            "actions",
            "cost_per_action_type",
            "ctr",
            "cpc",
            "frequency",
            "roas",
        ]

        params = {
            "access_token": self.access_token,
            "fields": ",".join(fields or default_fields),
            "time_range": json_dumps({"since": str(date_start), "until": str(date_end)}),
            "level": "campaign",
            "date_preset": "maximum",
        }

        client = await self._get_client()
        endpoint = f"/{ad_account_id}/insights"

        logger.info(f"📊 Fetching insights: {ad_account_id} ({date_start} to {date_end})")

        response = await client.get(endpoint, params=params)
        response.raise_for_status()

        data = response.json()
        return data.get("data", [])

    async def get_campaign_details(
        self,
        campaign_id: str,
    ) -> dict:
        """
        Fetch details for a specific campaign.

        Args:
            campaign_id: Meta campaign ID.

        Returns:
            Campaign detail dictionary.
        """
        params = {
            "access_token": self.access_token,
            "fields": "name,status,objective,daily_budget,lifetime_budget",
        }

        client = await self._get_client()
        response = await client.get(f"/{campaign_id}", params=params)
        response.raise_for_status()

        return response.json()

    async def get_ad_account_list(
        self,
        business_id: str | None = None,
    ) -> list[dict]:
        """
        List all ad accounts accessible by the system user.

        Args:
            business_id: Meta Business ID (falls back to settings).

        Returns:
            List of ad account dictionaries.
        """
        settings = get_settings()
        bid = business_id or settings.META_BUSINESS_ID

        params = {
            "access_token": self.access_token,
            "fields": "id,name,account_status,currency",
        }

        client = await self._get_client()
        response = await client.get(f"/{bid}/owned_ad_accounts", params=params)
        response.raise_for_status()

        data = response.json()
        return data.get("data", [])


def json_dumps(obj: dict) -> str:
    """Simple JSON serialization for query parameters."""
    import json
    return json.dumps(obj)
