"""
Ad Account ORM Model.

Represents a Meta ad account managed under a tenant.
Bronze Tier: stores account config and budget ceiling only.
"""

import uuid
from datetime import datetime

from sqlalchemy import String, Boolean, Numeric, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class AdAccount(Base):
    """
    Managed Meta Ad Accounts.

    Each row is a separate ad account being monitored.
    Budget ceiling is a hard limit that no agent can override.
    """

    __tablename__ = "ad_accounts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    platform: Mapped[str] = mapped_column(String(50), default="META")
    external_account_id: Mapped[str] = mapped_column(
        String(100), unique=True, nullable=False
    )  # e.g., act_123456789
    account_name: Mapped[str | None] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Hard budget ceiling — agents CANNOT exceed this
    max_budget_ceiling_pkr: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    target_cpa_pkr: Mapped[float | None] = mapped_column(Numeric(12, 2))
    target_roas: Mapped[float | None] = mapped_column(Numeric(6, 2))

    # UTM tracking template
    utm_template: Mapped[str] = mapped_column(
        String(255),
        default="utm_source=meta&utm_medium=cpc&utm_campaign={{campaign.name}}",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    tenant = relationship("Tenant", back_populates="ad_accounts")
    metrics_snapshots = relationship(
        "CampaignMetricsSnapshot", back_populates="ad_account", lazy="selectin"
    )

    def __repr__(self) -> str:
        return f"<AdAccount {self.external_account_id} ({self.account_name})>"
