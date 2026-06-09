"""Driver-scoped assignment start/end and current lookup.

These endpoints let a driver (not an admin) start and end their own ride.
The driver's identity and vehicle come from their active DriverBusSession,
so the driver cannot start/end another driver's ride.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.security import RequireDriver
from app.crud import assignment as crud_assignment
from app.crud import driver_bus_session as crud_driver_session
from app.crud import route as crud_route
from app.db.session import get_db
from app.models.assignment import Assignment

router = APIRouter(tags=["driver-assignments"])


class DriverAssignmentStartBody(BaseModel):
    route_id: int


class DriverAssignmentEndBody(BaseModel):
    assignment_id: int


class DriverAssignmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    driver_id: int
    vehicle_id: int
    route_id: int
    start_time: str
    end_time: str | None
    status: str
    driver_username: str | None = None
    vehicle_plate: str | None = None
    route_number: str | None = None


def _to_out(a: Assignment) -> DriverAssignmentOut:
    return DriverAssignmentOut(
        id=a.id,
        driver_id=a.driver_id,
        vehicle_id=a.vehicle_id,
        route_id=a.route_id,
        start_time=a.start_time.isoformat() if a.start_time else "",
        end_time=a.end_time.isoformat() if a.end_time else None,
        status=a.status,
        driver_username=a.driver.username if a.driver else None,
        vehicle_plate=a.vehicle.plate_number if a.vehicle else None,
        route_number=a.route.route_number if a.route else None,
    )


@router.get("/driver/assignments/current", response_model=DriverAssignmentOut | None)
async def get_current_assignment(
    current_user: RequireDriver,
    db: AsyncSession = Depends(get_db),
):
    """Return the current driver's active assignment, or None."""
    session = await crud_driver_session.get_active_session_for_driver(
        db, current_user.id
    )
    if not session:
        raise HTTPException(404, "No active driver session")

    assignment = await crud_assignment.get_active_assignment_by_vehicle(
        db, session.vehicle_id
    )
    if not assignment:
        return None
    return _to_out(assignment)


@router.post("/driver/assignments/start", response_model=DriverAssignmentOut)
async def start_driver_assignment(
    body: DriverAssignmentStartBody,
    current_user: RequireDriver,
    db: AsyncSession = Depends(get_db),
):
    """Driver starts their own ride. Vehicle comes from active session."""
    session = await crud_driver_session.get_active_session_for_driver(
        db, current_user.id
    )
    if not session:
        raise HTTPException(404, "No active driver session")

    if not await crud_route.get_route_by_id(db, body.route_id):
        raise HTTPException(404, "Route not found")

    existing = await crud_assignment.get_active_assignment_by_vehicle(
        db, session.vehicle_id
    )
    if existing:
        raise HTTPException(409, "Vehicle already has an active assignment")

    a = await crud_assignment.create_assignment(
        db, current_user.id, session.vehicle_id, body.route_id
    )
    res = await db.execute(
        select(Assignment)
        .where(Assignment.id == a.id)
        .options(
            selectinload(Assignment.driver),
            selectinload(Assignment.vehicle),
            selectinload(Assignment.route),
        )
    )
    full = res.scalar_one()
    return _to_out(full)


@router.post("/driver/assignments/end")
async def end_driver_assignment(
    body: DriverAssignmentEndBody,
    current_user: RequireDriver,
    db: AsyncSession = Depends(get_db),
):
    """Driver ends their own ride. Verifies assignment belongs to driver's vehicle."""
    session = await crud_driver_session.get_active_session_for_driver(
        db, current_user.id
    )
    if not session:
        raise HTTPException(404, "No active driver session")

    a = await crud_assignment.get_assignment_by_id(db, body.assignment_id)
    if not a:
        raise HTTPException(404, "Assignment not found")
    if a.status != "active":
        raise HTTPException(400, "Assignment is not active")
    if a.vehicle_id != session.vehicle_id:
        raise HTTPException(403, "Assignment does not belong to your vehicle")

    await crud_assignment.end_assignment(db, body.assignment_id)
    return {"status": "ended", "assignment_id": body.assignment_id}
