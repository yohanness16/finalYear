"""Helpers for journey search and bus filtering."""

from __future__ import annotations

import time
from collections.abc import Sequence

from app.models.stop import Stop
from app.utils.gps_validation import haversine_meters


def nearest_stop_index(lat: float, lon: float, stops: Sequence[Stop]) -> int:
    """Return index of nearest stop in the given ordered list."""
    if not stops:
        return 0
    nearest_idx = 0
    nearest_dist = None
    for idx, stop in enumerate(stops):
        dist = haversine_meters(lat, lon, stop.lat, stop.lon)
        if nearest_dist is None or dist < nearest_dist:
            nearest_dist = dist
            nearest_idx = idx
    return nearest_idx


def compute_live_eta(eta_seconds: float | int, computed_at: float | int) -> int | None:
    """Return live ETA seconds adjusted by elapsed time."""
    try:
        eta = float(eta_seconds)
        ts = float(computed_at)
    except (TypeError, ValueError):
        return None
    if ts <= 0:
        return None
    elapsed = max(0.0, time.time() - ts)
    return max(0, int(round(eta - elapsed)))


def infer_bus_direction(
    coords: Sequence[dict[str, float]], stops: Sequence[Stop]
) -> int | None:
    """Infer direction from recent coords: 1 forward, -1 reverse, None unknown."""
    if len(coords) < 2 or not stops:
        return None

    curr = coords[0]
    prev = coords[1]
    try:
        curr_idx = nearest_stop_index(float(curr["lat"]), float(curr["lon"]), stops)
        prev_idx = nearest_stop_index(float(prev["lat"]), float(prev["lon"]), stops)
    except (KeyError, TypeError, ValueError):
        return None

    if curr_idx != prev_idx:
        return 1 if curr_idx > prev_idx else -1

    if curr_idx < len(stops) - 1:
        next_stop = stops[curr_idx + 1]
        curr_next = haversine_meters(
            float(curr["lat"]), float(curr["lon"]), next_stop.lat, next_stop.lon
        )
        prev_next = haversine_meters(
            float(prev["lat"]), float(prev["lon"]), next_stop.lat, next_stop.lon
        )
        if curr_next < prev_next:
            return 1

    if curr_idx > 0:
        prev_stop = stops[curr_idx - 1]
        curr_prev = haversine_meters(
            float(curr["lat"]), float(curr["lon"]), prev_stop.lat, prev_stop.lon
        )
        prev_prev = haversine_meters(
            float(prev["lat"]), float(prev["lon"]), prev_stop.lat, prev_stop.lon
        )
        if curr_prev < prev_prev:
            return -1

    return None
