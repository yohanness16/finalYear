"""Telemetry ingestion and live tracking endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.limiter import limiter
from app.crud import vehicle as crud_vehicle
from app.db.session import get_db
from app.schemas.tracking import TelemetryInput
from app.services.telemetry_ingest import process_telemetry
from app.utils.occupancy import resolve_occupancy_level

router = APIRouter()


@router.post("/telemetry")
@limiter.limit("300/minute")
async def receive_telemetry(
    request: Request,
    data: TelemetryInput,
    db: AsyncSession = Depends(get_db),
):
    """Receive GPS + density data from SIM7600/other devices.

    Returns immediately after delegating to the unified process_telemetry()
    service which handles: vehicle resolution, GPS validation, Redis update,
    ETA computation, trip history, and WebSocket broadcast.
    """
    # Check vehicle exists (the legacy endpoint requires pre-registration,
    # unlike gateway/tracking which auto-provision)
    vehicle = await crud_vehicle.get_vehicle_by_device_id(db, data.device_id)
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not registered")

    occupancy = resolve_occupancy_level(data.pixel_count, data.raw_payload)

    result = await process_telemetry(
        db=db,
        device_id=data.device_id,
        lat=data.lat,
        lon=data.lon,
        speed=data.speed or 0.0,
        occupancy_level=occupancy,
        compute_eta=True,
        persist_raw=True,
    )

    return result
