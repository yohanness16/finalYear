"""Gateway endpoints for IoT devices with onboard camera support."""

import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud import vehicle as crud_vehicle
from app.db.session import get_db
from app.services.cv_engine import analyze_bus_density_from_image, estimate_density_from_people_count
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


async def _upsert_bus_for_device(
    db: AsyncSession,
    device_id: str,
    plate_number: str | None,
    bus_type: str | None,
    capacity: int | None,
) -> tuple["Vehicle", bool]:
    """Create or update a bus record from ESP telemetry metadata."""
    from app.models.vehicle import Vehicle

    existing = await crud_vehicle.get_vehicle_by_device_id(db, device_id)
    target_plate = plate_number or _default_plate_from_device_id(device_id)
    target_type = bus_type or "Anbessa"
    target_capacity = capacity if capacity and capacity > 0 else None

    if existing:
        if plate_number and existing.plate_number != plate_number:
            duplicate = await crud_vehicle.get_vehicle_by_plate(db, plate_number)
            if duplicate and duplicate.id != existing.id:
                raise ValueError("plate_number already registered")
            existing.plate_number = plate_number
        if bus_type:
            existing.bus_type = bus_type
        if target_capacity is not None:
            existing.capacity = target_capacity
        existing.is_active = True
        await db.flush()
        await db.refresh(existing, ["route"])
        return existing, False

    if await crud_vehicle.get_vehicle_by_plate(db, target_plate):
        raise ValueError("plate_number already registered")

    vehicle = await crud_vehicle.create_vehicle(
        db,
        plate_number=target_plate,
        device_id=device_id,
        bus_type=target_type,
        capacity=target_capacity,
        is_active=True,
    )
    await db.refresh(vehicle, ["route"])
    return vehicle, True


@router.post("/gateway/esp32/telemetry")
async def receive_esp32_telemetry(
    device_id: str = Form(...),
    plate_number: str | None = Form(None),
    bus_type: str | None = Form(None),
    lat: float = Form(...),
    lon: float = Form(...),
    speed: float = Form(0.0),
    bus_capacity: int = Form(0),
    image: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """Receive multipart telemetry from an ESP32-CAM gateway."""
    try:
        vehicle, created = await _upsert_bus_for_device(
            db,
            device_id,
            plate_number,
            bus_type,
            bus_capacity,
        )
    except ValueError as exc:
        return {"status": "rejected", "reason": str(exc)}

    image_bytes = await image.read()
    analysis = analyze_bus_density_from_image(image_bytes, bus_capacity or None)
    people_count = int(analysis["people_count"])
    if (vehicle.capacity is None or vehicle.capacity <= 0) and bus_capacity > 0:
        vehicle.capacity = bus_capacity
        await db.flush()

    occupancy_level = int(analysis["crowd_density"])
    capacity_for_analysis = bus_capacity or vehicle.capacity
    if occupancy_level == 0 and people_count > 0:
        occupancy_level = _occupancy_from_people_count(people_count, capacity_for_analysis)

    image_saved = False
    image_path = ""
    try:
        image_path = _store_test_image(image_bytes, image.filename)
        image_saved = True
    except Exception:
        image_saved = False

    raw_payload = {
        "source": "esp32_cam",
        "device_id": device_id,
        "plate_number": vehicle.plate_number,
        "bus_type": vehicle.bus_type,
        "capacity": vehicle.capacity or bus_capacity,
        "image_filename": image.filename,
        "image_saved": image_saved,
        "image_path": image_path,
        "bus_capacity": bus_capacity or vehicle.capacity,
        "cv": {
            "human_count": people_count,
            "people_count": people_count,
            "crowd_density": occupancy_level,
            "is_crowded": occupancy_level == 2,
            "method": analysis["method"],
            "confidence": analysis["confidence"],
            "foreground_ratio": analysis["foreground_ratio"],
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
        bus_type=vehicle.bus_type,
        image_path=image_path if image_saved else None,
    )

    return {
        "status": "received",
        "vehicle_id": vehicle.id,
        "plate_number": vehicle.plate_number,
        "bus_type": vehicle.bus_type,
        "capacity": vehicle.capacity,
        "created": created,
        "occupancy_level": occupancy_level,
        "image_saved": image_saved,
        "image_path": image_path,
        "cv": {
            "human_count": people_count,
            "people_count": people_count,
            "crowd_density": occupancy_level,
            "is_crowded": occupancy_level == 2,
            "method": analysis["method"],
            "confidence": analysis["confidence"],
            "foreground_ratio": analysis["foreground_ratio"],
        },
    }
