"""Push live vehicle position and CV updates to WebSocket subscribers (admin dashboard)."""

from __future__ import annotations

import logging
import time
from typing import Any

from app.services.websocket import manager

logger = logging.getLogger(__name__)


async def broadcast_vehicle_position(
    vehicle_id: int,
    plate_number: str,
    lat: float,
    lon: float,
    speed: float,
    route_id: int | None,
    timestamp: float | None = None,
    bus_type: str | None = None,
    occupancy_level: int | None = None,
    eta_payloads: dict[int, dict[str, Any]] | None = None,
) -> None:
    """
    Broadcast vehicle position update to all admin WebSocket clients.

    Includes occupancy_level from CV analysis so the admin dashboard
    can show crowd density alongside position on the live map.

    When eta_payloads is provided (computed from route_eta.py), each
    entry keyed by stop_id carries stop_name, eta_seconds, distance_m,
    and computed_at so frontends can render live ETA countdowns.
    """
    try:
        ts = timestamp if timestamp is not None else time.time()
        payload: dict[str, Any] = {
            "type": "vehicle_position",
            "vehicle_id": vehicle_id,
            "plate_number": plate_number,
            "lat": lat,
            "lon": lon,
            "speed": speed,
            "route_id": route_id,
            "timestamp": ts,
        }
        if bus_type is not None:
            payload["bus_type"] = bus_type
        if occupancy_level is not None:
            payload["occupancy_level"] = occupancy_level
            payload["density_level"] = occupancy_level
        if eta_payloads is not None:
            payload["eta_payloads"] = {
                str(stop_id): {
                    "stop_name": data.get("stop_name", ""),
                    "eta_seconds": data.get("eta_seconds", 0),
                    "distance_m": data.get("distance_m", 0),
                    "computed_at": data.get("computed_at", 0),
                }
                for stop_id, data in eta_payloads.items()
            }
        await manager.broadcast(payload)
    except Exception:
        logger.warning(
            "broadcast_vehicle_position failed for %s", plate_number,
            exc_info=True,
        )


async def broadcast_cv_result(
    vehicle_id: int,
    plate_number: str,
    cv_result: dict[str, Any],
    image_path: str | None = None,
    timestamp: float | None = None,
) -> None:
    """
    Broadcast detailed CV analysis result to all admin WebSocket clients.

    This is a separate message type from vehicle_position so the admin
    dashboard can update the crowd density panel, show people count,
    confidence score, and method used.
    """
    try:
        ts = timestamp if timestamp is not None else time.time()
        payload: dict[str, Any] = {
            "type": "cv_result",
            "vehicle_id": vehicle_id,
            "plate_number": plate_number,
            "timestamp": ts,
            "cv": {
                "people_count": cv_result.get("people_count", 0),
                "crowd_density": cv_result.get("crowd_density", 0),
                "is_crowded": cv_result.get("is_crowded", False),
                "method": cv_result.get("method", "unknown"),
                "confidence": cv_result.get("confidence", 0.0),
                "foreground_ratio": cv_result.get("foreground_ratio", 0.0),
            },
        }
        if image_path is not None:
            payload["image_path"] = image_path
        await manager.broadcast(payload)
    except Exception:
        logger.warning(
            "broadcast_cv_result failed for %s", plate_number,
            exc_info=True,
        )
