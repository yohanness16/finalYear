"""Telemetry ingestion and live tracking endpoints."""

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request

from app.core.limiter import limiter
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud import assignment as crud_assignment
from app.crud import tracking as crud_tracking
from app.crud import vehicle as crud_vehicle
from app.db.session import get_db
from app.schemas.tracking import TelemetryInput, AssignmentStart, AssignmentEnd
from app.utils.gps_validation import is_valid_coord, get_average_coord
from app.utils.redis_client import (
    get_last_coords,
    set_bus_live_pipeline,
)
from app.services.cv_engine import estimate_density

router = APIRouter()


async def _save_raw_telemetry(
    vehicle_id: int,
    lat: float,
    lon: float,
    pixel_count: int | None,
    raw_payload: dict | None,
):
    """Background task: persist raw telemetry to DB."""
    from app.db.session import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        await crud_tracking.create_raw_telemetry(
            db, vehicle_id, lat, lon, pixel_count, raw_payload
        )
        await db.commit()


@router.post("/telemetry")
@limiter.limit("300/minute")
async def receive_telemetry(
    request: Request,
    data: TelemetryInput,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Receive GPS + density data from SIM7600/ESP32-CAM. Returns immediately; raw save in background."""
    vehicle = await crud_vehicle.get_vehicle_by_device_id(db, data.device_id)
    if not vehicle:
        raise HTTPException(404, "Vehicle not registered")
    last_coords = await get_last_coords(vehicle.plate_number)
    if not is_valid_coord(data.lat, data.lon, last_coords):
        avg = get_average_coord(last_coords)
        if avg:
            data.lat, data.lon = avg
        else:
            return {"status": "rejected", "reason": "gps_outlier"}
    assignment = await crud_assignment.get_active_assignment_by_vehicle(db, vehicle.id)
    occupancy = 0
    if data.pixel_count is not None:
        occupancy = estimate_density(data.pixel_count)
    background_tasks.add_task(
        _save_raw_telemetry,
        vehicle.id,
        data.lat,
        data.lon,
        data.pixel_count,
        data.raw_payload,
    )
    await set_bus_live_pipeline(
        vehicle.plate_number,
        data.lat,
        data.lon,
        occupancy,
        assignment.id if assignment else 0,
    )
    return {"status": "received"}


@router.post("/assignments/start")
async def start_assignment(body: AssignmentStart, db: AsyncSession = Depends(get_db)):
    """Driver check-in: start trip with vehicle and route."""
    existing_driver = await crud_assignment.get_active_assignment_by_driver(db, body.driver_id)
    if existing_driver:
        raise HTTPException(
            400,
            "Driver already has an active assignment. End current trip first.",
        )
    existing_vehicle = await crud_assignment.get_active_assignment_by_vehicle(db, body.vehicle_id)
    if existing_vehicle:
        raise HTTPException(
            400,
            "Vehicle already has an active assignment. End current trip first.",
        )
    assignment = await crud_assignment.create_assignment(
        db, body.driver_id, body.vehicle_id, body.route_id
    )
    return {"assignment_id": assignment.id, "status": "active"}


@router.post("/assignments/end")
async def end_assignment(body: AssignmentEnd, db: AsyncSession = Depends(get_db)):
    """End trip."""
    a = await crud_assignment.end_assignment(db, body.assignment_id)
    if not a:
        raise HTTPException(404, "Assignment not found")
    return {"status": "completed"}
