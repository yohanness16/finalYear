"""Redis caching helpers for last-known positions and route stops."""

import json
from typing import Any, List, Optional

import redis.asyncio as redis

from app.core.config import get_settings

_settings = get_settings()
redis_cache = redis.from_url(_settings.REDIS_URL, decode_responses=True)

COORD_HISTORY_MAX = 5
HIST_KEY = "veh:hist:{plate}"


async def connect_redis() -> None:
    """Connect to Redis."""
    await redis_cache.ping()


async def get_route_stops(db: Any, route_id: int) -> List[Any]:
    """Stops for route validation (from DB)."""
    from app.crud import route as crud_route

    if db is None:
        return []
    return await crud_route.get_route_stops_ordered(db, route_id)


async def get_cached_route_stops(route_id: str) -> List[Any]:
    """Legacy alias."""
    return []


async def get_last_coords(plate: str) -> list[dict[str, float]]:
    """Recent coordinates newest-first (for GPS outlier checks)."""
    key = HIST_KEY.format(plate=plate)
    raw_list = await redis_cache.lrange(key, 0, COORD_HISTORY_MAX - 1)
    out: list[dict[str, float]] = []
    for raw in raw_list:
        try:
            data = json.loads(raw)
            out.append({"lat": float(data["lat"]), "lon": float(data["lon"])})
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            continue
    return out


async def set_bus_live_pipeline(
    plate: str,
    lat: float,
    lon: float,
    occupancy: int,
    assignment_id: int,
    ttl: int = 300,
) -> None:
    """Update last position, coord history, and push to live stream."""
    key_hist = HIST_KEY.format(plate=plate)
    async with redis_cache.pipeline(transaction=True) as pipe:
        pipe.set(f"veh:pos:{plate}", json.dumps([lat, lon]), ex=ttl)
        pipe.lpush(key_hist, json.dumps({"lat": lat, "lon": lon}))
        pipe.ltrim(key_hist, 0, COORD_HISTORY_MAX - 1)
        pipe.expire(key_hist, ttl)
        pipe.xadd(
            "pipe:positions",
            {
                "plate": plate,
                "lat": str(lat),
                "lon": str(lon),
                "occupancy": str(occupancy),
                "assignment_id": str(assignment_id),
            },
        )
        await pipe.execute()


def set_last_position(plate: str, lat: float, lon: float, ttl: int = 300) -> None:
    import asyncio

    async def _set() -> None:
        await redis_cache.set(f"veh:pos:{plate}", json.dumps([lat, lon]), ex=ttl)

    asyncio.create_task(_set())


async def push_live_position(plate: str, payload: dict) -> None:
    fields = {"plate": plate, **{k: str(v) for k, v in payload.items()}}
    await redis_cache.xadd("pipe:positions", fields)


async def close_redis_cache() -> None:
    await redis_cache.aclose()
