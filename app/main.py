"""
AgentZline — Bronze Tier MVP Entry Point.

FastAPI application factory and startup configuration.
Read-only Meta Ads monitoring + WhatsApp bilingual daily reports.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from app.core.config import get_settings
from app.core.database import init_db
from app.api.router import api_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup and shutdown events."""
    settings = get_settings()
    logger.info(f"🚀 AgentZline starting in {settings.APP_ENV} mode")

    # Initialize database connection pool
    await init_db()
    logger.info("✅ Database connection pool initialized")

    yield

    logger.info("🛑 AgentZline shutting down")


def create_application() -> FastAPI:
    """Create and configure the FastAPI application instance."""
    settings = get_settings()
    application = FastAPI(
        title=settings.APP_NAME,
        description=(
            "AgentZline — AI Media Buyer Engine. "
            "Bronze Tier: Meta Ads read-only monitoring + WhatsApp daily reports."
        ),
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs" if settings.DEBUG else None,
        redoc_url="/redoc" if settings.DEBUG else None,
    )

    # CORS middleware for future web dashboard
    application.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # Tighten in production
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Mount API routes
    application.include_router(api_router, prefix="/api/v1")

    return application


app = create_application()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=get_settings().DEBUG,
    )
