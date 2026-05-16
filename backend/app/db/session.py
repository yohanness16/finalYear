"""Database session and engine setup."""

from collections.abc import AsyncGenerator
from typing import Annotated

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings

settings = get_settings()

# Convert postgresql:// to postgresql+asyncpg:// for async
database_url = settings.DATABASE_URL
if "postgresql+asyncpg" not in database_url:
    # This handles both 'postgresql://' and 'postgresql+psycopg2://'
    database_url = database_url.replace("postgresql", "postgresql+asyncpg", 1)
    # Just in case you had +psycopg2 in there, let's clean it up
    database_url = database_url.replace(
        "postgresql+asyncpg+psycopg2", "postgresql+asyncpg"
    )
if database_url.startswith("postgresql://"):
    database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)

engine = create_async_engine(
    database_url,
    echo=False,
    pool_pre_ping=True,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency that yields a database session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


DbSession = Annotated[AsyncSession, "DbSession"]
