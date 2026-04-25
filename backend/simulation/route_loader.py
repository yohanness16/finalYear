"""Load ordered stop lists from the API (source of truth for geometry)."""

from typing import Any

from api_client import APIClient


def stops_from_route_detail(route_json: dict[str, Any]) -> list[dict[str, Any]]:
    """Build simulator stop dicts from GET /routes/{id} (RouteWithStops)."""
    raw = route_json.get("stops") or []
    out: list[dict[str, Any]] = []
    for s in raw:
        out.append(
            {
                "name": s["name"],
                "id": s.get("id"),
                "lat": float(s["lat"]),
                "lon": float(s["lon"]),
                "dwell": int(s.get("base_dwell_time", 30)),
                "is_terminal": bool(s.get("is_terminal", False)),
            }
        )
    return out


def fetch_route_stops(client: APIClient, route_id: int) -> list[dict[str, Any]] | None:
    """GET /routes/{route_id}; returns None on failure."""
    data = client.get(f"/routes/{route_id}")
    if not data or not isinstance(data, dict):
        return None
    stops = stops_from_route_detail(data)
    return stops if stops else None
