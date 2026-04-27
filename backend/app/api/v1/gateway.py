"""Gateway endpoints for IoT devices with onboard camera support."""

from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud import vehicle as crud_vehicle
from app.db.session import get_db
from app.services.live_broadcast import broadcast_vehicle_position
from app.services.redis_cache import set_bus_live_pipeline

router = APIRouter(tags=["gateway"])


def _count_people_from_image(image_bytes: bytes) -> int:
    """Count dark blobs in a camera frame as a lightweight crowd proxy."""
    try:
        import cv2
        import numpy as np
    except ImportError:
        return 0

    image_array = np.frombuffer(image_bytes, np.uint8)
    frame = cv2.imdecode(image_array, cv2.IMREAD_COLOR)
    if frame is None:
        return 0

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    _, threshold = cv2.threshold(gray, 120, 255, cv2.THRESH_BINARY_INV)
    contours, _ = cv2.findContours(threshold, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    return sum(1 for contour in contours if cv2.contourArea(contour) >= 50)


def _occupancy_from_people_count(people_count: int, bus_capacity: int | None) -> int:
    if not bus_capacity or bus_capacity <= 0:
        return 0 if people_count == 0 else 1

    load_ratio = people_count / bus_capacity
    if load_ratio < 0.3:
        return 0
    if load_ratio < 0.7:
        return 1
    return 2


async def _save_raw_telemetry(
    vehicle_id: int,
    lat: float,
    lon: float,
    pixel_count: int | None,
    raw_payload: dict | None,
) -> None:
    from app.crud import tracking as crud_tracking
    from app.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        await crud_tracking.create_raw_telemetry(
            db, vehicle_id, lat, lon, pixel_count, raw_payload
        )
        await db.commit()


@router.post("/gateway/esp32/telemetry")
async def receive_esp32_telemetry(
    background_tasks: BackgroundTasks,
    device_id: str = Form(...),
    lat: float = Form(...),
    lon: float = Form(...),
    speed: float = Form(0.0),
    bus_capacity: int = Form(0),
    image: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """Receive multipart telemetry from an ESP32-CAM gateway."""
    vehicle = await crud_vehicle.get_vehicle_by_device_id(db, device_id)
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not registered")

    image_bytes = await image.read()
    people_count = _count_people_from_image(image_bytes)
    occupancy_level = _occupancy_from_people_count(people_count, bus_capacity or vehicle.capacity)

    raw_payload = {
        "source": "esp32_cam",
        "image_filename": image.filename,
        "bus_capacity": bus_capacity or vehicle.capacity,
        "cv": {
            "people_count": people_count,
            "is_crowded": occupancy_level == 2,
        },
    }

    background_tasks.add_task(
        _save_raw_telemetry,
        vehicle.id,
        lat,
        lon,
        people_count,
        raw_payload,
    )

    try:
        await set_bus_live_pipeline(
            vehicle.plate_number,
            lat,
            lon,
            occupancy_level,
            0,
        )
    except Exception:
        pass

    await crud_vehicle.update_position(db, vehicle.id, lat, lon, speed)

    ts = datetime.now(timezone.utc).timestamp()
    await broadcast_vehicle_position(
        vehicle.id,
        vehicle.plate_number,
        lat,
        lon,
        speed,
        vehicle.route_id,
        ts,
    )

    return {
        "status": "received",
        "vehicle_id": vehicle.id,
        "occupancy_level": occupancy_level,
        "cv": {
            "people_count": people_count,
            "is_crowded": occupancy_level == 2,
        },
    }
