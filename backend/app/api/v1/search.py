"""Point-to-point search and journey planning."""

import time

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.crud import route as crud_route
from app.crud import vehicle as crud_vehicle
from app.db.session import get_db
from app.schemas.tracking import GeoJourneySearch, PointToPointSearch
from app.services.geocoding import geocode_text
from app.services.redis_cache import get_last_coords as get_recent_coords
from app.services.route_eta import estimate_route_stop_eta_payloads
from app.services.search_helpers import (
    compute_live_eta,
    infer_bus_direction,
    nearest_stop_index,
)
from app.utils.gps_validation import haversine_meters
from app.utils.redis_client import bus_live_key, get_redis

router = APIRouter()


async def _resolve_point(
    label: str, query: str | None, lat: float | None, lon: float | None
) -> dict:
    if lat is not None and lon is not None:
        return {
            "lat": float(lat),
            "lon": float(lon),
            "provider": "coords",
            "label": label,
        }
    if query:
        resolved = await geocode_text(query)
        if resolved:
            return resolved
    raise HTTPException(400, f"{label} location could not be resolved")


@router.post("/search/point-to-point")
async def point_to_point_search(
    body: PointToPointSearch,
    db: AsyncSession = Depends(get_db),
):
    """
    Find routes passing through start and end stops.
    Returns routes with pre-calculated bus ETAs and matching live buses.
    """
    start = await crud_route.get_stop_by_id(db, body.start_stop_id)
    end = await crud_route.get_stop_by_id(db, body.end_stop_id)
    if not start or not end:
        raise HTTPException(404, "Stop not found")
    routes = await crud_route.get_routes_through_stops(
        db, body.start_stop_id, body.end_stop_id
    )
    redis = None
    try:
        redis = await get_redis()
    except Exception:
        redis = None

    live_positions: dict[str, dict] = {}
    try:
        live_positions = await crud_vehicle.get_live_positions(db)
    except Exception:
        live_positions = {}

    results = []
    for route in routes:
        key = f"route:{route.route_number}:stop:{body.start_stop_id}"
        data = {}
        if redis is not None:
            try:
                data = await redis.hgetall(key)
            except Exception:
                data = {}
        if data:
            live_eta = compute_live_eta(
                data.get("eta_seconds", 0), data.get("computed_at", 0)
            )
            if live_eta is not None:
                data["eta_live_seconds"] = live_eta

        route_buses = [
            bus for bus in live_positions.values() if bus.get("route_id") == route.id
        ]

        entry: dict = {
            "route_number": route.route_number,
            "etas": data if data else {},
            "buses": route_buses,
        }
        results.append(entry)
    return {"routes": results, "start_stop": start.name, "end_stop": end.name}


@router.post("/search/journey")
async def journey_search(
    body: GeoJourneySearch,
    db: AsyncSession = Depends(get_db),
):
    """Search routes and live buses using user-provided locations."""
    settings = get_settings()
    max_age_seconds = int(settings.LIVE_POSITION_MAX_AGE_SECONDS or 0)

    start_point = await _resolve_point(
        "start", body.start_query, body.start_lat, body.start_lon
    )
    end_point = await _resolve_point("end", body.end_query, body.end_lat, body.end_lon)

    start_stop = await crud_route.get_nearest_stop(
        db, start_point["lat"], start_point["lon"]
    )
    end_stop = await crud_route.get_nearest_stop(db, end_point["lat"], end_point["lon"])
    if not start_stop or not end_stop:
        raise HTTPException(404, "No stops found near the provided locations")

    routes = await crud_route.get_routes_through_stops(db, start_stop.id, end_stop.id)
    if body.max_routes:
        routes = routes[: max(1, int(body.max_routes))]

    redis = None
    try:
        redis = await get_redis()
    except Exception:
        redis = None

    live_positions = await crud_vehicle.get_live_positions(db)
    buses = list(live_positions.values())

    now_ts = time.time()
    response_routes = []
    for route in routes:
        route_stops = await crud_route.get_route_stops_ordered(db, route.id)
        if not route_stops:
            continue
        stop_index = {s.id: idx for idx, s in enumerate(route_stops)}
        start_idx = stop_index.get(start_stop.id, 0)
        end_idx = stop_index.get(end_stop.id, len(route_stops) - 1)
        forward_direction = start_idx <= end_idx

        route_buses = []
        for bus in buses:
            if bus.get("route_id") != route.id:
                continue
            lat = bus.get("lat")
            lon = bus.get("lon")
            if lat is None or lon is None:
                continue

            if max_age_seconds > 0:
                pos_ts = bus.get("timestamp")
                try:
                    age_seconds = now_ts - float(pos_ts)
                except (TypeError, ValueError):
                    continue
                if age_seconds > max_age_seconds:
                    continue

            bus_idx = nearest_stop_index(float(lat), float(lon), route_stops)

            plate_number = bus.get("plate_number", "")
            direction = None
            if plate_number:
                try:
                    recent_coords = await get_recent_coords(plate_number)
                    direction = infer_bus_direction(recent_coords, route_stops)
                except Exception:
                    direction = None

            if direction is None:
                continue
            if forward_direction:
                if direction < 0 or bus_idx > start_idx:
                    continue
            else:
                if direction > 0 or bus_idx < start_idx:
                    continue

            occupancy_level = 0
            if redis is not None and plate_number:
                try:
                    live = await redis.hgetall(bus_live_key(plate_number))
                    if live:
                        occupancy_level = int(live.get("occupancy_level", 0))
                except Exception:
                    occupancy_level = 0

            eta_stops = (
                route_stops if forward_direction else list(reversed(route_stops))
            )
            eta_payloads = estimate_route_stop_eta_payloads(
                float(lat),
                float(lon),
                float(bus.get("speed") or 0.0),
                int(occupancy_level),
                route.route_number,
                route.id,
                eta_stops,
                plate_number=plate_number,
                vehicle_id=bus.get("vehicle_id"),
            )
            eta_data = eta_payloads.get(end_stop.id)
            if not eta_data:
                continue
            try:
                eta_seconds = float(eta_data.get("eta_seconds", 0))
            except (TypeError, ValueError):
                eta_seconds = 0.0
            live_eta = compute_live_eta(
                eta_data.get("eta_seconds", 0), eta_data.get("computed_at", 0)
            )

            route_buses.append(
                {
                    "vehicle_id": bus.get("vehicle_id"),
                    "plate_number": plate_number,
                    "lat": float(lat),
                    "lon": float(lon),
                    "speed": float(bus.get("speed") or 0.0),
                    "route_id": route.id,
                    "assignment_id": bus.get("assignment_id"),
                    "occupancy_level": int(occupancy_level),
                    "eta_seconds": int(eta_seconds),
                    "eta_live_seconds": live_eta,
                    "eta_mode": eta_data.get("eta_mode"),
                    "eta_ml_seconds": eta_data.get("eta_ml_seconds"),
                    "eta_heuristic_seconds": eta_data.get("eta_heuristic_seconds"),
                    "distance_m": eta_data.get("distance_m"),
                }
            )

        if body.max_buses:
            route_buses = route_buses[: max(1, int(body.max_buses))]

        response_routes.append(
            {
                "route_id": route.id,
                "route_number": route.route_number,
                "direction": "forward" if forward_direction else "reverse",
                "name": route.name,
                "start_index": start_idx,
                "end_index": end_idx,
                "buses": route_buses,
            }
        )

    return {
        "start": {
            "query": body.start_query,
            "lat": start_point["lat"],
            "lon": start_point["lon"],
            "stop_id": start_stop.id,
            "stop_name": start_stop.name,
            "distance_m": int(
                haversine_meters(
                    start_point["lat"],
                    start_point["lon"],
                    start_stop.lat,
                    start_stop.lon,
                )
            ),
        },
        "end": {
            "query": body.end_query,
            "lat": end_point["lat"],
            "lon": end_point["lon"],
            "stop_id": end_stop.id,
            "stop_name": end_stop.name,
            "distance_m": int(
                haversine_meters(
                    end_point["lat"], end_point["lon"], end_stop.lat, end_stop.lon
                )
            ),
        },
        "routes": response_routes,
    }
