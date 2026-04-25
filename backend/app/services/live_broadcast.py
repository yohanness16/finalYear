"""Push live vehicle position updates to WebSocket subscribers (admin dashboard)."""

from __future__ import annotations

import time
from typing import Any


async def broadcast_vehicle_position(
    vehicle_id: int,
    plate_number: str,
    lat: float,
    lon: float,
    speed: float,
    route_id: int | None,
    timestamp: float | None = None,
) -> None:
    """Swallows errors so telemetry never fails if WebSocket layer has issues."""
    try:
        from app.services.websocket import manager

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
        await manager.broadcast(payload)
    except Exception:
        pass
