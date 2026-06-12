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
    driver_assignments,
    favorites,
    gateway,
    notifications,
    pairing,
    performance,
    routes,
    search,
    tracking,
    trip_history,
    users,
    vehicles,
    websocket,
    websocket_mobile,
)
from app.core.config import get_settings
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

    # Start MQTT-Kafka bridge (if enabled)
    _bridge = None
    _consumer = None
    if settings.MQTT_ENABLED and settings.KAFKA_ENABLED:
        try:
            from app.services.mqtt_kafka_bridge import get_mqtt_kafka_bridge
            _bridge = await get_mqtt_kafka_bridge(settings)
            if _bridge:
                await _bridge.start()
                logger.info("MQTT-Kafka bridge started")
        except Exception:
            logger.exception("Failed to start MQTT-Kafka bridge")

        try:
            from app.services.telemetry_consumer import get_telemetry_consumer
            _consumer = await get_telemetry_consumer(settings)
            if _consumer:
                await _consumer.start()
                logger.info("Kafka telemetry consumer started")
        except Exception:
            logger.exception("Failed to start Kafka telemetry consumer")
    else:
        logger.info("MQTT/Kafka disabled (set MQTT_ENABLED=true KAFKA_ENABLED=true to enable)")

    yield

    # Shutdown
    if notif_task:
        notif_task.cancel()
        try:
            await asyncio.wait_for(notif_task, timeout=10.0)
        except asyncio.CancelledError:
            pass
        except asyncio.TimeoutError:
            logger.warning(
                "Notification worker did not stop within timeout; forcing cancel"
            )

    if _consumer:
        try:
            await _consumer.stop()
        except Exception:
            logger.exception("Error stopping Kafka consumer")

    if _bridge:
        try:
            await _bridge.stop()
        except Exception:
            logger.exception("Error stopping MQTT-Kafka bridge")

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
# Open CORS: allow ALL origins, all methods, all headers
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
    max_age=86400,
    allow_origin_regex=".*",
)

# 3. Security headers — DISABLED (CSP/form-action blocks cross-origin POST)
# app.add_middleware(SecurityHeadersMiddleware)

# 2. Request validation — DISABLED (body parsing conflicts cause 422)
# app.add_middleware(RequestValidationMiddleware)

# 1. Firewall — DISABLED (anomaly scoring blocks legitimate requests)
# if settings.FIREWALL_ENABLED:
#     app.add_middleware(FirewallMiddleware)

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
app.include_router(
    driver_assignments.router, prefix="/api/v1", tags=["driver-assignments"]
)
app.include_router(trip_history.router, prefix="/api/v1", tags=["trip-history"])
app.include_router(performance.router, prefix="/api/v1", tags=["performance"])
