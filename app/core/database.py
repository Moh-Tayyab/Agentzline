"""
AgentZline Database Configuration.

Async SQLAlchemy session factory and engine setup for PostgreSQL.
"""

from collections.abc import AsyncGenerator

from loguru import logger
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings

settings = get_settings()

# Engine kwargs based on database driver
engine_kwargs: dict[str, object] = {
    "echo": settings.DATABASE_ECHO,
}
if "sqlite" not in settings.DATABASE_URL:
    engine_kwargs.update({
        "pool_size": 5,
        "max_overflow": 10,
        "pool_pre_ping": True,
    })

engine = create_async_engine(settings.DATABASE_URL, **engine_kwargs)

# Session factory for dependency injection
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)
async_session_maker = AsyncSessionLocal


async def init_db() -> None:
    """Initialize database connection pool and dev tables. Called during app startup."""
    logger.info(f"Connecting to database: {settings.DATABASE_URL.split('@')[-1]}")
    # Connection test using explicit executable text clause
    async with engine.begin() as conn:
        await conn.execute(text("SELECT 1"))

    # In development mode, auto-create tables if Alembic migrations haven't run yet
    if settings.APP_ENV == "development":
        import app.models  # noqa: F401  # Ensure all model classes are registered on Base.metadata
        from app.models.base import Base

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("✅ Database tables verified/created in development mode")


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields an async database session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
