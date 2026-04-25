"""System settings CRUD."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.system_settings import SystemSettings


async def get_setting(db: AsyncSession, key: str) -> str | None:
    result = await db.execute(select(SystemSettings).where(SystemSettings.key == key))
    row = result.scalar_one_or_none()
    return row.value if row else None


async def get_use_ml_for_prod(db: AsyncSession) -> bool:
    """DB toggle overrides env when explicitly set."""
    val = await get_setting(db, "use_ml_for_prod")
    if val == "true":
        return True
    if val == "false":
        return False
    return get_settings().USE_ML_FOR_PROD


async def set_setting(db: AsyncSession, key: str, value: str) -> None:
    result = await db.execute(select(SystemSettings).where(SystemSettings.key == key))
    row = result.scalar_one_or_none()
    if row:
        row.value = value
    else:
        db.add(SystemSettings(key=key, value=value))
    await db.flush()
