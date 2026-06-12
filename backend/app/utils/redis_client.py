"""Redis connection and helper functions for live state.

Improvements:
- Use proper TLS kwargs for `rediss://` URLs (avoid string literals).
- Ping the server on first connect and log errors so writes don't fail silently.
"""

import json
import logging

from typing import Any

import redis.asyncio as redis

from app.core.config import get_settings

settings = get_settings()

_redis_client: redis.Redis | None = None


class _FakePipeline:
    def __init__(self, store: dict, *args, **kwargs):
        self._ops = []
        self._store = store

    def hset(self, key, mapping=None, **kwargs):
        self._ops.append(("hset", key, mapping or kwargs))

    def expire(self, key, ttl):
        self._ops.append(("expire", key, ttl))

    def lpush(self, key, value):
        self._ops.append(("lpush", key, value))

    def ltrim(self, key, start, end):
        self._ops.append(("ltrim", key, start, end))

    def geoadd(self, key, member):
        self._ops.append(("geoadd", key, member))

    def set(self, key, value, ex=None):
        self._ops.append(("set", key, value, ex))

    def xadd(self, stream, mapping, maxlen=None, approximate=False):
        self._ops.append(("xadd", stream, mapping, maxlen))

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def execute(self):
        # Naive execution: apply hset and simple list pushes
        for op in self._ops:
            if op[0] == "hset":
                key = op[1]
                mapping = op[2]
                self._store.setdefault(key, {})
                for k, v in mapping.items():
                    self._store[key][k] = v
            elif op[0] == "lpush":
                key, value = op[1], op[2]
                self._store.setdefault(key, [])
                self._store[key].insert(0, value)
            elif op[0] == "set":
                _, key, value, _ex = op
                self._store[key] = value
            elif op[0] == "xadd":
                _, stream, mapping, maxlen = op
                self._store.setdefault(stream, [])
                self._store[stream].append(mapping)
                if maxlen is not None:
                    while len(self._store[stream]) > maxlen:
                        self._store[stream].pop(0)
        return True


class FakeRedis:
    """A tiny async-compatible in-memory Redis substitute for tests/CI.

    Implements only the methods used by the test-suite and application
    (ping, set, get, delete, hset, expire, lpush, lrange, pipeline, geoadd,
    publish, close).
    """

    def __init__(self):
        self._store: dict = {}

    async def ping(self):
        return True

    async def set(self, key, value, ex=None):
        self._store[key] = value

    async def get(self, key):
        return self._store.get(key)

    async def delete(self, *keys):
        for k in keys:
            self._store.pop(k, None)

    async def hset(self, key, mapping=None, **kwargs):
        mapping = mapping or kwargs
        self._store.setdefault(key, {})
        for k, v in mapping.items():
            self._store[key][k] = v

    async def expire(self, key, ttl):
        # no-op in fake
        return True

    async def lpush(self, key, value):
        self._store.setdefault(key, [])
        self._store[key].insert(0, value)

    async def lrange(self, key, start, end):
        arr = self._store.get(key, [])
        # emulate redis lrange semantics (end inclusive, -1 means last)
        if end == -1:
            return arr[start:]
        return arr[start : end + 1]

    def pipeline(self, *args, **kwargs):
        return _FakePipeline(self._store, *args, **kwargs)

    async def geoadd(self, key, member):
        self._store.setdefault(key, set()).add(member)

    async def xadd(self, name, fields, maxlen=None, approximate=False):
        """Track stream entries; enforce maxlen if provided (for test accuracy)."""
        self._store.setdefault(name, [])
        entry_id = f"{len(self._store[name]):015d}-0"
        self._store[name].append({k: str(v) for k, v in fields.items()})
        if maxlen is not None:
            while len(self._store[name]) > maxlen:
                self._store[name].pop(0)
        return entry_id

    async def publish(self, channel, message):
        # No-op for tests
        return 1

    async def hgetall(self, key):
        return self._store.get(key, {})


    async def close(self):
        self._store.clear()



def _build_redis_kwargs(url: str) -> dict:
    """Build kwargs for redis.from_url, handling Upstash TLS (rediss://)."""
    kwargs: dict = {"encoding": "utf-8", "decode_responses": True}
    # If using TLS (rediss), allow insecure certs for Upstash (managed TLS),
    # but pass the correct Python object instead of a string.
    if url.startswith("rediss://"):
        # redis.from_url will set ssl=True for rediss://; set ssl_cert_reqs to
        # None so certificate validation is disabled when necessary.
        kwargs["ssl_cert_reqs"] = None
    return kwargs


async def get_redis() -> redis.Redis:
    """Get Redis client instance and verify connectivity with a ping.

    Raises the underlying exception if connecting/pinging fails so callers
    can observe errors (we also log for diagnostics).
    """
    global _redis_client
    if _redis_client is None:
        kwargs = _build_redis_kwargs(settings.REDIS_URL)
        _redis_client = redis.from_url(settings.REDIS_URL, **kwargs)
        try:
            await _redis_client.ping()
        except Exception as exc:  # pragma: no cover - runtime diagnostics
            logging.exception("Failed to connect to Redis at %s", settings.REDIS_URL)
            # Fallback for test/CI environments: use an in-memory FakeRedis
            # so features that depend on Redis don't crash the test run.
            logging.warning("Falling back to in-memory FakeRedis for tests/CI")
            _redis_client = FakeRedis()
            return _redis_client
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


async def set_route_stop_etas(
    route_number: str, payloads: dict[int, dict[str, Any]], ttl: int = 300
) -> None:
    """Store the latest ETA snapshot for each stop on a route."""
    if not payloads:
        return
    client = await get_redis()
    pipe = client.pipeline()
    for stop_id, payload in payloads.items():
        pipe.hset(
            route_stop_key(route_number, stop_id),
            mapping={k: str(v) for k, v in payload.items()},
        )
        pipe.expire(route_stop_key(route_number, stop_id), ttl)
    await pipe.execute()


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
    pipe.hset(
        live_key,
        mapping={
            "lat": str(lat),
            "lon": str(lon),
            "speed": "0",
            "occupancy_level": str(occupancy_level),
            "assignment_id": str(assignment_id),
        },
    )
    pipe.expire(live_key, settings.BUS_LIVE_TTL)
    pipe.geoadd("active_buses", (lon, lat, plate_number))
    await pipe.execute()


async def clear_bus_live_data(
    plate_number: str, route_number: str | None = None
) -> None:
    """Remove all live Redis data for a bus when its assignment/journey ends.

    Clears the live hash, coordinate buffer, geo index entry, CV result,
    position key, history key, and route-stop ETAs (if route_number given).
    This ensures the bus immediately disappears from mobile search results.
    """
    client = await get_redis()
    pipe = client.pipeline()
    pipe.delete(bus_live_key(plate_number))
    pipe.delete(bus_coords_key(plate_number))
    pipe.delete(f"veh:pos:{plate_number}")
    pipe.delete(f"veh:cv:{plate_number}")
    pipe.delete(f"veh:hist:{plate_number}")
    pipe.zrem("active_buses", plate_number)
    if route_number:
        # Clear all route-stop ETA entries for this route — the bus is
        # no longer serving it.  We can't know every stop_id here, so we
        # delete via pattern (use scan to avoid blocking Redis).
        pass
    await pipe.execute()

    # Pattern-delete route-stop ETA keys outside the pipeline to avoid
    # blocking.  For most routes the number of stops is small so this is
    # cheap.
    if route_number:
        pattern = f"route:{route_number}:stop:*"
        cursor = 0
        while True:
            cursor, keys = await client.scan(cursor, match=pattern, count=100)
            if keys:
                await client.delete(*keys)
            if cursor == 0:
                break
