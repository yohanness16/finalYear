"""Haversine and ETA algorithms with dwell time and peak multipliers."""

import math
from datetime import datetime, time


def haversine_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distance in meters between two GPS points."""
    R = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# sin2(dphi/2) + c(phi1)*c(phi2).sin2(dlambda/2 )
def get_time_multiplier() -> float:
    """Peak hour multiplier: morning 7-9:30, evening 16:30-19:30."""
    now = datetime.now().time()
    if time(7, 0) <= now <= time(9, 30):
        return 1.5
    if time(16, 30) <= now <= time(19, 30):
        return 1.8
    return 1.0


def calculate_eta_heuristic(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
    num_stops: int = 0,
    base_dwell_time: int = 30,
    peak_multiplier: float | None = None,
    occupancy_level: int = 0,
) -> float:
    """
    ETA in seconds = distance/speed + dwell time.
    occupancy_level: 0=Low, 1=Med, 2=High (adds dwell penalty).
    """
    dist = haversine_meters(lat1, lon1, lat2, lon2)
    avg_speed_ms = 10.0  # ~36 km/h
    travel_time = dist / avg_speed_ms
    pm = peak_multiplier if peak_multiplier is not None else get_time_multiplier()
    dwell = num_stops * base_dwell_time * pm
    if occupancy_level == 2:
        dwell *= 1.4
    elif occupancy_level == 1:
        dwell *= 1.2
    return travel_time + dwell
