"""
Meta Graph API Client.

Async HTTP client for read-only Meta Marketing API calls.
Bronze Tier: Only fetches campaign insights and account structure.
"""

import asyncio
from datetime import date
import json
import random
from typing import Any

import httpx
from loguru import logger

from app.core.config import get_settings


class MetaAPIError(Exception):
    """Base exception for Meta API errors."""
    def __init__(self, message: str, code: int | None = None, is_transient: bool = False):
        super().__init__(message)
        self.code = code
        self.is_transient = is_transient


class MetaGraphClient:
    """
    Async client for Meta Marketing Graph API.

    All methods are strictly read-only — no mutations in Bronze Tier.
    Handles pagination, rate limiting backoff with jitter, and token error detection.
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

    async def close(self) -> None:
        """Close the HTTP client session to prevent connection leaks."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def _execute_with_retry(self, method: str, url: str, params: dict[str, Any]) -> dict[str, Any]:
        """
        Execute HTTP request with exponential backoff and jitter for transient errors.
        Fails fast without retry on Code 190 (Invalid/Expired Token).
        """
        client = await self._get_client()
        max_retries = 3
        backoff_base = 2.0

        for attempt in range(max_retries):
            try:
                response = await client.request(method, url, params=params)
                data = response.json()

                if "error" in data:
                    err = data["error"]
                    err_code = err.get("code")
                    err_msg = err.get("message", "Unknown Meta error")

                    # Code 190: Invalid / expired access token -> Fail immediately
                    if err_code == 190:
                        logger.error(f"❌ Meta API Authentication failed (Code 190): {err_msg}")
                        raise MetaAPIError(f"Meta token expired or invalid: {err_msg}", code=190, is_transient=False)

                    # Transient codes: 429, 4 (Too many calls), 17 (User request limit), 32 (Page request limit)
                    if err_code in (4, 17, 32) or response.status_code == 429:
                        if attempt < max_retries - 1:
                            jitter = random.uniform(0.5, 1.5)
                            sleep_time = (backoff_base ** attempt) + jitter
                            logger.warning(
                                f"⚠️ Meta rate limit hit (code {err_code}). Retrying in {sleep_time:.2f}s (attempt {attempt + 1}/{max_retries})"
                            )
                            await asyncio.sleep(sleep_time)
                            continue
                        raise MetaAPIError(f"Meta rate limit exceeded: {err_msg}", code=err_code, is_transient=True)

                    raise MetaAPIError(f"Meta API error [{err_code}]: {err_msg}", code=err_code, is_transient=False)

                response.raise_for_status()
                return data

            except httpx.RequestError as exc:
                if attempt < max_retries - 1:
                    sleep_time = (backoff_base ** attempt) + random.uniform(0.5, 1.0)
                    logger.warning(f"⚠️ Network error connecting to Meta: {exc}. Retrying in {sleep_time:.2f}s")
                    await asyncio.sleep(sleep_time)
                    continue
                raise MetaAPIError(f"Network error communicating with Meta API: {exc}", is_transient=True)

        raise MetaAPIError("Exceeded max retries for Meta API call", is_transient=True)

    async def get_account_insights(
        self,
        ad_account_id: str,
        date_start: date,
        date_end: date,
        fields: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Fetch campaign-level insights for an ad account with full pagination.

        Args:
            ad_account_id: Meta ad account ID (e.g., act_123456789).
            date_start: Start date for reporting window.
            date_end: End date for reporting window.
            fields: List of metric fields to request.

        Returns:
            List of all campaign insight dictionaries across pages.
        """
        default_fields = [
            "campaign_name",
            "campaign_id",
            "spend",
            "impressions",
            "clicks",
            "actions",
            "action_values",
            "cost_per_action_type",
            "ctr",
            "cpc",
            "frequency",
        ]

        params = {
            "access_token": self.access_token,
            "fields": ",".join(fields or default_fields),
            "time_range": json.dumps({"since": str(date_start), "until": str(date_end)}),
            "level": "campaign",
            "limit": "100",
            "use_unified_attribution_setting": "true",
        }

        endpoint = f"/{ad_account_id}/insights"
        logger.info(f"📊 Fetching insights for {ad_account_id} ({date_start} to {date_end})")

        all_records: list[dict[str, Any]] = []
        data = await self._execute_with_retry("GET", endpoint, params)
        all_records.extend(data.get("data", []))

        # Handle pagination cursor
        client = await self._get_client()
        paging = data.get("paging", {})
        next_url = paging.get("next")

        while next_url:
            try:
                resp = await client.get(next_url)
                resp.raise_for_status()
                page_data = resp.json()
                page_records = page_data.get("data", [])
                if not page_records:
                    break
                all_records.extend(page_records)
                next_url = page_data.get("paging", {}).get("next")
            except Exception as exc:
                logger.warning(f"Error fetching next insights page: {exc}")
                break

        return all_records

    async def get_campaign_details(self, campaign_id: str) -> dict[str, Any]:
        """Fetch details for a specific campaign."""
        params = {
            "access_token": self.access_token,
            "fields": "name,status,objective,daily_budget,lifetime_budget",
        }
        return await self._execute_with_retry("GET", f"/{campaign_id}", params)

    async def get_ad_account_list(self, business_id: str | None = None) -> list[dict[str, Any]]:
        """List all ad accounts accessible by the business user."""
        settings = get_settings()
        bid = business_id or settings.META_BUSINESS_ID

        params = {
            "access_token": self.access_token,
            "fields": "id,name,account_status,currency",
        }
        data = await self._execute_with_retry("GET", f"/{bid}/owned_ad_accounts", params)
        return data.get("data", [])
