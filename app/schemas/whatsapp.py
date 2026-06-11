"""
WhatsApp Schemas.

Pydantic models for WhatsApp webhook payloads and responses.
"""

from pydantic import BaseModel, Field


class WhatsAppWebhookVerification(BaseModel):
    """Query parameters for WhatsApp webhook verification (GET)."""
    hub_mode: str = Field(alias="hub.mode")
    hub_challenge: str = Field(alias="hub.challenge")
    hub_verify_token: str = Field(alias="hub.verify_token")


class WhatsAppButtonPayload(BaseModel):
    """
    Interactive button click payload from WhatsApp.

    Used in the Human-In-The-Loop (HITL) approval flow.
    """
    sender_number: str = Field(..., description="WhatsApp number of the responder")
    context_profile_id: str = Field(..., description="Managed profile context")
    action_token: str = Field(..., description="Signed token identifying the proposed action")
    user_decision: str = Field(..., description="APPROVED or REJECTED")


class WhatsAppTextMessage(BaseModel):
    """Outbound WhatsApp text message payload."""
    recipient_number: str
    message_text: str


class WhatsAppInteractiveButtons(BaseModel):
    """
    Outbound interactive message with approval buttons.

    Sent when the agent proposes an action (e.g., pause campaign).
    The user sees [Approve] [Reject] buttons in WhatsApp.
    """
    recipient_number: str
    header_text: str
    body_text: str
    action_token: str = Field(..., description="Signed token for HITL verification")
    button_approve_label: str = "Approve"
    button_reject_label: str = "Reject"
