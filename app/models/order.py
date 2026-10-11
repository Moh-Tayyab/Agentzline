"""
Order and Courier Event ORM Models (Phase-4 Gold Tier).

Stores e-commerce orders for multi-courier COD tracking, RTO detection,
and marketing attribution (Meta campaign / fbclid / UTM).
"""

import uuid
from datetime import datetime

from sqlalchemy import String, Numeric, DateTime, ForeignKey, func, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, JSON_TYPE


class Order(Base):
    """
    E-Commerce Order table.

    Tracks customer orders, COD payments, delivery/RTO fees, and campaign attribution.
    """

    __tablename__ = "orders"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    external_order_id: Mapped[str] = mapped_column(String(100), nullable=False)  # e.g., "1042" / "#1042"
    order_number: Mapped[str | None] = mapped_column(String(100))
    customer_phone: Mapped[str | None] = mapped_column(String(50))
    city: Mapped[str | None] = mapped_column(String(100))
    payment_method: Mapped[str] = mapped_column(String(50), default="COD")  # COD | PREPAID

    # Financials (PKR)
    total_amount_pkr: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    cogs_amount_pkr: Mapped[float] = mapped_column(Numeric(12, 2), default=0.0)
    courier_fee_pkr: Mapped[float] = mapped_column(Numeric(10, 2), default=0.0)
    return_fee_pkr: Mapped[float] = mapped_column(Numeric(10, 2), default=0.0)

    # Courier Fulfillment
    courier_name: Mapped[str | None] = mapped_column(String(50))  # e.g. "POSTEX"
    tracking_number: Mapped[str | None] = mapped_column(String(100), index=True)
    current_status: Mapped[str] = mapped_column(
        String(50), default="PENDING"
    )  # PENDING, BOOKED, IN_TRANSIT, OUT_FOR_DELIVERY, DELIVERED, RETURNED, CANCELLED

    # Marketing Attribution
    campaign_id: Mapped[str | None] = mapped_column(String(100), index=True)
    ad_id: Mapped[str | None] = mapped_column(String(100))
    utm_source: Mapped[str | None] = mapped_column(String(100))
    utm_medium: Mapped[str | None] = mapped_column(String(100))
    utm_campaign: Mapped[str | None] = mapped_column(String(100))
    fbclid: Mapped[str | None] = mapped_column(String(255))

    order_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    returned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    tenant = relationship("Tenant", back_populates="orders")
    courier_events = relationship(
        "CourierEvent",
        back_populates="order",
        lazy="selectin",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Order {self.external_order_id} ({self.current_status})>"


class CourierEvent(Base):
    """
    Courier tracking event history.

    Immutable log of every webhook or tracking status event received from a courier.
    """

    __tablename__ = "courier_events"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    order_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("orders.id", ondelete="CASCADE"), nullable=False
    )

    courier_name: Mapped[str] = mapped_column(String(50), nullable=False)  # POSTEX
    tracking_number: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    raw_status: Mapped[str] = mapped_column(String(100), nullable=False)
    normalized_status: Mapped[str] = mapped_column(String(50), nullable=False)  # BOOKED, IN_TRANSIT, DELIVERED, RETURNED, etc.

    event_timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    raw_payload: Mapped[dict | None] = mapped_column(JSON_TYPE)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    order = relationship("Order", back_populates="courier_events")

    def __repr__(self) -> str:
        return f"<CourierEvent {self.courier_name} {self.tracking_number}: {self.normalized_status}>"
