"""
Tenant ORM Model.

Multi-tenant agency/brand structure — the top-level organizational unit.
"""

import uuid
from datetime import datetime

from sqlalchemy import String, DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class Tenant(Base):
    """
    Tenants/Agencies table.

    Each tenant represents an agency or brand using AgentZline.
    All ad accounts and credentials belong to a tenant.
    """

    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_name: Mapped[str] = mapped_column(String(255), nullable=False)
    country_code: Mapped[str] = mapped_column(String(10), default="PK")
    currency: Mapped[str] = mapped_column(String(10), default="PKR")
    preferred_language: Mapped[str] = mapped_column(
        String(10), default="roman_urdu"
    )  # roman_urdu | urdu | english
    whatsapp_notification_number: Mapped[str | None] = mapped_column(String(50))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    ad_accounts = relationship("AdAccount", back_populates="tenant", lazy="selectin")
    credentials = relationship("PlatformCredential", back_populates="tenant", lazy="selectin")

    def __repr__(self) -> str:
        return f"<Tenant {self.company_name}>"
