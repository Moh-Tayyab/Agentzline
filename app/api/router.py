"""
AgentZline API Router.

Aggregates all route modules under a single v1 prefix.
"""

from fastapi import APIRouter

from app.api.endpoints import health, whatsapp_webhook, meta_accounts

api_router = APIRouter()

# Health check
api_router.include_router(health.router, tags=["health"])

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
