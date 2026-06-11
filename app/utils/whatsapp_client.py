"""
WhatsApp Business API Client.

Async HTTP client for sending messages via WhatsApp Business API.
Handles text messages and interactive button messages for HITL flow.
"""

import httpx
from loguru import logger

from app.core.config import get_settings


class WhatsAppClient:
    """
    Async client for WhatsApp Cloud API.

    Handles outbound message delivery:
    - Daily executive summary (text)
    - HITL interactive buttons (approve/reject)
    """

    BASE_URL = "https://graph.facebook.com"

    def __init__(self):
        settings = get_settings()
        self.phone_number_id = settings.WHATSAPP_PHONE_NUMBER_ID
        self.access_token = settings.WHATSAPP_ACCESS_TOKEN
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

    async def send_text_message(
        self,
        recipient_number: str,
        message_text: str,
    ) -> dict:
        """
        Send a plain text WhatsApp message.

        Args:
            recipient_number: Recipient's WhatsApp number (with country code).
            message_text: The message body (supports WhatsApp formatting).

        Returns:
            WhatsApp API response dictionary.
        """
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": recipient_number,
            "type": "text",
            "text": {"body": message_text},
        }

        return await self._send(payload)

    async def send_interactive_buttons(
        self,
        recipient_number: str,
        header_text: str,
        body_text: str,
        button_approve_id: str,
        button_reject_id: str,
        button_approve_label: str = "Approve",
        button_reject_label: str = "Reject",
    ) -> dict:
        """
        Send an interactive message with Approve/Reject buttons.

        This is the HITL (Human-In-The-Loop) delivery mechanism.
        The button IDs carry signed action tokens for verification.

        Args:
            recipient_number: Recipient's WhatsApp number.
            header_text: Bold header text.
            body_text: Detailed message body.
            button_approve_id: Signed token for the approve action.
            button_reject_id: Signed token for the reject action.
            button_approve_label: Label for the approve button.
            button_reject_label: Label for the reject button.

        Returns:
            WhatsApp API response dictionary.
        """
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": recipient_number,
            "type": "interactive",
            "interactive": {
                "type": "button",
                "header": {"type": "text", "text": header_text},
                "body": {"text": body_text},
                "action": {
                    "buttons": [
                        {
                            "type": "reply",
                            "reply": {"id": button_approve_id, "title": button_approve_label},
                        },
                        {
                            "type": "reply",
                            "reply": {"id": button_reject_id, "title": button_reject_label},
                        },
                    ]
                },
            },
        }

        return await self._send(payload)

    async def _send(self, payload: dict) -> dict:
        """Execute the WhatsApp API send request."""
        client = await self._get_client()

        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }

        endpoint = f"/{self.phone_number_id}/messages"

        logger.info(f"📤 Sending WhatsApp message to {payload.get('to', 'unknown')}")

        response = await client.post(endpoint, json=payload, headers=headers)
        response.raise_for_status()

        return response.json()
