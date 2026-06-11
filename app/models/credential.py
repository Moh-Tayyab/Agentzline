"""
Platform Credential ORM Model.

Encrypted token vault for Meta / WhatsApp API credentials.
Tokens are encrypted at rest using Fernet before database storage.
"""

import uuid
from datetime import datetime

from sqlalchemy import String, Text, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class PlatformCredential(Base):
    """
    Vault-encrypted API credentials per tenant.

    Stores encrypted access/refresh tokens for Meta and WhatsApp.
    Tokens are NEVER stored in plaintext — always use app.core.security
    to encrypt/decrypt.
    """

    __tablename__ = "platform_credentials"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    platform_name: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # META | WHATSAPP

    # Encrypted at rest via Fernet
    encrypted_access_token: Mapped[str] = mapped_column(Text, nullable=False)
    encrypted_refresh_token: Mapped[str | None] = mapped_column(Text)

    # Meta-specific fields
    meta_business_id: Mapped[str | None] = mapped_column(String(100))

    # Token lifecycle
    token_status: Mapped[str] = mapped_column(
        String(50), default="ACTIVE"
    )  # ACTIVE | EXPIRED | REVOKED
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_rotated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    tenant = relationship("Tenant", back_populates="credentials")

    def __repr__(self) -> str:
        return f"<PlatformCredential {self.platform_name} ({self.token_status})>"
