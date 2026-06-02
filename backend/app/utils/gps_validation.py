"""GPS outlier detection using last 5 points buffer."""

# Max plausible distance (meters) between consecutive pings for a moving bus
# ~100 km/h = ~28 m/s, so 5 sec interval = ~140m. Use 500m as safety margin.
MAX_PLAUSIBLE_DELTA_M = 500.0

# Re-export haversine_meters from the single source of truth (eta_calc)
from app.services.eta_calc import haversine_meters  # noqa: F401


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
        last["lat"],
        last["lon"],
        new_lat,
        new_lon,
    )
    return dist <= MAX_PLAUSIBLE_DELTA_M


def get_average_coord(
    coords: list[dict[str, float]],
) -> tuple[float, float] | None:
    """Return average lat/lon from list of coords (for fallback on outlier)."""
    if not coords:
        return None
    n = len(coords)
    lat_sum = sum(c["lat"] for c in coords)
    lon_sum = sum(c["lon"] for c in coords)
    return (lat_sum / n, lon_sum / n)
