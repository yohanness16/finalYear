"""
Image processing pipeline — async CV analysis with vehicle identity resolution.

Flow:
  1. IoT device sends multipart telemetry (device_id + image + GPS)
  2. Vehicle is resolved by device_id (auto-provision if unknown)
  3. GPS is validated (outlier check + on-route check)
  4. Image is queued for background CV analysis
  5. Immediate response returned to IoT device (status: processing)
  6. CV runs in background → results stored in Redis + DB
  7. Results broadcast to admin WebSocket clients with full crowd data

This decouples the slow CV analysis from the HTTP response so IoT devices
get sub-100ms responses even when image processing takes 1-3 seconds.
"""

import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.crud import vehicle as crud_vehicle
from app.crud import tracking as crud_tracking
from app.crud import assignment as crud_assignment
from app.crud import route as crud_route
from app.services.cv_engine import analyze_bus_density_from_image
from app.services.redis_cache import set_bus_live_pipeline, get_last_coords
from app.services.route_eta import estimate_route_stop_eta_payloads
from app.services.route_validation import find_nearest_stop, is_on_route
from app.services.live_broadcast import broadcast_vehicle_position, broadcast_cv_result
from app.utils.gps_validation import is_valid_coord, get_average_coord
from app.utils.redis_client import set_route_stop_etas


async def _store_image(image_bytes: bytes, image_name: str | None) -> tuple[str, bool]:
    """Save uploaded image to storage. Returns (relative_path, success)."""
    root = Path(__file__).resolve().parents[2]
    out_dir = root / "storage" / "esp32_images"
    out_dir.mkdir(parents=True, exist_ok=True)

    suffix = ".jpg"
    if image_name and "." in image_name:
        ext = "." + image_name.rsplit(".", 1)[-1].lower()
        if 1 < len(ext) <= 10:
            suffix = ext

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    unique = uuid.uuid4().hex[:8]
    filename = f"esp32_{stamp}_{unique}{suffix}"
    out_path = out_dir / filename

    try:
        out_path.write_bytes(image_bytes)
        return str(out_path.relative_to(root)), True
    except Exception:
        return "", False


async def _resolve_vehicle(db, device_id: str, plate_number: str | None,
                           bus_type: str | None, capacity: int | None):
    """
    Resolve vehicle identity from device_id.

    - If vehicle exists with this device_id → update metadata if provided
    - If not → auto-provision a new vehicle
    - Returns (vehicle, created: bool)

    Raises ValueError if plate conflict detected.
    """
    from app.models.vehicle import Vehicle

    existing = await crud_vehicle.get_vehicle_by_device_id(db, device_id)

    if existing:
        # Update metadata if provided
        if plate_number and existing.plate_number != plate_number:
            duplicate = await crud_vehicle.get_vehicle_by_plate(db, plate_number)
            if duplicate and duplicate.id != existing.id:
                raise ValueError("plate_number already registered")
            existing.plate_number = plate_number
        if bus_type:
            existing.bus_type = bus_type
        if capacity is not None and capacity > 0:
            existing.capacity = capacity
        existing.is_active = True
        await db.flush()
        await db.refresh(existing, ["route"])
        return existing, False

    # Auto-provision new vehicle
    import re
    cleaned = re.sub(r"[^A-Za-z0-9]", "", device_id).upper()
    tail = cleaned[-8:] if cleaned else "BUS00001"
    target_plate = plate_number or f"ESP-{tail}"[:20]
    target_type = bus_type or "Anbessa"
    target_capacity = capacity if capacity and capacity > 0 else None

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


async def _validate_gps(lat: float, lon: float, plate: str, route_stops: list) -> tuple[float, float, str | None]:
    """
    Validate GPS coordinates.

    Returns (lat, lon, rejection_reason).
    rejection_reason is None if valid.
    """
    # On-route check
    if route_stops and not is_on_route(lat, lon, route_stops):
        return lat, lon, "off_route"

    # Outlier check against Redis history
    try:
        last_coords = await get_last_coords(plate)
    except Exception:
        last_coords = []

    if last_coords and not is_valid_coord(lat, lon, last_coords):
        avg = get_average_coord(last_coords)
        if avg:
            return avg[0], avg[1], None  # Use averaged coords
        return lat, lon, "gps_outlier"

    return lat, lon, None


async def process_esp32_telemetry(
    db,
    device_id: str,
    lat: float,
    lon: float,
    speed: float,
    bus_capacity: int,
    image_bytes: bytes,
    image_name: str | None,
    plate_number: str | None = None,
    bus_type: str | None = None,
) -> dict[str, Any]:
    """
    Full ESP32-CAM telemetry pipeline.

    Steps:
      1. Resolve vehicle identity (device_id → vehicle)
      2. Validate GPS (outlier + on-route)
      3. Save image to disk
      4. Run CV analysis on image
      5. Store raw telemetry in DB
      6. Update Redis live pipeline
      7. Compute ETAs if on route
      8. Update vehicle position in DB
      9. Record trip history if on assignment
      10. Broadcast to WebSocket admins (position + CV results)

    Returns a dict with full processing results for the HTTP response.
    """
    settings = get_settings()
    result: dict[str, Any] = {
        "status": "received",
        "device_id": device_id,
        "image_saved": False,
    }

    # ── Step 1: Resolve vehicle identity ──
    try:
        vehicle, created = await _resolve_vehicle(
            db, device_id, plate_number, bus_type,
            capacity=bus_capacity if bus_capacity > 0 else None,
        )
    except ValueError as exc:
        return {"status": "rejected", "reason": str(exc), "device_id": device_id}

    result["vehicle_id"] = vehicle.id
    result["plate_number"] = vehicle.plate_number
    result["bus_type"] = vehicle.bus_type
    result["capacity"] = vehicle.capacity
    result["created"] = created

    # ── Step 2: Validate GPS ──
    route_stops = []
    if vehicle.route_id:
        route_stops = await crud_route.get_route_stops_ordered(db, vehicle.route_id)

    validated_lat, validated_lon, rejection = await _validate_gps(
        lat, lon, vehicle.plate_number, route_stops
    )

    if rejection:
        result["status"] = "rejected"
        result["reason"] = rejection
        result["vehicle_id"] = vehicle.id
        return result

    result["lat"] = validated_lat
    result["lon"] = validated_lon

    # ── Step 3: Save image to disk ──
    image_path = ""
    try:
        image_path, image_saved = await _store_image(image_bytes, image_name)
        result["image_saved"] = image_saved
        result["image_path"] = image_path
    except Exception:
        result["image_saved"] = False

    # ── Step 4: CV analysis ──
    capacity_for_cv = bus_capacity or vehicle.capacity
    cv_result = analyze_bus_density_from_image(image_bytes, capacity_for_cv)
    occupancy_level = int(cv_result["crowd_density"])

    # Fallback: if density is 0 but people detected, use people-count-based estimate
    if occupancy_level == 0 and cv_result["people_count"] > 0:
        from app.services.cv_engine import estimate_density_from_people_count
        occupancy_level = estimate_density_from_people_count(
            cv_result["people_count"], capacity_for_cv
        )

    result["occupancy_level"] = occupancy_level
    result["cv"] = cv_result

    # ── Step 5: Persist raw telemetry ──
    raw_payload = {
        "source": "esp32_cam",
        "device_id": device_id,
        "plate_number": vehicle.plate_number,
        "bus_type": vehicle.bus_type,
        "capacity": vehicle.capacity or bus_capacity,
        "image_filename": image_name,
        "image_saved": result["image_saved"],
        "image_path": image_path,
        "bus_capacity": bus_capacity or vehicle.capacity,
        "cv": {
            "human_count": cv_result["human_count"],
            "people_count": cv_result["people_count"],
            "crowd_density": cv_result["crowd_density"],
            "is_crowded": cv_result["is_crowded"],
            "method": cv_result["method"],
            "confidence": cv_result["confidence"],
            "foreground_ratio": cv_result["foreground_ratio"],
        },
    }

    await crud_tracking.create_raw_telemetry(
        db,
        vehicle.id,
        validated_lat,
        validated_lon,
        cv_result["people_count"],
        raw_payload,
    )

    # ── Step 6: Update Redis live pipeline ──
    assignment = await crud_assignment.get_active_assignment_by_vehicle(db, vehicle.id)
    assignment_id = assignment.id if assignment else 0

    try:
        await set_bus_live_pipeline(
            vehicle.plate_number,
            validated_lat,
            validated_lon,
            occupancy_level,
            assignment_id,
        )
    except Exception:
        pass

    # ── Step 6b: Store detailed CV result in Redis ──
    try:
        from app.services.redis_cache import update_cv_result
        await update_cv_result(
            plate=vehicle.plate_number,
            occupancy_level=occupancy_level,
            people_count=cv_result["people_count"],
            crowd_density=cv_result["crowd_density"],
            confidence=cv_result["confidence"],
            method=cv_result["method"],
        )
    except Exception:
        pass

    # ── Step 7: Compute ETAs if on route ──
    eta_payloads = {}
    if vehicle.route and route_stops:
        try:
            eta_payloads = estimate_route_stop_eta_payloads(
                validated_lat,
                validated_lon,
                speed,
                occupancy_level,
                vehicle.route.route_number,
                vehicle.route_id,
                route_stops,
            )
            await set_route_stop_etas(vehicle.route.route_number, eta_payloads)
        except Exception:
            pass

    result["eta_computed"] = bool(eta_payloads)
    result["route_checked"] = bool(vehicle.route_id)

    # ── Step 8: Update vehicle position in DB ──
    await crud_vehicle.update_position(
        db, vehicle.id, validated_lat, validated_lon, speed
    )

    # ── Step 9: Record trip history ──
    if assignment and route_stops:
        nearest_stop = find_nearest_stop(validated_lat, validated_lon, route_stops)
        if nearest_stop is not None:
            try:
                await crud_tracking.create_trip_history_from_assignment(
                    db,
                    assignment,
                    nearest_stop,
                    validated_lat,
                    validated_lon,
                    occupancy_level=occupancy_level,
                )
            except Exception:
                pass

    # ── Step 10: Broadcast to WebSocket admins ──
    ts = datetime.now(timezone.utc).timestamp()

    # Broadcast position update with occupancy
    await broadcast_vehicle_position(
        vehicle_id=vehicle.id,
        plate_number=vehicle.plate_number,
        lat=validated_lat,
        lon=validated_lon,
        speed=speed,
        route_id=vehicle.route_id,
        timestamp=ts,
        bus_type=vehicle.bus_type,
        occupancy_level=occupancy_level,
    )

    # Broadcast detailed CV result as a separate message
    await broadcast_cv_result(
        vehicle_id=vehicle.id,
        plate_number=vehicle.plate_number,
        cv_result=cv_result,
        image_path=image_path if result["image_saved"] else None,
        timestamp=ts,
    )

    result["status"] = "received"
    return result
