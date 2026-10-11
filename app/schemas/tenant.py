"""
Tenant Schemas.

Pydantic models for Agency / Tenant onboarding and management.
"""

from datetime import datetime
from pydantic import BaseModel, Field, field_validator
import re


def validate_e164_phone(phone: str | None) -> str | None:
    if phone is None:
        return None
    cleaned = phone.strip()
    if not re.match(r"^\+[1-9]\d{7,14}$", cleaned):
        raise ValueError("Phone number must be in E.164 format (e.g., +923001234567)")
    return cleaned


class TenantCreate(BaseModel):
    """Payload to onboard a new tenant / agency brand."""
    company_name: str = Field(..., min_length=2, max_length=255, description="Agency or brand name")
    country_code: str = Field("PK", max_length=10, description="ISO Country code")
    currency: str = Field("PKR", max_length=10, description="Billing and reporting currency")
    preferred_language: str = Field("roman_urdu", description="Reporting language: roman_urdu | english | urdu")
    whatsapp_notification_number: str = Field(
        ...,
        description="E.164 phone number for daily executive reports and alerts",
    )

    @field_validator("whatsapp_notification_number")
    @classmethod
    def check_phone(cls, v: str) -> str:
        return validate_e164_phone(v) or v

    @field_validator("preferred_language")
    @classmethod
    def check_language(cls, v: str) -> str:
        valid = {"roman_urdu", "english", "urdu"}
        if v.lower() not in valid:
            raise ValueError(f"Language must be one of {valid}")
        return v.lower()


class TenantUpdate(BaseModel):
    """Payload to update an existing tenant's profile or preferences."""
    company_name: str | None = Field(None, min_length=2, max_length=255)
    preferred_language: str | None = None
    whatsapp_notification_number: str | None = None
    currency: str | None = Field(None, max_length=10)

    @field_validator("whatsapp_notification_number")
    @classmethod
    def check_phone(cls, v: str | None) -> str | None:
        return validate_e164_phone(v)

    @field_validator("preferred_language")
    @classmethod
    def check_language(cls, v: str | None) -> str | None:
        if v is not None:
            valid = {"roman_urdu", "english", "urdu"}
            if v.lower() not in valid:
                raise ValueError(f"Language must be one of {valid}")
            return v.lower()
        return None


class TenantResponse(BaseModel):
    """Serialized tenant model representation."""
    id: str
    company_name: str
    country_code: str
    currency: str
    preferred_language: str
    whatsapp_notification_number: str | None
    created_at: datetime
    updated_at: datetime
    ad_accounts_count: int = 0
    active_credentials_count: int = 0
