"""Shared GPS helpers for bus simulation."""

import math
import random


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two WGS84 points in meters."""
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def interpolate_gps(lat1, lon1, lat2, lon2, steps: int):
    """Generate smooth GPS points between two coordinates."""
    points = []
    for i in range(steps + 1):
        t = i / steps
        jitter_lat = random.gauss(0, 0.00008)
        jitter_lon = random.gauss(0, 0.00008)
        points.append(
            (
                lat1 + (lat2 - lat1) * t + jitter_lat,
                lon1 + (lon2 - lon1) * t + jitter_lon,
            )
        )
    return points
