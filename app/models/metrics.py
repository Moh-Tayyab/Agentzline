"""
Campaign Metrics Snapshot ORM Model.

Time-series cache of daily campaign-level metrics pulled from Meta Graph API.
Each row is one campaign's metrics for one date.
"""

import uuid
from datetime import date, datetime

from sqlalchemy import String, Integer, Numeric, Date, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class CampaignMetricsSnapshot(Base):
    """
    Daily campaign metrics cache.

    Populated by the scheduled Meta API sync job.
    Stores raw Meta API payload in JSONB for reprocessing.
    """

    __tablename__ = "campaign_metrics_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    ad_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ad_accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    external_campaign_id: Mapped[str] = mapped_column(String(100), nullable=False)
    campaign_name: Mapped[str | None] = mapped_column(String(255))

    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False)

    # Core metrics
    spend: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    impressions: Mapped[int] = mapped_column(Integer, nullable=False)
    clicks: Mapped[int] = mapped_column(Integer, nullable=False)
    conversions: Mapped[int] = mapped_column(Integer, nullable=False)
    roas: Mapped[float] = mapped_column(Numeric(6, 2), nullable=False)

    # Derived metrics (computed on insert)
    ctr: Mapped[float | None] = mapped_column(Numeric(6, 4))
    cpc: Mapped[float | None] = mapped_column(Numeric(10, 2))
    cpa: Mapped[float | None] = mapped_column(Numeric(10, 2))

    # Full raw API response for reprocessing
    raw_payload: Mapped[dict | None] = mapped_column(JSONB)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    ad_account = relationship("AdAccount", back_populates="metrics_snapshots")

    def __repr__(self) -> str:
        return f"<CampaignMetrics {self.campaign_name} @ {self.snapshot_date}>"
