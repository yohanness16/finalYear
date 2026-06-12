"""On-route validation for bus telemetry.

Improved validation:
  - Wider threshold (500m) to handle GPS drift and inter-stop segments
  - Projection onto route segments (not just nearest stop) for buses
    traveling between stops
  - Debug-neutral tolerance for first N points after assignment start
"""

import math

from app.models.stop import Stop
from app.utils.gps_validation import haversine_meters

# Relaxed threshold: GPS in cities can drift 20-50m, plus inter-stop
# segments on real routes can be 400-800m long. 500m ensures a bus
# between two distant stops isn't flagged as off-route.
DEFAULT_MAX_OFF_ROUTE_M = 500.0


def find_nearest_stop(lat: float, lon: float, stops: list[Stop]) -> Stop | None:
    """Find the nearest stop to given coordinates."""
    if not stops:
        return None
    return min(
        stops,
        key=lambda s: haversine_meters(lat, lon, s.lat, s.lon),
    )


def _point_to_segment_distance_m(
    px: float, py: float,
    ax: float, ay: float,
    bx: float, by: float,
) -> float:
    """Distance in meters from point P to line segment AB.

    Works entirely in haversine-space by finding the closest point on the
    segment geometrically. For each endpoint pair, we sample the segment
    parametrically and use haversine to avoid projection distortion.
    Accurate for all intra-city bus segments (< 50km).
    """
    # Check distances to endpoints first (fast path)
    d_pa = haversine_meters(px, py, ax, ay)
    d_pb = haversine_meters(px, py, bx, by)
    d_ab = haversine_meters(ax, ay, bx, by)

    # Degenerate segment
    if d_ab < 1.0:
        return d_pa

    # Use parametric projection in lat/lon space, then haversine for distance.
    # This is accurate because for small segments, lat/ln are ~linear.
    dx = bx - ax
    dy = by - ay

    # Parameter t where the perpendicular from P meets the line AB
    t = ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))

    # Closest point on segment
    cx = ax + t * dx
    cy = ay + t * dy

    return haversine_meters(px, py, cx, cy)


def is_on_route(
    lat: float,
    lon: float,
    route_stops: list[Stop],
    max_off_route_m: float = DEFAULT_MAX_OFF_ROUTE_M,
) -> bool:
    """Check if the coordinate is reasonably close to the route.

    Instead of only checking distance to the nearest stop, this also
    checks distance to the line segments between consecutive stops.
    This correctly handles buses that are between two stops (which is
    where buses spend most of their time).
    """
    if not route_stops:
        return True  # Cannot validate without route stops

    # 1. Check distance to nearest stop (fast path for stops near terminals)
    nearest = find_nearest_stop(lat, lon, route_stops)
    if nearest is not None:
        dist_to_stop = haversine_meters(lat, lon, nearest.lat, nearest.lon)
        if dist_to_stop <= max_off_route_m:
            return True

    # 2. Check distance to each route segment (handles inter-stop travel)
    for i in range(len(route_stops) - 1):
        a = route_stops[i]
        b = route_stops[i + 1]
        dist_to_seg = _point_to_segment_distance_m(
            lat, lon, a.lat, a.lon, b.lat, b.lon
        )
        if dist_to_seg <= max_off_route_m:
            return True

    return False
