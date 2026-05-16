"""Shared ML feature utilities for ETA models."""

from __future__ import annotations

from datetime import datetime

FEATURE_NAMES = [
    "route_id",
    "stop_id",
    "stop_sequence",
    "remaining_stops",
    "distance_m",
    "base_dwell_time",
    "peak_multiplier",
    "hour",
    "day_of_week",
    "is_peak_hour",
    "occupancy_level",
    "heuristic_eta",
]


def is_peak_hour(hour: int) -> int:
    """Return 1 if peak hour, else 0."""
    if 7 <= hour < 10:
        return 1
    if 16 <= hour < 20:
        return 1
    return 0


def time_features(ts: datetime | None) -> tuple[int, int, int]:
    """Return hour, day_of_week, is_peak_hour."""
    now = ts or datetime.now()
    hour = int(now.hour)
    dow = int(now.weekday())
    return hour, dow, is_peak_hour(hour)


def build_feature_dict(
    route_id: int,
    stop_id: int,
    stop_sequence: int,
    remaining_stops: int,
    distance_m: float,
    base_dwell_time: int,
    peak_multiplier: float,
    hour: int,
    day_of_week: int,
    is_peak: int,
    occupancy_level: int,
    heuristic_eta: float,
) -> dict[str, float]:
    """Return a feature dict aligned with FEATURE_NAMES."""
    return {
        "route_id": float(route_id),
        "stop_id": float(stop_id),
        "stop_sequence": float(stop_sequence),
        "remaining_stops": float(remaining_stops),
        "distance_m": float(distance_m),
        "base_dwell_time": float(base_dwell_time),
        "peak_multiplier": float(peak_multiplier),
        "hour": float(hour),
        "day_of_week": float(day_of_week),
        "is_peak_hour": float(is_peak),
        "occupancy_level": float(occupancy_level),
        "heuristic_eta": float(heuristic_eta),
    }


def build_feature_vector(features: dict[str, float]) -> list[float]:
    """Return ordered feature vector for model inference."""
    return [float(features.get(name, 0.0)) for name in FEATURE_NAMES]
