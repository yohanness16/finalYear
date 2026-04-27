"""CRUD operations for driver bus sessions."""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.driver_bus_session import DriverBusSession


async def get_active_session_for_driver(
    db: AsyncSession, driver_id: int
) -> DriverBusSession | None:
    result = await db.execute(
        select(DriverBusSession)
        .where(DriverBusSession.driver_id == driver_id, DriverBusSession.status == "active")
        .order_by(DriverBusSession.login_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def create_session(
    db: AsyncSession, driver_id: int, vehicle_id: int
) -> DriverBusSession:
    session = DriverBusSession(
        driver_id=driver_id,
        vehicle_id=vehicle_id,
        status="active",
    )
    db.add(session)
    await db.flush()
    await db.refresh(session)
    return session


async def get_session_by_id(db: AsyncSession, session_id: int) -> DriverBusSession | None:
    result = await db.execute(select(DriverBusSession).where(DriverBusSession.id == session_id))
    return result.scalar_one_or_none()


async def end_session(db: AsyncSession, session_id: int) -> DriverBusSession | None:
    result = await db.execute(select(DriverBusSession).where(DriverBusSession.id == session_id))
    session = result.scalar_one_or_none()
    if not session:
        return None
    session.status = "ended"
    session.logout_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(session)
    return session
