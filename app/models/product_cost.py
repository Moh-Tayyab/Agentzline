"""
Product Cost ORM Model (Phase-4 Gold Tier).

Stores Cost of Goods Sold (COGS) by SKU per tenant for true net margin calculations.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Numeric, String, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class ProductCost(Base):
    """
    Product SKU Cost table (COGS).

    Used to compute accurate net margins and contribution profit.
    """

    __tablename__ = "product_costs"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    sku: Mapped[str] = mapped_column(String(100), nullable=False)
    product_name: Mapped[str | None] = mapped_column(String(255))
    cost_price_pkr: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    selling_price_pkr: Mapped[float | None] = mapped_column(Numeric(10, 2))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "sku", name="uq_tenant_product_sku"),
    )

    # Relationships
    tenant = relationship("Tenant", back_populates="product_costs")

    def __repr__(self) -> str:
        return f"<ProductCost {self.sku} (Cost: {self.cost_price_pkr} PKR)>"
