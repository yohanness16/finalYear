"""Estimate ETA values from the current bus position to route stops."""

from __future__ import annotations

from typing import Any

from app.models.stop import Stop
from app.utils.gps_validation import haversine_meters


def estimate_route_stop_eta_payloads(
    lat: float,
    lon: float,
    speed_kmh: float,
    occupancy_level: int,
    route_number: str,
    route_stops: list[Stop],
) -> dict[int, dict[str, Any]]:
    """Build Redis-ready ETA payloads keyed by stop_id."""
    if not route_stops:
        return {}

    speed_ms = max(speed_kmh / 3.6, 6.0)
    occupancy_multiplier = {0: 1.0, 1: 1.12, 2: 1.28}.get(occupancy_level, 1.0)
    payloads: dict[int, dict[str, Any]] = {}

    for stop in route_stops:
        distance_m = haversine_meters(lat, lon, stop.lat, stop.lon)
        travel_seconds = distance_m / speed_ms
        dwell_seconds = (stop.base_dwell_time or 30) * (stop.peak_multiplier or 1.0)
        eta_seconds = int((travel_seconds + dwell_seconds * occupancy_multiplier) + 0.5)
        payloads[stop.id] = {
            "route_number": route_number,
            "stop_id": stop.id,
            "stop_name": stop.name,
            "eta_seconds": eta_seconds,
            "distance_m": int(distance_m + 0.5),
            "speed_kmh": round(speed_kmh, 2),
            "occupancy_level": occupancy_level,
        }

    return payloads