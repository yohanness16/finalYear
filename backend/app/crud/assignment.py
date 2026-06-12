"""Assignment CRUD operations."""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.assignment import Assignment


async def get_active_assignment_by_driver(
    db: AsyncSession, driver_id: int
) -> Assignment | None:
    result = await db.execute(
        select(Assignment)
        .where(Assignment.driver_id == driver_id, Assignment.status == "active")
        .order_by(Assignment.start_time.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def get_active_assignment_by_vehicle(
    db: AsyncSession, vehicle_id: int
) -> Assignment | None:
    result = await db.execute(
        select(Assignment)
        .where(Assignment.vehicle_id == vehicle_id, Assignment.status == "active")
        .options(
            selectinload(Assignment.route),
            selectinload(Assignment.vehicle),
            selectinload(Assignment.driver),
        )
        .order_by(Assignment.start_time.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def list_active_assignments(db: AsyncSession) -> list[Assignment]:
    result = await db.execute(
        select(Assignment)
        .where(Assignment.status == "active")
        .options(
            selectinload(Assignment.vehicle),
            selectinload(Assignment.route),
            selectinload(Assignment.driver),
        )
        .order_by(Assignment.start_time.desc())
    )
    return list(result.scalars().unique().all())


async def create_assignment(
    db: AsyncSession, driver_id: int, vehicle_id: int, route_id: int
) -> Assignment:
    assignment = Assignment(
        driver_id=driver_id, vehicle_id=vehicle_id, route_id=route_id, status="active"
    )
    db.add(assignment)
    await db.flush()
    await db.refresh(assignment)
    return assignment


async def end_assignment(db: AsyncSession, assignment_id: int) -> Assignment | None:
    # Load assignment WITH relationships eagerly so we can access
    # vehicle.plate_number and route.route_number after flush without
    # triggering a lazy load (which crashes with MissingGreenlet in async).
    result = await db.execute(
        select(Assignment)
        .where(Assignment.id == assignment_id)
        .options(
            selectinload(Assignment.vehicle),
            selectinload(Assignment.route),
        )
    )
    assignment = result.scalar_one_or_none()
    if assignment is None:
        return None

    # Snapshot the values we need BEFORE flush/refresh wipe the
    # eagerly-loaded relationship objects off the ORM state.
    plate = (
        getattr(assignment.vehicle, "plate_number", None)
        if assignment.vehicle else None
    )
    route_number = (
        getattr(assignment.route, "route_number", None)
        if assignment.route else None
    )

    assignment.status = "completed"
    assignment.end_time = datetime.now(UTC)
    await db.flush()

    # Re-fetch with relationships so the returned object is fully populated.
    # We do NOT use db.refresh() here because refresh() drops eager-loaded
    # relationships, which would cause MissingGreenlet on any subsequent access.
    result2 = await db.execute(
        select(Assignment)
        .where(Assignment.id == assignment_id)
        .options(
            selectinload(Assignment.vehicle),
            selectinload(Assignment.route),
            selectinload(Assignment.driver),
        )
    )
    assignment = result2.scalar_one_or_none()

    # Clear all live Redis data for this bus so it immediately
    # disappears from mobile search results.
    if plate:
        try:
            from app.utils.redis_client import clear_bus_live_data
            await clear_bus_live_data(plate, route_number)
        except Exception:
            import logging
            logging.exception(
                "clear_bus_live_data failed for plate %s on assignment %s",
                plate,
                assignment_id,
            )

    return assignment


async def get_assignment_by_id(
    db: AsyncSession, assignment_id: int
) -> Assignment | None:
    result = await db.execute(select(Assignment).where(Assignment.id == assignment_id))
    return result.scalar_one_or_none()