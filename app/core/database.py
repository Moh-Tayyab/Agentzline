"""
AgentZline Database Configuration.

Async SQLAlchemy session factory and engine setup for PostgreSQL.
"""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from loguru import logger

from app.core.config import get_settings

settings = get_settings()

# Async engine — configured from DATABASE_URL
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DATABASE_ECHO,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
)

# Session factory for dependency injection
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def init_db() -> None:
    """Initialize database connection pool. Called during app startup."""
    logger.info(f"Connecting to database: {settings.DATABASE_URL.split('@')[-1]}")
    # Connection test
    async with engine.begin() as conn:
        await conn.execute(conn.get_raw_connection().__class__.__module__ and "SELECT 1")


async def get_db() -> AsyncSession:
    """FastAPI dependency that yields an async database session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
