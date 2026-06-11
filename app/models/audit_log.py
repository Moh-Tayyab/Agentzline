"""
Audit Log ORM Model.

Immutable audit trail for all agent actions and human decisions.
Every proposed action, approval, and rejection is logged here.
"""

import uuid
from datetime import datetime

from sqlalchemy import String, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AuditLog(Base):
    """
    Agent action audit log.

    Records every action the system proposes or executes:
    - FETCH_METRICS: routine data sync
    - SUGGESTED_PAUSE: agent proposes pausing a campaign
    - USER_APPROVED: human approved via WhatsApp button
    - USER_REJECTED: human rejected via WhatsApp button
    - ALERT_SENT: anomaly alert sent to WhatsApp
    - REPORT_SENT: daily summary delivered
    """

    __tablename__ = "agent_action_audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    ad_account_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ad_accounts.id")
    )

    action_type: Mapped[str] = mapped_column(String(100), nullable=False)
    action_details: Mapped[dict] = mapped_column(JSONB, nullable=False)
    executed_by: Mapped[str] = mapped_column(
        String(100), default="AGENTZLINE_ENGINE"
    )
    executed_by_whatsapp_num: Mapped[str | None] = mapped_column(String(50))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    def __repr__(self) -> str:
        return f"<AuditLog {self.action_type} @ {self.created_at}>"
