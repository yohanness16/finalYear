"""Redis caching helpers for last-known positions and route stops.

Uses the shared redis_client.get_redis() connection so reads and writes
go through the same pool — fixing the silent write-failure bug caused by
maintaining two separate Redis clients.
"""

import json
import time as _time
from typing import Any

from app.utils.redis_client import get_redis, bus_live_key, bus_coords_key

COORD_HISTORY_MAX = 5
HIST_KEY = "veh:hist:{plate}"


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
    client = await get_redis()
    raw_list = await client.lrange(key, 0, COORD_HISTORY_MAX - 1)
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
    key_bus_live = bus_live_key(plate)
    key_bus_coords = bus_coords_key(plate)
    client = await get_redis()
    async with client.pipeline(transaction=True) as pipe:
        # Position (JSON array for backward compat)
        pipe.set(f"veh:pos:{plate}", json.dumps([lat, lon]), ex=ttl)
        # Coordinate history for GPS validation
        pipe.lpush(key_hist, json.dumps({"lat": lat, "lon": lon}))
        pipe.ltrim(key_hist, 0, COORD_HISTORY_MAX - 1)
        pipe.expire(key_hist, ttl)
        # Compatibility keys for live dashboard / direct Redis checks
        pipe.lpush(key_bus_coords, json.dumps({"lat": lat, "lon": lon}))
        pipe.ltrim(key_bus_coords, 0, COORD_HISTORY_MAX - 1)
        pipe.expire(key_bus_coords, ttl)
        pipe.hset(
            key_bus_live,
            mapping={
                "lat": str(lat),
                "lon": str(lon),
                "speed": "0",
                "occupancy_level": str(occupancy),
                "assignment_id": str(assignment_id),
            },
        )
        pipe.expire(key_bus_live, ttl)
        # CV result hash — stores crowd density for live queries
        pipe.hset(
            key_cv,
            mapping={
                "occupancy_level": str(occupancy),
                "people_count": "0",
                "crowd_density": str(occupancy),
                "confidence": "0",
                "method": "unknown",
                "updated_at": str(int(_time.time())),
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
    image_path: str | None = None,
    ttl: int = 300,
) -> None:
    """Update the CV result hash for a vehicle after image analysis."""
    key_cv = f"veh:cv:{plate}"
    client = await get_redis()
    mapping: dict[str, str] = {
        "occupancy_level": str(occupancy_level),
        "people_count": str(people_count),
        "crowd_density": str(crowd_density),
        "confidence": str(confidence),
        "method": method,
        "updated_at": str(int(_time.time())),
    }
    if image_path:
        mapping["image_path"] = image_path
    await client.hset(key_cv, mapping=mapping)
    await client.expire(key_cv, ttl)


async def get_cv_result(
    plate: str,
    keys: tuple[str, ...] | None = None,
    defaults: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Get the latest CV result for a vehicle. Returns None if not found.

    Args:
        plate: Vehicle plate number.
        keys: Optional tuple of Redis hash keys to retrieve. When None,
              returns the standard 6-field dict for backward compatibility.
        defaults: Optional default values for each key. When provided the
                  return dict will contain every key in *keys*.
    """
    key_cv = f"veh:cv:{plate}"
    client = await get_redis()
    data = await client.hgetall(key_cv)
    if not data:
        return None

    if keys is None:
        return {
            "occupancy_level": int(data.get("occupancy_level", 0)),
            "people_count": int(data.get("people_count", 0)),
            "crowd_density": int(data.get("crowd_density", 0)),
            "confidence": float(data.get("confidence", 0.0)),
            "method": data.get("method", "unknown"),
            "updated_at": int(data.get("updated_at", 0)),
        }

    # Extended mode: return exactly the requested keys with type coercion.
    result: dict[str, Any] = {}
    for k in keys:
        raw = data.get(k)
        if raw is None:
            result[k] = defaults.get(k, None) if defaults else None
            continue
        if k in ("occupancy_level", "people_count", "crowd_density", "updated_at"):
            result[k] = int(raw)
        elif k == "confidence":
            result[k] = float(raw)
        else:
            result[k] = raw
    return result


def set_last_position(plate: str, lat: float, lon: float, ttl: int = 300) -> None:
    import asyncio

    async def _set() -> None:
        client = await get_redis()
        await client.set(f"veh:pos:{plate}", json.dumps([lat, lon]), ex=ttl)

    asyncio.create_task(_set())


async def push_live_position(plate: str, payload: dict) -> None:
    client = await get_redis()
    fields = {"plate": plate, **{k: str(v) for k, v in payload.items()}}
    await client.xadd("pipe:positions", fields)


async def close_redis_cache() -> None:
    """No-op: connection is managed by redis_client.close_redis()."""
    pass
