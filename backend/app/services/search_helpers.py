"""Helpers for journey search and bus filtering."""

from __future__ import annotations

import time
from typing import Sequence

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
