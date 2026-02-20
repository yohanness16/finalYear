"""GPS outlier detection using last 5 points buffer."""

import math
from typing import Optional

# Max plausible distance (meters) between consecutive pings for a moving bus
# ~100 km/h = ~28 m/s, so 5 sec interval = ~140m. Use 500m as safety margin.
MAX_PLAUSIBLE_DELTA_M = 500.0


def haversine_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate distance in meters between two GPS points."""
    R = 6371000  # Earth radius in meters
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def is_valid_coord(
    new_lat: float,
    new_lon: float,
    last_coords: list[dict[str, float]],
) -> bool:
    """
    Check if new coordinate is plausible given last N points.
    Rejects GPS jumps (e.g., sudden 10km teleport).
    """
    if not last_coords:
        return True
    last = last_coords[0]
    dist = haversine_meters(
        last["lat"], last["lon"],
        new_lat, new_lon,
    )
    return dist <= MAX_PLAUSIBLE_DELTA_M


def get_average_coord(
    coords: list[dict[str, float]],
) -> Optional[tuple[float, float]]:
    """Return average lat/lon from list of coords (for fallback on outlier)."""
    if not coords:
        return None
    n = len(coords)
    lat_sum = sum(c["lat"] for c in coords)
    lon_sum = sum(c["lon"] for c in coords)
    return (lat_sum / n, lon_sum / n)
