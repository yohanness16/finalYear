"""Route and stop endpoints."""

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
