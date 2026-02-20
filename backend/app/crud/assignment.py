"""Assignment CRUD operations."""

from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.assignment import Assignment
from app.models.route import Route
from app.models.vehicle import Vehicle


async def get_active_assignment_by_driver(db: AsyncSession, driver_id: int) -> Assignment | None:
    result = await db.execute(
        select(Assignment)
        .where(Assignment.driver_id == driver_id, Assignment.status == "active")
        .order_by(Assignment.start_time.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def get_active_assignment_by_vehicle(db: AsyncSession, vehicle_id: int) -> Assignment | None:
    result = await db.execute(
        select(Assignment)
        .where(Assignment.vehicle_id == vehicle_id, Assignment.status == "active")
        .options(selectinload(Assignment.route), selectinload(Assignment.vehicle))
        .order_by(Assignment.start_time.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def create_assignment(db: AsyncSession, driver_id: int, vehicle_id: int, route_id: int) -> Assignment:
    assignment = Assignment(driver_id=driver_id, vehicle_id=vehicle_id, route_id=route_id, status="active")
    db.add(assignment)
    await db.flush()
    await db.refresh(assignment)
    return assignment


async def end_assignment(db: AsyncSession, assignment_id: int) -> Assignment | None:
    result = await db.execute(select(Assignment).where(Assignment.id == assignment_id))
    assignment = result.scalar_one_or_none()
    if assignment:
        assignment.status = "completed"
        assignment.end_time = datetime.now(timezone.utc)
        await db.flush()
        await db.refresh(assignment)
    return assignment
