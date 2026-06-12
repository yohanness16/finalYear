"""Redis connection and helper functions for live state.

Fixes:
- Explicit ConnectionPool with max_connections=50 (was default 10, causing MaxConnectionsError)
- Separate pubsub pool so subscribe connections don't starve regular commands
- Socket keepalive + timeouts so stale connections are detected fast
"""

import json
import logging

from typing import Any

import redis.asyncio as redis
from redis.asyncio.connection import ConnectionPool, SSLConnection, Connection

from app.core.config import get_settings

settings = get_settings()

logger = logging.getLogger(__name__)

_redis_client: redis.Redis | None = None
_pubsub_client: redis.Redis | None = None  # dedicated client for pubsub only


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

    def delete(self, *keys):
        for key in keys:
            self._ops.append(("delete", key))

    def zrem(self, key, *members):
        self._ops.append(("zrem", key, members))

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def execute(self):
        for op in self._ops:
            if op[0] == "hset":
                key, mapping = op[1], op[2]
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
            elif op[0] == "delete":
                self._store.pop(op[1], None)
            elif op[0] == "zrem":
                pass  # no-op in fake
        return True


class FakeRedis:
    """A tiny async-compatible in-memory Redis substitute for tests/CI."""

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

    async def hget(self, key, field):
        return self._store.get(key, {}).get(field)

    async def expire(self, key, ttl):
        return True

    async def lpush(self, key, value):
        self._store.setdefault(key, [])
        self._store[key].insert(0, value)

    async def ltrim(self, key, start, end):
        arr = self._store.get(key, [])
        self._store[key] = arr[start: end + 1] if end != -1 else arr[start:]

    async def lrange(self, key, start, end):
        arr = self._store.get(key, [])
        if end == -1:
            return arr[start:]
        return arr[start: end + 1]

    async def scan(self, cursor, match=None, count=100):
        return 0, []

    def pipeline(self, *args, **kwargs):
        return _FakePipeline(self._store, *args, **kwargs)

    async def geoadd(self, key, member):
        self._store.setdefault(key, set()).add(member)

    async def xadd(self, name, fields, maxlen=None, approximate=False):
        self._store.setdefault(name, [])
        entry_id = f"{len(self._store[name]):015d}-0"
        self._store[name].append({k: str(v) for k, v in fields.items()})
        if maxlen is not None:
            while len(self._store[name]) > maxlen:
                self._store[name].pop(0)
        return entry_id

    async def publish(self, channel, message):
        return 1

    async def hgetall(self, key):
        return self._store.get(key, {})

    async def close(self):
        self._store.clear()

    def pubsub(self):
        return _FakePubSub()


class _FakePubSub:
    async def subscribe(self, *channels):
        pass

    async def unsubscribe(self, *channels):
        pass

    async def listen(self):
        # Never yields in fake — loop won't run in tests
        return
        yield  # make it an async generator

    async def aclose(self):
        pass


def _make_pool(url: str, max_connections: int = 50) -> ConnectionPool:
    """Build a ConnectionPool with sensible defaults for production."""
    is_tls = url.startswith("rediss://")
    connection_class = SSLConnection if is_tls else Connection

    kwargs: dict = {
        "max_connections": max_connections,
        "socket_keepalive": True,
        "socket_connect_timeout": 5,
        "socket_timeout": 5,
        "retry_on_timeout": True,
        "health_check_interval": 30,
        "decode_responses": True,
    }

    if is_tls:
        kwargs["ssl_cert_reqs"] = None  # Upstash / managed TLS — skip cert verify

    return ConnectionPool.from_url(url, **kwargs)


async def get_redis() -> redis.Redis:
    """Get the shared Redis client (general commands).

    Uses a pool of up to 50 connections. Falls back to FakeRedis in CI.
    """
    global _redis_client
    if _redis_client is None:
        try:
            pool = _make_pool(settings.REDIS_URL, max_connections=50)
            client = redis.Redis(connection_pool=pool)
            await client.ping()
            _redis_client = client
            logger.info("Redis connected (general pool, max_connections=50)")
        except Exception:
            logger.exception("Failed to connect to Redis at %s — using FakeRedis", settings.REDIS_URL)
            _redis_client = FakeRedis()
    return _redis_client


async def get_pubsub_redis() -> redis.Redis:
    """Get a DEDICATED Redis client for pubsub subscriptions only.

    Kept separate so pubsub connections never compete with regular
    commands for pool slots — this was the root cause of MaxConnectionsError.
    """
    global _pubsub_client
    if _pubsub_client is None:
        try:
            # Pubsub only needs a small pool — each subscriber uses 1 connection
            pool = _make_pool(settings.REDIS_URL, max_connections=10)
            client = redis.Redis(connection_pool=pool)
            await client.ping()
            _pubsub_client = client
            logger.info("Redis connected (pubsub pool, max_connections=10)")
        except Exception:
            logger.exception("Failed to connect pubsub Redis — using FakeRedis")
            _pubsub_client = FakeRedis()
    return _pubsub_client


async def close_redis() -> None:
    """Close both Redis connections on app shutdown."""
    global _redis_client, _pubsub_client
    if _redis_client and not isinstance(_redis_client, FakeRedis):
        await _redis_client.aclose()
        _redis_client = None
    if _pubsub_client and not isinstance(_pubsub_client, FakeRedis):
        await _pubsub_client.aclose()
        _pubsub_client = None


# ── Key helpers ────────────────────────────────────────────────────────────────

def bus_live_key(plate_number: str) -> str:
    return f"bus:live:{plate_number}"


def bus_coords_key(plate_number: str) -> str:
    return f"bus:coords:{plate_number}"


def route_stop_key(route_no: str, stop_id: int) -> str:
    return f"route:{route_no}:stop:{stop_id}"


# ── Write helpers ──────────────────────────────────────────────────────────────

async def set_route_stop_etas(
    route_number: str, payloads: dict[int, dict[str, Any]], ttl: int = 300
) -> None:
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
    client = await get_redis()
    key = bus_live_key(plate_number)
    await client.hset(key, mapping={
        "lat": str(lat),
        "lon": str(lon),
        "speed": str(speed),
        "occupancy_level": str(occupancy_level),
        "assignment_id": str(assignment_id),
    })
    await client.expire(key, settings.BUS_LIVE_TTL)


async def push_coord_to_buffer(plate_number: str, lat: float, lon: float) -> None:
    client = await get_redis()
    key = bus_coords_key(plate_number)
    coord = json.dumps({"lat": lat, "lon": lon})
    await client.lpush(key, coord)
    await client.ltrim(key, 0, 4)
    await client.expire(key, settings.BUS_LIVE_TTL)


async def get_last_coords(plate_number: str) -> list[dict[str, float]]:
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
    client = await get_redis()
    await client.geoadd("active_buses", (lon, lat, plate_number))


async def set_bus_live_pipeline(
    plate_number: str,
    lat: float,
    lon: float,
    occupancy_level: int,
    assignment_id: int,
) -> None:
    """Batch Redis ops in one pipeline to reduce round-trips."""
    client = await get_redis()
    pipe = client.pipeline()
    coord = json.dumps({"lat": lat, "lon": lon})
    coords_key = bus_coords_key(plate_number)
    live_key = bus_live_key(plate_number)
    pipe.lpush(coords_key, coord)
    pipe.ltrim(coords_key, 0, 4)
    pipe.expire(coords_key, settings.BUS_LIVE_TTL)
    pipe.hset(live_key, mapping={
        "lat": str(lat),
        "lon": str(lon),
        "speed": "0",
        "occupancy_level": str(occupancy_level),
        "assignment_id": str(assignment_id),
    })
    pipe.expire(live_key, settings.BUS_LIVE_TTL)
    pipe.geoadd("active_buses", (lon, lat, plate_number))
    await pipe.execute()


async def clear_bus_live_data(
    plate_number: str, route_number: str | None = None
) -> None:
    """Remove all live Redis data for a bus when its assignment ends."""
    client = await get_redis()
    pipe = client.pipeline()
    pipe.delete(bus_live_key(plate_number))
    pipe.delete(bus_coords_key(plate_number))
    pipe.delete(f"veh:pos:{plate_number}")
    pipe.delete(f"veh:cv:{plate_number}")
    pipe.delete(f"veh:hist:{plate_number}")
    pipe.zrem("active_buses", plate_number)
    await pipe.execute()

    if route_number:
        pattern = f"route:{route_number}:stop:*"
        cursor = 0
        while True:
            cursor, keys = await client.scan(cursor, match=pattern, count=100)
            if keys:
                await client.delete(*keys)
            if cursor == 0:
                break