"""Vehicle CRUD operations."""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.assignment import Assignment
from app.models.vehicle import Vehicle
from app.utils.redis_client import get_redis, bus_live_key
from app.services.redis_cache import get_cv_result


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


async def get_vehicles(
    db: AsyncSession, skip: int = 0, limit: int = 100
) -> list[Vehicle]:
    result = await db.execute(
        select(Vehicle).options(selectinload(Vehicle.route)).offset(skip).limit(limit)
    )
    return list(result.scalars().all())


async def get_vehicle_with_positions(
    db: AsyncSession, vehicle_id: int
) -> Vehicle | None:
    return await get_vehicle_by_id(db, vehicle_id)


async def get_live_positions(db: AsyncSession) -> dict[str, dict]:
    """Positions keyed by vehicle id (string) for JSON stability.

    Only returns vehicles that have an active assignment — buses whose
    driver has not ended their journey are excluded so the mobile app
    sees only buses that are actually serving the route right now.
    """
    result = await db.execute(
        select(
            Vehicle.id,
            Vehicle.plate_number,
            Vehicle.last_lat,
            Vehicle.last_lon,
            Vehicle.speed,
            Vehicle.route_id,
            Vehicle.position_updated_at,
            Assignment.id.label("assignment_id"),
        )
        .join(Assignment, Assignment.vehicle_id == Vehicle.id)
        .where(Assignment.status == "active")
    )
    rows = result.all()
    out: dict[str, dict] = {}
    now_ts = datetime.now(UTC).timestamp()
    for vid, plate, lat, lon, speed, route_id, pos_at, assignment_id in rows:
        if lat is None or lon is None:
            continue
        ts = pos_at.timestamp() if pos_at else now_ts
        # try bus live hash first, then fallback to CV result hash
        occupancy: int | None = None
        try:
            client = await get_redis()
            raw = await client.hget(bus_live_key(plate), "occupancy_level")
            if raw is not None:
                occupancy = int(raw)
        except Exception:
            occupancy = None

        if occupancy is None:
            try:
                cv = await get_cv_result(plate)
                if cv is not None and "occupancy_level" in cv:
                    occupancy = int(cv.get("occupancy_level", 0))
            except Exception:
                occupancy = None

        if occupancy is None:
            occupancy = 0

        out[str(vid)] = {
            "vehicle_id": vid,
            "plate_number": plate,
            "lat": lat,
            "lon": lon,
            "speed": speed or 0.0,
            "timestamp": ts,
            "route_id": route_id,
            "assignment_id": assignment_id,
            "occupancy_level": occupancy,
            "last_updated": pos_at,
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
    ts = pos_at.timestamp() if pos_at else datetime.now(UTC).timestamp()
    occupancy: int | None = None
    try:
        client = await get_redis()
        raw = await client.hget(bus_live_key(plate), "occupancy_level")
        if raw is not None:
            occupancy = int(raw)
    except Exception:
        occupancy = None

    if occupancy is None:
        try:
            cv = await get_cv_result(plate)
            if cv is not None and "occupancy_level" in cv:
                occupancy = int(cv.get("occupancy_level", 0))
        except Exception:
            occupancy = None

    if occupancy is None:
        occupancy = 0

    return {
        "vehicle_id": vid,
        "plate_number": plate,
        "lat": lat,
        "lon": lon,
        "speed": speed or 0.0,
        "timestamp": ts,
        "route_id": route_id,
        "assignment_id": assignment_id,
        "occupancy_level": occupancy,
        "last_updated": pos_at,
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
    vehicle.position_updated_at = datetime.now(UTC)
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
