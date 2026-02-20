"""Data retention: delete old raw_telemetry and optionally trip_history."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.raw_telemetry import RawTelemetry
from app.models.trip_history import TripHistory


async def cleanup_raw_telemetry(db: AsyncSession, batch_size: int = 10000) -> int:
    """Delete raw_telemetry older than RAW_TELEMETRY_RETENTION_DAYS. Returns deleted count."""
    settings = get_settings()
    cutoff = datetime.now(timezone.utc) - timedelta(days=settings.RAW_TELEMETRY_RETENTION_DAYS)
    result = await db.execute(
        delete(RawTelemetry).where(RawTelemetry.timestamp < cutoff)
    )
    await db.flush()
    return result.rowcount or 0


async def cleanup_trip_history(db: AsyncSession, batch_size: int = 5000) -> int:
    """Delete trip_history older than TRIP_HISTORY_RETENTION_DAYS. Returns deleted count."""
    settings = get_settings()
    cutoff = datetime.now(timezone.utc) - timedelta(days=settings.TRIP_HISTORY_RETENTION_DAYS)
    result = await db.execute(
        delete(TripHistory).where(TripHistory.arrival_time < cutoff)
    )
    await db.flush()
    return result.rowcount or 0


async def run_cleanup(db: AsyncSession) -> dict:
    """Run all cleanup tasks. Returns counts."""
    raw_deleted = await cleanup_raw_telemetry(db)
    trip_deleted = await cleanup_trip_history(db)
    return {"raw_telemetry_deleted": raw_deleted, "trip_history_deleted": trip_deleted}
