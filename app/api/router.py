"""
AgentZline API Router.

Aggregates all route modules under a single v1 prefix.
"""

from fastapi import APIRouter

from app.api.endpoints import (
    courier_webhook,
    credentials,
    health,
    hitl_actions,
    meta_accounts,
    orders,
    tenants,
    whatsapp_webhook,
)

api_router = APIRouter()

# Health check
api_router.include_router(health.router, tags=["health"])

# Tenant / Agency onboarding (Phase-1 Task #3)
api_router.include_router(
    tenants.router,
    prefix="/tenants",
    tags=["tenants"],
)

# WhatsApp webhook receiver (HITL button clicks)
api_router.include_router(
    whatsapp_webhook.router,
    prefix="/whatsapp",
    tags=["whatsapp"],
)

# Meta ad accounts management
api_router.include_router(
    meta_accounts.router,
    prefix="/meta",
    tags=["meta"],
)

# Credential vault management (Phase-1 Task #2)
api_router.include_router(
    credentials.router,
    prefix="/credentials",
    tags=["credentials"],
)

# Phase-4 Gold Tier: Orders and Product Costs (COGS)
api_router.include_router(
    orders.router,
    prefix="/orders",
    tags=["orders"],
)

# Phase-4 Gold Tier: Multi-courier webhook receiver (PostEx MVP)
api_router.include_router(
    courier_webhook.router,
    prefix="/courier",
    tags=["courier"],
)

# Phase-3 Silver Tier: Direct HITL action endpoint (POST /actions/pause)
api_router.include_router(
    hitl_actions.router,
    prefix="/actions",
    tags=["actions"],
)
