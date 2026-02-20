"""Redis connection and helper functions for live state."""

import json
from typing import Any, Optional

import redis.asyncio as redis
from app.core.config import get_settings

settings = get_settings()

_redis_client: Optional[redis.Redis] = None


async def get_redis() -> redis.Redis:
    """Get Redis client instance."""
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
        )
    return _redis_client


async def close_redis() -> None:
    """Close Redis connection."""
    global _redis_client
    if _redis_client:
        await _redis_client.close()
        _redis_client = None


def bus_live_key(plate_number: str) -> str:
    """Key for bus live state hash."""
    return f"bus:live:{plate_number}"


def bus_coords_key(plate_number: str) -> str:
    """Key for bus coordinates buffer (last 5 points)."""
    return f"bus:coords:{plate_number}"


def route_stop_key(route_no: str, stop_id: int) -> str:
    """Key for pre-calculated ETAs at a stop."""
    return f"route:{route_no}:stop:{stop_id}"


async def set_bus_live(
    plate_number: str,
    lat: float,
    lon: float,
    speed: float,
    occupancy_level: int,
    assignment_id: int,
) -> None:
    """Store bus live state in Redis hash."""
    client = await get_redis()
    key = bus_live_key(plate_number)
    data = {
        "lat": str(lat),
        "lon": str(lon),
        "speed": str(speed),
        "occupancy_level": str(occupancy_level),
        "assignment_id": str(assignment_id),
    }
    await client.hset(key, mapping=data)
    await client.expire(key, settings.BUS_LIVE_TTL)


async def push_coord_to_buffer(plate_number: str, lat: float, lon: float) -> None:
    """Push coordinate to circular buffer (last 5), trim if needed."""
    client = await get_redis()
    key = bus_coords_key(plate_number)
    coord = json.dumps({"lat": lat, "lon": lon})
    await client.lpush(key, coord)
    await client.ltrim(key, 0, 4)
    await client.expire(key, settings.BUS_LIVE_TTL)


async def get_last_coords(plate_number: str) -> list[dict[str, float]]:
    """Get last 5 coordinates from buffer."""
    client = await get_redis()
    key = bus_coords_key(plate_number)
    raw = await client.lrange(key, 0, -1)
    coords = []
    for r in raw:
        try:
            coords.append(json.loads(r))
        except json.JSONDecodeError:
            pass
    return coords


async def add_bus_to_geo(plate_number: str, lon: float, lat: float) -> None:
    """Add bus to Redis geospatial index for nearby lookup."""
    client = await get_redis()
    await client.geoadd("active_buses", (lon, lat, plate_number))


async def set_bus_live_pipeline(
    plate_number: str,
    lat: float,
    lon: float,
    occupancy_level: int,
    assignment_id: int,
) -> None:
    """Batch Redis ops: push coords, set live hash, add to geo. Reduces round-trips."""
    client = await get_redis()
    pipe = client.pipeline()
    coord = json.dumps({"lat": lat, "lon": lon})
    coords_key = bus_coords_key(plate_number)
    live_key = bus_live_key(plate_number)
    pipe.lpush(coords_key, coord)
    pipe.ltrim(coords_key, 0, 4)
    pipe.expire(coords_key, settings.BUS_LIVE_TTL)
    pipe.hset(live_key, mapping={
        "lat": str(lat), "lon": str(lon), "speed": "0",
        "occupancy_level": str(occupancy_level), "assignment_id": str(assignment_id),
    })
    pipe.expire(live_key, settings.BUS_LIVE_TTL)
    pipe.geoadd("active_buses", (lon, lat, plate_number))
    await pipe.execute()

