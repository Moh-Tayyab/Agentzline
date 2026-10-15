"""
Pydantic Schemas for Orders, Courier Events, and Product Costs (Phase-4 Gold Tier).
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class OrderCreate(BaseModel):
    """Schema for creating a new e-commerce order."""
    tenant_id: uuid.UUID
    external_order_id: str = Field(..., max_length=100)
    order_number: str | None = None
    customer_phone: str | None = None
    city: str | None = None
    payment_method: str = "COD"  # COD | PREPAID
    total_amount_pkr: float = Field(..., ge=0)
    cogs_amount_pkr: float = Field(default=0.0, ge=0)
    courier_fee_pkr: float = Field(default=0.0, ge=0)
    return_fee_pkr: float = Field(default=0.0, ge=0)
    courier_name: str | None = "POSTEX"
    tracking_number: str | None = None
    campaign_id: str | None = None
    ad_id: str | None = None
    utm_source: str | None = None
    utm_medium: str | None = None
    utm_campaign: str | None = None
    fbclid: str | None = None
    sku: str | None = None
    quantity: int = Field(default=1, ge=1)


class OrderResponse(BaseModel):
    """Response schema for order details."""
    id: uuid.UUID
    tenant_id: uuid.UUID
    external_order_id: str
    order_number: str | None = None
    customer_phone: str | None = None
    city: str | None = None
    payment_method: str
    total_amount_pkr: float
    cogs_amount_pkr: float
    courier_fee_pkr: float
    return_fee_pkr: float
    courier_name: str | None = None
    tracking_number: str | None = None
    current_status: str
    campaign_id: str | None = None
    utm_campaign: str | None = None
    delivered_at: datetime | None = None
    returned_at: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ProductCostCreate(BaseModel):
    """Schema for setting product SKU Cost of Goods Sold."""
    tenant_id: uuid.UUID
    sku: str = Field(..., max_length=100)
    product_name: str | None = None
    cost_price_pkr: float = Field(..., ge=0)
    selling_price_pkr: float | None = Field(default=None, ge=0)


class ProductCostResponse(BaseModel):
    """Response schema for product cost."""
    id: uuid.UUID
    tenant_id: uuid.UUID
    sku: str
    product_name: str | None = None
    cost_price_pkr: float
    selling_price_pkr: float | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class CourierWebhookResponse(BaseModel):
    """Response schema for courier webhook callback."""
    status: str
    courier: str
    tracking_number: str | None = None
    order_id: str | None = None
    normalized_status: str | None = None
