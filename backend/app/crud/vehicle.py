"""Vehicle CRUD operations."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.vehicle import Vehicle


async def get_vehicle_by_id(db: AsyncSession, vehicle_id: int) -> Vehicle | None:
    result = await db.execute(select(Vehicle).where(Vehicle.id == vehicle_id))
    return result.scalar_one_or_none()


async def get_vehicle_by_device_id(db: AsyncSession, device_id: str) -> Vehicle | None:
    result = await db.execute(select(Vehicle).where(Vehicle.device_id == device_id))
    return result.scalar_one_or_none()


async def get_vehicle_by_plate(db: AsyncSession, plate_number: str) -> Vehicle | None:
    result = await db.execute(select(Vehicle).where(Vehicle.plate_number == plate_number))
    return result.scalar_one_or_none()


async def get_vehicles(db: AsyncSession, skip: int = 0, limit: int = 100) -> list[Vehicle]:
    result = await db.execute(select(Vehicle).offset(skip).limit(limit))
    return list(result.scalars().all())


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
