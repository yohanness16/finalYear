"""Route and stop endpoints."""

import time

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import RequireAdmin
from app.crud import route as crud_route
from app.db.session import get_db
from app.schemas.route import (
    RouteCreate,
    RouteResponse,
    RouteWithStops,
    StopCreate,
    StopResponse,
)
from app.utils.redis_client import get_redis

router = APIRouter()


@router.post("/stops", response_model=StopResponse)
async def create_stop(
    current_user: RequireAdmin,
    stop: StopCreate,
    db: AsyncSession = Depends(get_db),
):
    return await crud_route.create_stop(
        db,
        stop.name,
        stop.lat,
        stop.lon,
        stop.base_dwell_time,
        stop.is_terminal,
        stop.peak_multiplier,
    )


@router.get("/stops", response_model=list[StopResponse])
async def list_stops(
    skip: int = 0, limit: int = 100, db: AsyncSession = Depends(get_db)
):
    limit = min(limit, 500)
    return await crud_route.get_stops(db, skip, limit)


@router.get("/stops/{stop_id}", response_model=StopResponse)
async def get_stop(stop_id: int, db: AsyncSession = Depends(get_db)):
    s = await crud_route.get_stop_by_id(db, stop_id)
    if not s:
        raise HTTPException(404, "Stop not found")
    return s


@router.post("/routes", response_model=RouteResponse)
async def create_route(
    current_user: RequireAdmin,
    route: RouteCreate,
    db: AsyncSession = Depends(get_db),
):
    direction = (route.direction or "forward").strip().lower()
    if direction not in {"forward", "reverse"}:
        raise HTTPException(400, "Direction must be 'forward' or 'reverse'")
    if await crud_route.get_route_by_number(db, route.route_number, direction):
        raise HTTPException(400, "Route number already exists for this direction")
    stop_sequence = (
        [(s.stop_id, s.sequence_order) for s in route.stops] if route.stops else None
    )
    return await crud_route.create_route(
        db,
        route.route_number,
        direction,
        route.name,
        route.origin,
        route.destination,
        stop_sequence,
    )


@router.get("/routes", response_model=list[RouteResponse])
async def list_routes(
    skip: int = 0, limit: int = 100, db: AsyncSession = Depends(get_db)
):
    limit = min(limit, 500)
    return await crud_route.get_routes(db, skip, limit)


@router.get("/routes/{route_id}", response_model=RouteWithStops)
async def get_route(route_id: int, db: AsyncSession = Depends(get_db)):
    r = await crud_route.get_route_by_id(db, route_id)
    if not r:
        raise HTTPException(404, "Route not found")
    stops = [rs.stop for rs in sorted(r.route_stops, key=lambda x: x.sequence_order)]
    return RouteWithStops(
        id=r.id,
        route_number=r.route_number,
        direction=r.direction,
        name=r.name,
        origin=r.origin,
        destination=r.destination,
        stops=stops,
    )


@router.get("/routes/{route_number}/etas")
async def get_route_etas(route_number: str):
    """Get all pre-computed ETAs for a route's stops (Redis-cached).

    Returns live-adjusted ETA seconds for each stop that has an active
    ETA entry. Used by frontends for ETA countdown displays.
    """
    redis = await get_redis()
    keys = await redis.keys(f"route:{route_number}:stop:*")
    result: dict[str, dict[str, object]] = {}
    now = time.time()
    for key in keys:
        data = await redis.hgetall(key)
        if not data:
            continue
        stop_id = key.split(":")[-1]
        try:
            eta_seconds = float(data.get("eta_seconds", 0))
            computed_at = float(data.get("computed_at", 0))
            elapsed = max(0.0, now - computed_at)
            live_eta = max(0, int(round(eta_seconds - elapsed)))
        except (TypeError, ValueError):
            live_eta = 0
        result[stop_id] = {
            "stop_name": data.get("stop_name", ""),
            "eta_seconds": live_eta,
            "distance_m": int(data.get("distance_m", 0)),
            "occupancy_level": int(data.get("occupancy_level", 0)),
        }
    return {"route_number": route_number, "etas": result}
