"""Vehicle endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import RequireAdmin
from app.crud import vehicle as crud_vehicle
from app.db.session import get_db
from app.schemas.vehicle import VehicleCreate, VehicleResponse, VehicleUpdate

router = APIRouter()


@router.post("/vehicles", response_model=VehicleResponse)
async def register_vehicle(
    current_user: RequireAdmin,
    vehicle: VehicleCreate,
    db: AsyncSession = Depends(get_db),
    
):
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
    return v


@router.get("/vehicles", response_model=list[VehicleResponse])
async def list_vehicles(skip: int = 0, limit: int = 100, db: AsyncSession = Depends(get_db)):
    return await crud_vehicle.get_vehicles(db, skip, limit)


@router.get("/vehicles/{vehicle_id}", response_model=VehicleResponse)
async def get_vehicle(vehicle_id: int, db: AsyncSession = Depends(get_db)):
    v = await crud_vehicle.get_vehicle_by_id(db, vehicle_id)
    if not v:
        raise HTTPException(404, "Vehicle not found")
    return v
