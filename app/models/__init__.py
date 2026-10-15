"""AgentZline SQLAlchemy ORM models package."""

from app.models.ad_account import AdAccount
from app.models.audit_log import AuditLog
from app.models.base import Base
from app.models.credential import PlatformCredential
from app.models.metrics import CampaignMetricsSnapshot
from app.models.order import CourierEvent, Order
from app.models.product_cost import ProductCost
from app.models.tenant import Tenant

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
    "Order",
    "CourierEvent",
    "ProductCost",
]
