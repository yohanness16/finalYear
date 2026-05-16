"""Redis caching helpers for last-known positions and route stops."""

import json
from typing import Any

import redis.asyncio as redis

from app.core.config import get_settings

_settings = get_settings()


def _build_redis_kwargs(url: str) -> dict:
    kwargs = {"decode_responses": True}

    if url.startswith("rediss://"):
        import ssl

        kwargs["ssl"] = True
        kwargs["ssl_cert_reqs"] = ssl.CERT_NONE

    return kwargs


redis_cache = redis.from_url(
    _settings.REDIS_URL, **_build_redis_kwargs(_settings.REDIS_URL)
)

COORD_HISTORY_MAX = 5
HIST_KEY = "veh:hist:{plate}"


async def connect_redis() -> None:
    """Connect to Redis."""
    await redis_cache.ping()


async def get_route_stops(db: Any, route_id: int) -> list[Any]:
    """Stops for route validation (from DB)."""
    from app.crud import route as crud_route

    if db is None:
        return []
    return await crud_route.get_route_stops_ordered(db, route_id)


async def get_cached_route_stops(route_id: str) -> list[Any]:
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
    """Update last position, coord history, occupancy hash, and push to live stream."""
    key_hist = HIST_KEY.format(plate=plate)
    key_cv = f"veh:cv:{plate}"
    async with redis_cache.pipeline(transaction=True) as pipe:
        # Position (JSON array for backward compat)
        pipe.set(f"veh:pos:{plate}", json.dumps([lat, lon]), ex=ttl)
        # Coordinate history for GPS validation
        pipe.lpush(key_hist, json.dumps({"lat": lat, "lon": lon}))
        pipe.ltrim(key_hist, 0, COORD_HISTORY_MAX - 1)
        pipe.expire(key_hist, ttl)
        # CV result hash — stores crowd density for live queries
        pipe.hset(
            key_cv,
            mapping={
                "occupancy_level": str(occupancy),
                "people_count": "0",
                "crowd_density": str(occupancy),
                "confidence": "0",
                "method": "unknown",
                "updated_at": str(int(__import__("time").time())),
            },
        )
        pipe.expire(key_cv, ttl)
        # Redis Stream for live consumers
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


async def update_cv_result(
    plate: str,
    occupancy_level: int,
    people_count: int,
    crowd_density: int,
    confidence: float,
    method: str,
    ttl: int = 300,
) -> None:
    """Update the CV result hash for a vehicle after image analysis."""
    key_cv = f"veh:cv:{plate}"
    import time as _time

    await redis_cache.hset(
        key_cv,
        mapping={
            "occupancy_level": str(occupancy_level),
            "people_count": str(people_count),
            "crowd_density": str(crowd_density),
            "confidence": str(confidence),
            "method": method,
            "updated_at": str(int(_time.time())),
        },
    )
    await redis_cache.expire(key_cv, ttl)


async def get_cv_result(plate: str) -> dict[str, Any] | None:
    """Get the latest CV result for a vehicle. Returns None if not found."""
    key_cv = f"veh:cv:{plate}"
    data = await redis_cache.hgetall(key_cv)
    if not data:
        return None
    return {
        "occupancy_level": int(data.get("occupancy_level", 0)),
        "people_count": int(data.get("people_count", 0)),
        "crowd_density": int(data.get("crowd_density", 0)),
        "confidence": float(data.get("confidence", 0.0)),
        "method": data.get("method", "unknown"),
        "updated_at": int(data.get("updated_at", 0)),
    }


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
