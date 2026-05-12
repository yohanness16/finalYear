"""Point-to-point search and journey planning."""

import time

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud import route as crud_route
from app.db.session import get_db
from app.schemas.tracking import PointToPointSearch
from app.utils.redis_client import get_redis, bus_live_key

router = APIRouter()


@router.post("/search/point-to-point")
async def point_to_point_search(
    body: PointToPointSearch,
    db: AsyncSession = Depends(get_db),
):
    """
    Find routes passing through start and end stops.
    Returns routes with pre-calculated bus ETAs from Redis.
    """
    start = await crud_route.get_stop_by_id(db, body.start_stop_id)
    end = await crud_route.get_stop_by_id(db, body.end_stop_id)
    if not start or not end:
        raise HTTPException(404, "Stop not found")
    routes = await crud_route.get_routes_through_stops(db, body.start_stop_id, body.end_stop_id)
    redis = None
    try:
        redis = await get_redis()
    except Exception:
        redis = None
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
            # Provide a smooth live ETA between telemetry pings.
            try:
                eta_seconds = float(data.get("eta_seconds", 0))
                computed_at = float(data.get("computed_at", 0))
                if computed_at > 0:
                    elapsed = max(0.0, time.time() - computed_at)
                    live_eta = max(0, int(round(eta_seconds - elapsed)))
                    data["eta_live_seconds"] = live_eta
            except (TypeError, ValueError):
                pass
        if data:
            results.append({"route_number": route.route_number, "etas": data})
        else:
            results.append({"route_number": route.route_number, "etas": {}})
    return {"routes": results, "start_stop": start.name, "end_stop": end.name}
