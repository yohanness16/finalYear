"""Telemetry ingestion and live tracking endpoints."""

from datetime import UTC

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.limiter import limiter
from app.crud import assignment as crud_assignment
from app.crud import tracking as crud_tracking
from app.crud import vehicle as crud_vehicle
from app.db.session import get_db
from app.schemas.tracking import TelemetryInput
from app.services.cv_engine import estimate_density
from app.services.redis_cache import (
    get_last_coords,
    get_route_stops,
    set_bus_live_pipeline,
)
from app.services.route_eta import estimate_route_stop_eta_payloads
from app.services.route_validation import find_nearest_stop, is_on_route
from app.utils.gps_validation import get_average_coord, is_valid_coord
from app.utils.redis_client import set_route_stop_etas

router = APIRouter()


async def _save_raw_telemetry(
    vehicle_id: int,
    lat: float,
    lon: float,
    pixel_count: int | None,
    raw_payload: dict | None,
) -> None:
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
        raise HTTPException(status_code=404, detail="Vehicle not registered")

    route_stops = []
    if vehicle.route_id:
        route_stops = await get_route_stops(db, vehicle.route_id)
        if not is_on_route(data.lat, data.lon, route_stops):
            return {
                "status": "rejected",
                "reason": "off_route",
                "route_id": vehicle.route_id,
            }

    try:
        last_coords = await get_last_coords(vehicle.plate_number)
    except Exception:
        last_coords = []
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

    try:
        await set_bus_live_pipeline(
            vehicle.plate_number,
            data.lat,
            data.lon,
            occupancy,
            assignment.id if assignment else 0,
        )
    except Exception:
        pass

    if vehicle.route and route_stops:
        stop_payloads = estimate_route_stop_eta_payloads(
            data.lat,
            data.lon,
            data.speed or 0.0,
            occupancy,
            vehicle.route.route_number,
            vehicle.route_id,
            route_stops,
        )
        try:
            await set_route_stop_etas(vehicle.route.route_number, stop_payloads)
        except Exception:
            pass

    await crud_vehicle.update_position(
        db, vehicle.id, data.lat, data.lon, data.speed or 0.0
    )

    if assignment and route_stops:
        nearest_stop = find_nearest_stop(data.lat, data.lon, route_stops)
        if nearest_stop is not None:
            try:
                await crud_tracking.create_trip_history_from_assignment(
                    db,
                    assignment,
                    nearest_stop,
                    data.lat,
                    data.lon,
                    occupancy_level=occupancy,
                )
            except Exception:
                pass

    from datetime import datetime

    from app.services.live_broadcast import broadcast_vehicle_position

    ts = datetime.now(UTC).timestamp()
    await broadcast_vehicle_position(
        vehicle_id=vehicle.id,
        plate_number=vehicle.plate_number,
        lat=data.lat,
        lon=data.lon,
        speed=data.speed or 0.0,
        route_id=vehicle.route_id,
        timestamp=ts,
        occupancy_level=occupancy,
    )

    return {
        "status": "received",
        "vehicle_id": vehicle.id,
        "occupancy_level": occupancy,
        "route_checked": bool(vehicle.route_id),
    }
