"""Vehicle, telemetry, and position endpoints."""

import re
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.limiter import limiter
from app.core.security import RequireAdmin
from app.crud import route as crud_route
from app.crud import vehicle as crud_vehicle
from app.db.session import get_db
from app.models.user import User
from app.models.vehicle import Vehicle
from app.schemas.vehicle import (
    LivePositionsEnvelope,
    TelemetryInput,
    VehicleAdminUpdate,
    VehicleCreate,
    VehiclePosition,
    VehicleResponse,
)
from app.services.telemetry_ingest import process_telemetry
from app.utils.occupancy import resolve_occupancy_level

router = APIRouter(tags=["vehicles"])


def _default_plate_from_device_id(device_id: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]", "", device_id).upper()
    tail = cleaned[-8:] if cleaned else "BUS00001"
    return f"ESP-{tail}"[:20]


def _vehicle_to_response(v: Vehicle) -> VehicleResponse:
    return VehicleResponse(
        id=v.id,
        plate_number=v.plate_number,
        device_id=v.device_id,
        bus_type=v.bus_type,
        capacity=v.capacity,
        is_active=v.is_active,
        route_id=v.route_id,
        route_number=v.route.route_number if v.route is not None else None,
        last_lat=v.last_lat,
        last_lon=v.last_lon,
        speed=v.speed,
        position_updated_at=v.position_updated_at,
    )


@router.post("/vehicles", response_model=VehicleResponse)
async def register_vehicle(
    vehicle: VehicleCreate,
    current_user: User = Depends(RequireAdmin),
    db: AsyncSession = Depends(get_db),
):
    """Register a new vehicle. Requires admin authentication."""
    import sys
    print(f">>> REQUEST REACHED register_vehicle: vehicle={vehicle.model_dump()}", file=sys.stderr, flush=True)
    if await crud_vehicle.get_vehicle_by_device_id(db, vehicle.device_id):
        raise HTTPException(400, "Device already registered")
    if await crud_vehicle.get_vehicle_by_plate(db, vehicle.plate_number):
        raise HTTPException(400, "Plate number already registered")
    v = await crud_vehicle.create_vehicle(
        db,
        vehicle.plate_number,
        vehicle.device_id,
        vehicle.bus_type,
        vehicle.capacity,
        vehicle.is_active,
    )
    await db.refresh(v, ["route"])
    return _vehicle_to_response(v)


@router.get("/vehicles/positions", response_model=LivePositionsEnvelope)
async def get_all_positions(db: AsyncSession = Depends(get_db)):
    positions = await crud_vehicle.get_live_positions(db)
    return LivePositionsEnvelope(positions=positions, timestamp=time.time())


@router.get("/vehicles/positions/{vehicle_id}", response_model=VehiclePosition)
async def get_vehicle_position(vehicle_id: int, db: AsyncSession = Depends(get_db)):
    pos = await crud_vehicle.get_position(db, vehicle_id)
    if not pos:
        raise HTTPException(404, "Position not found")
    return VehiclePosition(**pos)


@router.get("/vehicles", response_model=list[VehicleResponse])
async def list_vehicles(
    skip: int = 0, limit: int = 100, db: AsyncSession = Depends(get_db)
):
    vehicles = await crud_vehicle.get_vehicles(db, skip, limit)
    return [_vehicle_to_response(v) for v in vehicles]


@router.get("/vehicles/{vehicle_id}", response_model=VehicleResponse)
async def get_vehicle(vehicle_id: int, db: AsyncSession = Depends(get_db)):
    v = await crud_vehicle.get_vehicle_with_positions(db, vehicle_id)
    if not v:
        raise HTTPException(404, "Vehicle not found")
    return _vehicle_to_response(v)


@router.put("/vehicles/{vehicle_id}", response_model=VehicleResponse)
async def admin_update_vehicle(
    vehicle_id: int,
    body: VehicleAdminUpdate,
    current_user: RequireAdmin,
    db: AsyncSession = Depends(get_db),
):
    """Set optional fields such as route_id for corridor validation."""
    v = await crud_vehicle.get_vehicle_by_id(db, vehicle_id)
    if not v:
        raise HTTPException(404, "Vehicle not found")
    data = body.model_dump(exclude_unset=True)
    if "route_id" in data:
        rid = data["route_id"]
        if rid is not None and not await crud_route.get_route_by_id(db, rid):
            raise HTTPException(404, "Route not found")
        v = await crud_vehicle.set_vehicle_route(db, vehicle_id, rid)
        if not v:
            raise HTTPException(404, "Vehicle not found")
    return _vehicle_to_response(v)


@router.post("/vehicles/telemetry")
@limiter.limit("300/minute")
async def receive_telemetry(
    request: Request,
    data: TelemetryInput,
    db: AsyncSession = Depends(get_db),
):
    """Receive GPS telemetry and update vehicle position.

    Auto-provisions the vehicle if device_id is not yet registered.
    Delegates to the unified process_telemetry() service.
    """
    vehicle = await crud_vehicle.get_vehicle_by_device_id(db, data.device_id)
    if not vehicle:
        vehicle = await crud_vehicle.create_vehicle(
            db,
            plate_number=_default_plate_from_device_id(data.device_id),
            device_id=data.device_id,
            bus_type="ESP32-CAM",
            capacity=None,
            is_active=True,
        )

    occupancy_level = resolve_occupancy_level(
        pixel_count=data.pixel_count,
        raw_payload=data.raw_payload,
    )

    result = await process_telemetry(
        db=db,
        device_id=data.device_id,
        lat=data.lat,
        lon=data.lon,
        speed=data.speed or 0.0,
        occupancy_level=occupancy_level,
        compute_eta=False,
        persist_raw=True,
    )

    return result
