"""AgentZline SQLAlchemy ORM models package."""

from app.models.base import Base
from app.models.tenant import Tenant
from app.models.ad_account import AdAccount
from app.models.credential import PlatformCredential
from app.models.metrics import CampaignMetricsSnapshot
from app.models.audit_log import AuditLog

# Backward compatibility aliases
DailyCampaignMetric = CampaignMetricsSnapshot
AgentActionAuditLog = AuditLog

__all__ = [
    "Base",
    "Tenant",
    "AdAccount",
    "PlatformCredential",
    "CampaignMetricsSnapshot",
    "DailyCampaignMetric",
    "AuditLog",
    "AgentActionAuditLog",
]
