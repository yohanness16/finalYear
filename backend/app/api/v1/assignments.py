"""Admin assignment start/end and active list."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.security import RequireAdmin
from app.crud import assignment as crud_assignment
from app.crud import route as crud_route
from app.crud import user as crud_user
from app.crud import vehicle as crud_vehicle
from app.db.session import get_db
from app.models.assignment import Assignment

router = APIRouter(tags=["assignments"])


class AssignmentStartBody(BaseModel):
    driver_id: int
    vehicle_id: int
    route_id: int


class AssignmentEndBody(BaseModel):
    assignment_id: int


class AssignmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    driver_id: int
    vehicle_id: int
    route_id: int
    start_time: datetime
    end_time: datetime | None
    status: str
    driver_username: str | None = None
    vehicle_plate: str | None = None
    route_number: str | None = None


def _to_out(a: Assignment) -> AssignmentOut:
    return AssignmentOut(
        id=a.id,
        driver_id=a.driver_id,
        vehicle_id=a.vehicle_id,
        route_id=a.route_id,
        start_time=a.start_time,
        end_time=a.end_time,
        status=a.status,
        driver_username=a.driver.username if a.driver else None,
        vehicle_plate=a.vehicle.plate_number if a.vehicle else None,
        route_number=a.route.route_number if a.route else None,
    )


@router.get("/assignments/active", response_model=list[AssignmentOut])
async def list_active_assignments(
    current_user: RequireAdmin,
    db: AsyncSession = Depends(get_db),
):
    rows = await crud_assignment.list_active_assignments(db)
    return [_to_out(a) for a in rows]


@router.post("/assignments/start", response_model=AssignmentOut)
async def start_assignment(
    body: AssignmentStartBody,
    current_user: RequireAdmin,
    db: AsyncSession = Depends(get_db),
):
    if not await crud_user.get_user_by_id(db, body.driver_id):
        raise HTTPException(404, "Driver not found")
    if not await crud_vehicle.get_vehicle_by_id(db, body.vehicle_id):
        raise HTTPException(404, "Vehicle not found")
    if not await crud_route.get_route_by_id(db, body.route_id):
        raise HTTPException(404, "Route not found")
    existing = await crud_assignment.get_active_assignment_by_vehicle(
        db, body.vehicle_id
    )
    if existing:
        raise HTTPException(409, "Vehicle already has an active assignment")
    a = await crud_assignment.create_assignment(
        db, body.driver_id, body.vehicle_id, body.route_id
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


@router.post("/assignments/end")
async def end_assignment(
    body: AssignmentEndBody,
    current_user: RequireAdmin,
    db: AsyncSession = Depends(get_db),
):
    a = await crud_assignment.get_assignment_by_id(db, body.assignment_id)
    if not a:
        raise HTTPException(404, "Assignment not found")
    if a.status != "active":
        raise HTTPException(400, "Assignment is not active")
    await crud_assignment.end_assignment(db, body.assignment_id)
    return {"status": "ended", "assignment_id": body.assignment_id}
