"""Gateway endpoints for IoT devices with onboard camera support."""

import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud import vehicle as crud_vehicle
from app.db.session import get_db
from app.services.cv_engine import count_people_from_image, estimate_density_from_people_count
from app.services.live_broadcast import broadcast_vehicle_position
from app.services.redis_cache import set_bus_live_pipeline

router = APIRouter(tags=["gateway"])


def _default_plate_from_device_id(device_id: str) -> str:
    """Build a deterministic, unique-looking fallback plate for auto-provisioned ESP buses."""
    cleaned = re.sub(r"[^A-Za-z0-9]", "", device_id).upper()
    tail = (cleaned[-8:] if cleaned else "BUS00001")
    return f"ESP-{tail}"[:20]


def _store_test_image(image_bytes: bytes, image_name: str | None) -> str:
    """Save uploaded camera frame for debugging and return relative path."""
    root = Path(__file__).resolve().parents[3]
    out_dir = root / "storage" / "esp32_images"
    out_dir.mkdir(parents=True, exist_ok=True)

    suffix = ".jpg"
    if image_name and "." in image_name:
        ext = "." + image_name.rsplit(".", 1)[-1].lower()
        if 1 < len(ext) <= 10:
            suffix = ext

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    filename = f"esp32_{stamp}_{uuid4().hex[:8]}{suffix}"
    out_path = out_dir / filename
    out_path.write_bytes(image_bytes)

    return str(out_path.relative_to(root))


def _occupancy_from_people_count(people_count: int, bus_capacity: int | None) -> int:
    return estimate_density_from_people_count(people_count, bus_capacity)


async def _save_raw_telemetry(
    db: AsyncSession,
    vehicle_id: int,
    lat: float,
    lon: float,
    pixel_count: int | None,
    raw_payload: dict | None,
) -> None:
    from app.crud import tracking as crud_tracking

    await crud_tracking.create_raw_telemetry(
        db, vehicle_id, lat, lon, pixel_count, raw_payload
    )


@router.post("/gateway/esp32/telemetry")
async def receive_esp32_telemetry(
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
        vehicle = await crud_vehicle.create_vehicle(
            db,
            plate_number=_default_plate_from_device_id(device_id),
            device_id=device_id,
            bus_type="ESP32-CAM",
            capacity=bus_capacity or None,
            is_active=True,
        )

    image_bytes = await image.read()
    people_count = count_people_from_image(image_bytes)
    if (vehicle.capacity is None or vehicle.capacity <= 0) and bus_capacity > 0:
        vehicle.capacity = bus_capacity
        await db.flush()

    occupancy_level = _occupancy_from_people_count(
        people_count,
        bus_capacity or vehicle.capacity,
    )

    image_saved = False
    image_path = ""
    try:
        image_path = _store_test_image(image_bytes, image.filename)
        image_saved = True
    except Exception:
        image_saved = False

    raw_payload = {
        "source": "esp32_cam",
        "image_filename": image.filename,
        "image_saved": image_saved,
        "image_path": image_path,
        "bus_capacity": bus_capacity or vehicle.capacity,
        "cv": {
            "human_count": people_count,
            "people_count": people_count,
            "crowd_density": occupancy_level,
            "is_crowded": occupancy_level == 2,
        },
    }

    await _save_raw_telemetry(
        db,
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
        "image_saved": image_saved,
        "image_path": image_path,
        "cv": {
            "human_count": people_count,
            "people_count": people_count,
            "crowd_density": occupancy_level,
            "is_crowded": occupancy_level == 2,
        },
    }
