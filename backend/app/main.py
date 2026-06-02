"""FastAPI application entry point."""

import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import (
    admin,
    admin_dashboard,
    admin_users,
    assignments,
    auth,
    crowd,
    favorites,
    gateway,
    notifications,
    pairing,
    routes,
    search,
    tracking,
    users,
    vehicles,
    websocket,
    websocket_mobile,
)
from app.core.config import get_settings
from app.middleware.firewall import FirewallMiddleware
from app.middleware.request_validator import RequestValidationMiddleware
from app.middleware.security_headers import SecurityHeadersMiddleware
from app.services.redis_cache import close_redis_cache
from app.services.websocket import manager as ws_manager
from app.utils.redis_client import close_redis

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage startup and shutdown."""
    logger = logging.getLogger("uvicorn")

    # Start Redis Pub/Sub subscriber for cross-worker WebSocket broadcast
    await ws_manager.start()
    logger.info(
        "WebSocket Redis subscriber starting (pid=%d)",
        os.getpid() if hasattr(os, "getpid") else 0,
    )

    # Start push notification background worker (if FCM key configured)
    notif_task: asyncio.Task | None = None
    if settings.FCM_SERVER_KEY and settings.FCM_SERVER_KEY != "xxx":
        from app.tasks.notifications import notification_worker
        notif_task = asyncio.create_task(notification_worker())
        logger.info("Push notification worker started")
    else:
        logger.info("Push notification worker disabled (no FCM_SERVER_KEY)")

    yield

    # Shutdown
    if notif_task:
        notif_task.cancel()
        try:
            await asyncio.wait_for(notif_task, timeout=10.0)
        except asyncio.CancelledError:
            pass
        except asyncio.TimeoutError:
            logger.warning("Notification worker did not stop within timeout; forcing cancel")
    await ws_manager.stop()
    await close_redis()
    await close_redis_cache()


app = FastAPI(
    title="Smart Transport API",
    description="Real-time Public Transport Tracking & Density Prediction",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/health", tags=["health"])
async def health_check():
    """Health check endpoint for Azure App Service and load balancers."""
    from app.db.session import engine
    from app.utils.redis_client import get_redis

    health = {"status": "healthy", "version": "1.0.0"}

    # Check database
    try:
        async with engine.connect() as conn:
            await conn.execute(__import__("sqlalchemy").text("SELECT 1"))
        health["database"] = "connected"
    except Exception as e:
        health["database"] = f"error: {type(e).__name__}"
        health["status"] = "degraded"

    # Check Redis
    try:
        r = await get_redis()
        await r.ping()
        health["redis"] = "connected"
    except Exception as e:
        health["redis"] = f"error: {type(e).__name__}"
        health["status"] = "degraded"

    status_code = 200 if health["status"] == "healthy" else 503
    from fastapi.responses import JSONResponse

    return JSONResponse(content=health, status_code=status_code)


# ── Middleware stack (order matters: last added = first executed) ──

# 4. CORS — outermost layer, handles preflight
cors_origins = [o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()]
# When credentials are enabled, browsers reject wildcard origins.
# If the configured value is the default wildcard, disable credentials
# to prevent CORS failures; otherwise use the explicit origin list.
if cors_origins == ["*"]:
    _cors_allow_credentials = False
    _cors_allow_origins = ["*"]
else:
    _cors_allow_credentials = True
    _cors_allow_origins = cors_origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_allow_origins,
    allow_credentials=_cors_allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 3. Security headers — adds HSTS, CSP, etc. to every response
app.add_middleware(SecurityHeadersMiddleware)

# 2. Request validation — body size, content-type, method checks
app.add_middleware(RequestValidationMiddleware)

# 1. Firewall — IP blocklisting, anomaly scoring (innermost, closest to handler)
if settings.FIREWALL_ENABLED:
    app.add_middleware(FirewallMiddleware)

# ── API Routers ──
app.include_router(auth.router, prefix="/api/v1", tags=["auth"])
app.include_router(admin_users.router, prefix="/api/v1/admin/users", tags=["admin"])
app.include_router(admin_dashboard.router, prefix="/api/v1", tags=["admin"])
app.include_router(tracking.router, prefix="/api/v1", tags=["tracking"])
app.include_router(gateway.router, prefix="/api/v1", tags=["gateway"])
app.include_router(crowd.router, prefix="/api/v1", tags=["crowd"])
app.include_router(users.router, prefix="/api/v1", tags=["users"])
app.include_router(vehicles.router, prefix="/api/v1", tags=["vehicles"])
app.include_router(routes.router, prefix="/api/v1", tags=["routes"])
app.include_router(assignments.router, prefix="/api/v1", tags=["assignments"])
app.include_router(admin.router, prefix="/api/v1", tags=["admin"])
app.include_router(websocket.router, prefix="/api/v1", tags=["websocket"])
app.include_router(websocket_mobile.router, prefix="/api/v1", tags=["websocket"])
app.include_router(search.router, prefix="/api/v1", tags=["search"])
app.include_router(favorites.router, prefix="/api/v1", tags=["favorites"])
app.include_router(notifications.router, prefix="/api/v1", tags=["notifications"])
app.include_router(pairing.router, prefix="/api/v1", tags=["pairing"])
