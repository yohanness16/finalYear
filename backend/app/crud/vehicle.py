"""Vehicle CRUD operations."""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.assignment import Assignment
from app.models.vehicle import Vehicle


async def get_vehicle_by_id(db: AsyncSession, vehicle_id: int) -> Vehicle | None:
    result = await db.execute(
        select(Vehicle)
        .where(Vehicle.id == vehicle_id)
        .options(selectinload(Vehicle.route))
    )
    return result.scalar_one_or_none()


async def get_vehicle_by_device_id(db: AsyncSession, device_id: str) -> Vehicle | None:
    result = await db.execute(
        select(Vehicle)
        .where(Vehicle.device_id == device_id)
        .options(selectinload(Vehicle.route))
    )
    return result.scalar_one_or_none()


async def get_vehicle_by_plate(db: AsyncSession, plate_number: str) -> Vehicle | None:
    result = await db.execute(
        select(Vehicle)
        .where(Vehicle.plate_number == plate_number)
        .options(selectinload(Vehicle.route))
    )
    return result.scalar_one_or_none()


async def get_vehicles(db: AsyncSession, skip: int = 0, limit: int = 100) -> list[Vehicle]:
    result = await db.execute(
        select(Vehicle)
        .options(selectinload(Vehicle.route))
        .offset(skip)
        .limit(limit)
    )
    return list(result.scalars().all())


async def get_vehicle_with_positions(db: AsyncSession, vehicle_id: int) -> Vehicle | None:
    return await get_vehicle_by_id(db, vehicle_id)


async def get_live_positions(db: AsyncSession) -> dict[str, dict]:
    """Positions keyed by vehicle id (string) for JSON stability."""
    active_assignment_id = (
        select(Assignment.id)
        .where(Assignment.vehicle_id == Vehicle.id, Assignment.status == "active")
        .order_by(Assignment.start_time.desc())
        .limit(1)
        .scalar_subquery()
    )
    result = await db.execute(
        select(
            Vehicle.id,
            Vehicle.plate_number,
            Vehicle.last_lat,
            Vehicle.last_lon,
            Vehicle.speed,
            Vehicle.route_id,
            Vehicle.position_updated_at,
            active_assignment_id.label("assignment_id"),
        )
    )
    rows = result.all()
    out: dict[str, dict] = {}
    now_ts = datetime.now(timezone.utc).timestamp()
    for vid, plate, lat, lon, speed, route_id, pos_at, assignment_id in rows:
        if lat is None or lon is None:
            continue
        ts = pos_at.timestamp() if pos_at else now_ts
        out[str(vid)] = {
            "vehicle_id": vid,
            "plate_number": plate,
            "lat": lat,
            "lon": lon,
            "speed": speed or 0.0,
            "timestamp": ts,
            "route_id": route_id,
            "assignment_id": assignment_id,
        }
    return out


async def get_position(db: AsyncSession, vehicle_id: int) -> dict | None:
    active_assignment_id = (
        select(Assignment.id)
        .where(Assignment.vehicle_id == Vehicle.id, Assignment.status == "active")
        .order_by(Assignment.start_time.desc())
        .limit(1)
        .scalar_subquery()
    )
    result = await db.execute(
        select(
            Vehicle.id,
            Vehicle.plate_number,
            Vehicle.last_lat,
            Vehicle.last_lon,
            Vehicle.speed,
            Vehicle.route_id,
            Vehicle.position_updated_at,
            active_assignment_id.label("assignment_id"),
        ).where(Vehicle.id == vehicle_id)
    )
    row = result.first()
    if not row:
        return None
    vid, plate, lat, lon, speed, route_id, pos_at, assignment_id = row
    if lat is None or lon is None:
        return None
    ts = pos_at.timestamp() if pos_at else datetime.now(timezone.utc).timestamp()
    return {
        "vehicle_id": vid,
        "plate_number": plate,
        "lat": lat,
        "lon": lon,
        "speed": speed or 0.0,
        "timestamp": ts,
        "route_id": route_id,
        "assignment_id": assignment_id,
    }


async def update_position(
    db: AsyncSession,
    vehicle_id: int,
    lat: float,
    lon: float,
    speed: float = 0.0,
) -> None:
    vehicle = await db.get(Vehicle, vehicle_id)
    if not vehicle:
        return
    vehicle.last_lat = lat
    vehicle.last_lon = lon
    vehicle.speed = speed
    vehicle.position_updated_at = datetime.now(timezone.utc)
    await db.flush()


async def set_vehicle_route(
    db: AsyncSession,
    vehicle_id: int,
    route_id: int | None,
) -> Vehicle | None:
    """Assign or clear the corridor route used for telemetry validation."""
    vehicle = await get_vehicle_by_id(db, vehicle_id)
    if not vehicle:
        return None
    vehicle.route_id = route_id
    await db.flush()
    await db.refresh(vehicle, ["route"])
    return vehicle


async def create_vehicle(
    db: AsyncSession,
    plate_number: str,
    device_id: str,
    bus_type: str | None = None,
    capacity: int | None = None,
    is_active: bool = True,
) -> Vehicle:
    vehicle = Vehicle(
        plate_number=plate_number,
        device_id=device_id,
        bus_type=bus_type,
        capacity=capacity,
        is_active=is_active,
    )
    db.add(vehicle)
    await db.flush()
    await db.refresh(vehicle)
    return vehicle
