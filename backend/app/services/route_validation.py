"""On-route validation for bus telemetry."""

from app.models.stop import Stop
from app.utils.gps_validation import haversine_meters


def find_nearest_stop(lat: float, lon: float, stops: list[Stop]) -> Stop | None:
    """Find the nearest stop to given coordinates."""
    if not stops:
        return None
    return min(
        stops,
        key=lambda s: haversine_meters(lat, lon, s.lat, s.lon),
    )


def is_on_route(
    lat: float,
    lon: float,
    route_stops: list[Stop],
    max_off_route_m: float = 200.0,
) -> bool:
    """Check if the coordinate is reasonably close to any stop on the route."""
    if not route_stops:
        return True  # Cannot validate without route stops
    nearest = find_nearest_stop(lat, lon, route_stops)
    if nearest is None:
        return True
    dist = haversine_meters(lat, lon, nearest.lat, nearest.lon)
    return dist <= max_off_route_m
