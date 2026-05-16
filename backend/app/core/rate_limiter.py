"""Advanced Redis-backed sliding window rate limiter with per-endpoint tiers."""

import time
from enum import Enum

from fastapi import HTTPException, Request, status
from starlette.middleware.base import BaseHTTPMiddleware

from app.utils.redis_client import get_redis


class RateTier(Enum):
    """Rate limit tiers — each defines requests per window."""

    # Strict: login, registration, password reset
    STRICT = "strict"
    # Standard: most authenticated endpoints
    STANDARD = "standard"
    # Relaxed: read-only public endpoints
    RELAXED = "relaxed"
    # IoT: high-frequency telemetry ingestion
    IOT = "iot"
    # WebSocket: connection attempts
    WEBSOCKET = "ws"


# Tier configuration: (max_requests, window_seconds)
TIER_CONFIG: dict[RateTier, tuple[int, int]] = {
    RateTier.STRICT: (10, 60),  # 10 requests per minute
    RateTier.STANDARD: (60, 60),  # 60 requests per minute
    RateTier.RELAXED: (120, 60),  # 120 requests per minute
    RateTier.IOT: (300, 60),  # 300 requests per minute
    RateTier.WEBSOCKET: (5, 60),  # 5 connections per minute
}

# Path prefix -> tier mapping
PATH_TIERS: dict[str, RateTier] = {
    # Auth endpoints — strict
    "/api/v1/auth/login": RateTier.STRICT,
    "/api/v1/auth/register": RateTier.STRICT,
    "/api/v1/auth/google": RateTier.STRICT,
    "/api/v1/auth/driver-login": RateTier.STRICT,
    "/api/v1/auth/bus-dashboard/login": RateTier.STRICT,
    "/api/v1/auth/refresh": RateTier.STRICT,
    # IoT endpoints — high throughput
    "/api/v1/telemetry": RateTier.IOT,
    "/api/v1/gateway": RateTier.IOT,
    # WebSocket — strict connection limit
    "/api/v1/ws": RateTier.WEBSOCKET,
    # Admin endpoints — standard
    "/api/v1/admin": RateTier.STANDARD,
    # Search — relaxed (public-facing)
    "/api/v1/search": RateTier.RELAXED,
}


def resolve_tier(path: str) -> RateTier:
    """Resolve the rate tier for a given path."""
    for prefix, tier in PATH_TIERS.items():
        if path.startswith(prefix):
            return tier
    return RateTier.STANDARD


def _get_client_ip(request: Request) -> str:
    """Extract real client IP."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()
    if request.client:
        return request.client.host
    return "unknown"


class RedisRateLimiter(BaseHTTPMiddleware):
    """
    Redis-backed sliding window rate limiter.

    Uses sorted sets for O(log N) sliding window counting.
    Each IP+tier combination gets its own key.
    Returns 429 with Retry-After header when limit is exceeded.
    """

    async def dispatch(self, request: Request, call_next):
        ip = _get_client_ip(request)
        path = request.url.path
        tier = resolve_tier(path)
        max_requests, window_seconds = TIER_CONFIG[tier]

        try:
            redis = await get_redis()
            key = f"ratelimit:{tier.value}:{ip}"
            now = time.time()
            window_start = now - window_seconds

            pipe = redis.pipeline()
            # Remove entries outside the window
            pipe.zremrangebyscore(key, 0, window_start)
            # Count current entries in window
            pipe.zcard(key)
            # Add current request
            pipe.zadd(key, {f"{now}:{id(request)}": now})
            # Set expiry on the key
            pipe.expire(key, window_seconds + 1)
            results = await pipe.execute()

            current_count = results[1]

            if current_count >= max_requests:
                # Get the oldest entry to calculate retry-after
                oldest = await redis.zrange(key, 0, 0, withscores=True)
                retry_after = window_seconds
                if oldest:
                    retry_after = max(1, int(oldest[0][1] + window_seconds - now))

                return JSONResponse(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    content={
                        "detail": "Rate limit exceeded",
                        "tier": tier.value,
                        "limit": max_requests,
                        "window_seconds": window_seconds,
                    },
                    headers={
                        "Retry-After": str(retry_after),
                        "X-RateLimit-Limit": str(max_requests),
                        "X-RateLimit-Remaining": "0",
                        "X-RateLimit-Reset": str(int(now + retry_after)),
                    },
                )

            response = await call_next(request)

            # Add rate limit headers to successful responses
            remaining = max(0, max_requests - current_count - 1)
            response.headers["X-RateLimit-Limit"] = str(max_requests)
            response.headers["X-RateLimit-Remaining"] = str(remaining)
            response.headers["X-RateLimit-Tier"] = tier.value

            return response

        except Exception:
            # If Redis is down, allow the request (fail open)
            return await call_next(request)


class RateLimitExceeded(HTTPException):
    """Custom rate limit exception for non-middleware usage."""

    def __init__(self, tier: RateTier, limit: int, window: int):
        super().__init__(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded: {limit} requests per {window}s ({tier.value} tier)",
            headers={
                "Retry-After": str(window),
                "X-RateLimit-Limit": str(limit),
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Tier": tier.value,
            },
        )


async def check_rate_limit(request: Request, tier: RateTier | None = None) -> None:
    """
    Programmatic rate limit check for use in dependency injection.
    Raises RateLimitExceeded if the limit is hit.
    """
    ip = _get_client_ip(request)
    path = request.url.path
    effective_tier = tier or resolve_tier(path)
    max_requests, window_seconds = TIER_CONFIG[effective_tier]

    try:
        redis = await get_redis()
        key = f"ratelimit:{effective_tier.value}:{ip}"
        now = time.time()
        window_start = now - window_seconds

        pipe = redis.pipeline()
        pipe.zremrangebyscore(key, 0, window_start)
        pipe.zcard(key)
        pipe.zadd(key, {f"{now}:{id(request)}": now})
        pipe.expire(key, window_seconds + 1)
        results = await pipe.execute()

        current_count = results[1]
        if current_count >= max_requests:
            raise RateLimitExceeded(effective_tier, max_requests, window_seconds)

    except Exception:
        pass  # Fail open if Redis is unavailable


# Need this import at the bottom to avoid circular imports
from starlette.responses import JSONResponse  # noqa: E402
