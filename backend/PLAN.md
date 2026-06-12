# 🔧 Backend Fix & Enhancement Plan — BusTrack

> Generated: 2026-05-31
> Scope: Production-readiness fixes, WebSocket architecture, mobile real-time, push notifications

---

## 📋 TABLE OF CONTENTS

1. [Current System Architecture](#1-current-system-architecture)
2. [What the Mobile App Needs vs What It Gets](#2-what-the-mobile-app-needs-vs-what-it-gets)
3. [Task #1 — Fix WebSocket for Multi-Worker Production](#3-task-1--fix-websocket-for-multi-worker-production)
4. [Task #2 — Mobile WebSocket Endpoint](#4-task-2--mobile-websocket-endpoint)
5. [Task #3 — Deduplicate Telemetry Processing](#5-task--3--deduplicate-telemetry-processing)
6. [Task #4 — Push Notification System (FCM)](#6-task-4--push-notification-system-fcm)
7. [Task #5 — Secure Unprotected Endpoints](#7-task-5--secure-unprotected-endpoints)
8. [Task #6 — Rate Limiter on vehicles/telemetry](#8-task-6--rate-limiter-on-vehiclestelemetry)
9. [Mobile Search Gap Analysis & Fixes](#9-mobile-search-gap-analysis--fixes)
10. [Execution Order & Dependencies](#10-execution-order--dependencies)

---

## 1. CURRENT SYSTEM ARCHITECTURE

```
ESP32-CAM ──► POST /api/v1/gateway/esp32/telemetry  ──► image_pipeline (10-step)
SIM7600   ──► POST /api/v1/telemetry                 ──► tracking (inline)
 ESP32    ──► POST /api/v1/vehicles/telemetry         ──► vehicles (inline)
                     │
                     ▼
              broadcast_vehicle_position()
              broadcast_cv_result()
                     │
                     ▼
         ConnectionManager.broadcast()
         (in-memory list, per-process)
                     │
                     ▼
         Admin WebSocket /api/v1/ws/live
         (only works reliably with 1 worker)

Mobile ──(polling)──► GET /vehicles/positions
Mobile ──(polling)──► GET /routes/{number}/etas
Mobile ──(one-shot)──► POST /search/point-to-point
Mobile ──(one-shot)──► POST /search/journey
```

**Key problem:** `ConnectionManager` at `app/services/websocket.py:6-34` stores connections in a plain `list[WebSocket]` in memory. The Dockerfile runs `gunicorn -w 2`, meaning two separate worker processes, each with its own `manager` instance. When a telemetry request hits Worker A, the broadcast only reaches admin WebSocket clients connected to Worker A. Worker B's clients see nothing.

---

## 2. WHAT THE MOBILE APP NEEDS VS WHAT IT GETS

Your requirement: *"User searches start and stop, system returns all live buses passing through that place, their ETA, occupancy level, and the nearest stop for user to catch the bus."*

### What `POST /api/v1/search/journey` currently returns (for each bus):

```json
{
  "vehicle_id": 1,
  "plate_number": "ABC-123",
  "lat": 9.032,
  "lon": 38.746,
  "speed": 25.0,
  "route_id": 5,
  "assignment_id": 10,
  "occupancy_level": 1,          ✅ Present
  "eta_seconds": 320,             ✅ ETA to END stop
  "eta_live_seconds": 295,        ✅ Live-adjusted ETA to END stop
  "eta_to_start_stop": 120,       ✅ ETA from bus to boarding stop
  "eta_live_to_start_stop": 95,   ✅ Live-adjusted ETA to boarding stop
  "route_number": "121",
  "direction": "forward",
  "buses": [...],
  "start": { "lat": ..., "lon": ..., "stop_id": ..., "stop_name": "...", "distance_m": ... },
  "end":   { "lat": ..., "lon": ..., "stop_id": ..., "stop_name": "...", "distance_m": ... }
}
```

### What `POST /api/v1/search/point-to-point` currently returns (for each bus):

```json
{
  "vehicle_id": 1,
  "plate_number": "ABC-123",
  "lat": ..., "lon": ..., "speed": ...,
  "route_id": 5, "assignment_id": 10,
  "occupancy_level": 1,          ✅ Present
  "eta_to_start_stop": 120,       ✅ ETA to boarding stop
  "eta_live_to_start_stop": 95    ✅ Live-adjusted
}
```

### ✅ ALREADY CORRECT — The search endpoints DO return:

| Required | Status | Field |
|----------|--------|-------|
| Live buses passing through the searched area | ✅ | Filtered by route, direction, position, recency |
| ETA from bus to user's boarding stop | ✅ | `eta_to_start_stop` + `eta_live_to_start_stop` |
| Occupancy level per bus | ✅ | `occupancy_level` (0/1/2) |
| Nearest stop for user to catch bus | ✅ | `start.stop_id`, `start.stop_name`, `start.distance_m` |

### ❌ GAPS in the mobile search:

| Gap | Impact | Fix |
|-----|--------|-----|
| **No real-time updates** — mobile must poll | Stale data, high server load | Add mobile WebSocket (Task #2) |
| **No notification when bus approaches** | User misses their bus | Add push notifications (Task #4) |
| **Journey search returns `eta_seconds` for end stop, not `live_eta` for all intermediate stops** | Mobile can only show ETA to final destination, not to each stop | Add optional `include_all_stops: bool` query param |
| **`point-to-point` does NOT return `eta_seconds` to end stop** (only to start) | Mobile can't show "total trip time" | Add `eta_to_end_stop` field |
| **No image_path or cv data in search results** | Mobile can't show crowd density photo evidence to user | Optionally include last CV image path |

---

## 3. TASK #1 — Fix WebSocket for Multi-Worker Production

### Problem
`app/services/websocket.py:6-34` — `ConnectionManager` uses `self.active_connections: list[WebSocket]` in memory. With `gunicorn -w 2`, each worker has its own instance. Broadcasts from telemetry hitting Worker A don't reach WebSocket clients on Worker B.

### Solution: Redis Pub/Sub Cross-Worker Broadcast

Replace the flat in-memory manager with a Redis-backed publish/subscribe system. Each worker subscribes to a Redis channel and forwards messages to its own local connections.

### Files to Modify

**`app/services/websocket.py`** — Complete rewrite:

```python
"""
WebSocket connection manager with Redis Pub/Sub for cross-worker broadcasting.

Architecture:
  - Each worker maintains its own local set of WebSocket connections
  - When any worker wants to broadcast, it publishes to Redis channel
  - ALL workers receive the Redis message and forward to their local clients
  - This works with any number of Gunicorn/Uvicorn workers

Channels:
  - ws:vehicle_position  — bus position + occupancy updates
  - ws:cv_result         — CV crowd analysis results
"""

import asyncio
import json
import logging
from typing import Any

from fastapi import WebSocket

from app.utils.redis_client import get_redis

logger = logging.getLogger(__name__)

# Redis channel names for cross-worker broadcast
CHANNEL_VEHICLE_POSITION = "ws:vehicle_position"
CHANNEL_CV_RESULT = "ws:cv_result"

# How long to wait for Redis operations before giving up
REDIS_TIMEOUT = 2.0


class ConnectionManager:
    """
    Per-worker WebSocket connection manager with Redis Pub/Sub fan-out.
    
    Each worker process:
      1. Maintains its own local set of WebSocket connections
      2. Subscribes to Redis channels in a background task
      3. Forwards Redis messages to local connections
    """

    def __init__(self):
        # Local connections only (this worker's clients)
        self._local_connections: set[WebSocket] = set()
        # Background subscription task handle
        self._sub_task: asyncio.Task | None = None
        # Whether the subscription loop is running
        self._running = False

    async def start(self):
        """Start the Redis subscriber background task. Called once on app startup."""
        if self._running:
            return
        self._running = True
        self._sub_task = asyncio.create_task._subscribe_loop())
        logger.info("WebSocket Redis subscriber started")

    async def stop(self):
        """Stop the subscriber. Called on app shutdown."""
        self._running = False
        if self._sub_task:
            self._sub_task.cancel()
            try:
                await self._sub_task
            except asyncio.CancelledError:
                pass

    # ── Local connection management ──────────────────────────────────────

    def register(self, websocket: WebSocket) -> None:
        """Register an already-accepted WebSocket (for admin endpoints)."""
        self._local_connections.add(websocket)
        logger.debug("WebSocket registered locally (total: %d)", len(self._local_connections))

    def register_mobile(self, websocket: WebSocket, route_id: int) -> None:
        """Register a mobile WebSocket with a route subscription."""
        # Store route_id as an attribute on the WebSocket for filtering
        websocket.scope["subscribed_route_id"] = route_id
        self._local_connections.add(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        self._local_connections.discard(websocket)

    @property
    def local_count(self) -> int:
        return len(self._local_connections)

    # ── Cross-worker broadcast via Redis ─────────────────────────────────

    async def publish(self, channel: str, message: dict) -> None:
        """
        Publish a message to Redis. All workers (including this one)
        will receive it in their _subscribe_loop.
        """
        try:
            client = await asyncio.wait_for(get_redis(), timeout=REDIS_TIMEOUT)
            await asyncio.wait_for(
                client.publish(channel, json.dumps(message)),
                timeout=REDIS_TIMEOUT,
            )
        except Exception:
            logger.warning("Redis publish failed for channel %s", channel, exc_info=True)

    async def _subscribe_loop(self):
        """
        Background task: subscribe to Redis channels and forward
        messages to local WebSocket connections.
        """
        while self._running:
            try:
                client = await get_redis()
                pubsub = client.pubsub()
                await pubsub.subscribe(CHANNEL_VEHICLE_POSITION, CHANNEL_CV_RESULT)
                logger.info("Subscribed to Redis WebSocket channels")

                async for message in pubsub.listen():
                    if not self._running:
                        break
                    if message["type"] != "message":
                        continue

                    channel = message["channel"]
                    if isinstance(channel, bytes):
                        channel = channel.decode()

                    try:
                        data = json.loads(message["data"])
                    except (json.JSONDecodeError, TypeError):
                        continue

                    # Forward to local connections with optional filtering
                    await self._forward_to_locals(channel, data)

            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Redis subscribe loop error, reconnecting in 5s...")
                await asyncio.sleep(5)

    async def _forward_to_locals(self, channel: str, data: dict) -> None:
        """
        Send message to local WebSocket connections.
        
        For CHANNEL_VEHICLE_POSITION:
          - Admin WebSockets (no subscribed_route_id): receive ALL positions
          - Mobile WebSockets (with subscribed_route_id): receive ONLY if
            the position's route_id matches their subscription
        """
        dead: list[WebSocket] = []

        for ws in self._local_connections:
            try:
                # Mobile filtering: only send positions for subscribed route
                sub_route = ws.scope.get("subscribed_route_id")
                if sub_route is not None:
                    if channel == CHANNEL_VEHICLE_POSITION:
                        pos_route = data.get("route_id")
                        if pos_route is not None and pos_route != sub_route:
                            continue  # skip — not the route this mobile client cares about

                await ws.send_json(data)
            except Exception:
                dead.append(ws)

        for ws in dead:
            self.disconnect(ws)


# Singleton — one per worker process
manager = ConnectionManager()
```

**`app/main.py`** — Add startup/shutdown hooks for the subscriber:

```python
# In the lifespan function:
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start Redis WebSocket subscriber on each worker
    await manager.start()
    yield
    await manager.stop()
    await close_redis()
    await close_redis_cache()
```

**`app/services/live_broadcast.py`** — Replace `manager.broadcast()` with `manager.publish()`:

In `broadcast_vehicle_position()` (line ~62), change:
```python
# OLD:
await manager.broadcast(payload)

# NEW:
await manager.publish(CHANNEL_VEHICLE_POSITION, payload)
```

In `broadcast_cv_result()` (line ~109), change:
```python
# OLD:
await manager.broadcast(payload)

# NEW:
await manager.publish(CHANNEL_CV_RESULT, payload)

# Need to import the channel name:
from app.services.websocket import CHANNEL_VEHICLE_POSITION, CHANNEL_CV_RESULT
```

**`app/api/v1/websocket.py`** — No changes needed to the route handler itself. The existing `manager.register(websocket)` and `manager.disconnect(websocket)` calls work unchanged.

### Impact
- Fixes the 50% message loss with 2 Gunicorn workers
- Scales to any number of workers or even multiple servers
- Minimal code changes — only `websocket.py` fully rewritten, `live_broadcast.py` changes 2 lines

---

## 4. TASK #2 — Mobile WebSocket Endpoint

### Problem
Mobile app must poll `GET /vehicles/positions` every few seconds to see live updates. This is wasteful and provides stale data.

### Solution
Add `/api/v1/ws/mobile` — a WebSocket that:
1. Authenticates with any valid JWT (passenger, driver, admin)
2. Accepts subscription messages: `{"type": "subscribe", "route_id": 5}`
3. Filters incoming Redis Pub/Sub messages to only send positions for subscribed routes
4. Sends full ETA data + occupancy per update

### New file: **`app/api/v1/websocket_mobile.py`**

```python
"""WebSocket endpoint for mobile clients (passenger app)."""

import asyncio
import json

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.core.security import decode_token
from app.services.websocket import manager

router = APIRouter()


@router.websocket("/ws/mobile")
async def mobile_websocket(
    websocket: WebSocket,
    token: str = Query(..., description="JWT access token (Bearer value)"),
):
    """
    Real-time bus updates for the mobile passenger app.
    
    Protocol:
      1. Client connects with JWT in query string
       2. Server validates token, accepts connection
      3. Client sends: {"type": "subscribe", "route_id": 5}
      4. Server streams vehicle_position messages for route 5 only:
         {
           "type": "vehicle_position",
           "vehicle_id": 1, "plate_number": "ABC-123",
           "lat": ..., "lon": ..., "speed": ...,
           "route_id": 5, "timestamp": ...,
           "occupancy_level": 1,
           "eta_payloads": {"stop_id": {"stop_name": ..., "eta_seconds": ..., "distance_m": ...}}
         }
      5. Client can unsubscribe or change route:
         {"type": "subscribe", "route_id": 42}
    """
    await websocket.accept()

    # ── Auth ──
    if not token:
        await websocket.send_json({"type": "error", "detail": "missing_token"})
        await websocket.close(code=1008)
        return

    payload = decode_token(token)
    if not payload or payload.get("type") != "access":
        await websocket.send_json({"type": "error", "detail": "invalid_token"})
        await websocket.close(code=1008)
        return

    # Register (starts empty — will filter by route_id after subscribe)
    subscribed_route: int | None = None
    manager.register_mobile(websocket, subscribed_route)

    try:
        await websocket.send_json({
            "type": "connected",
            "detail": "mobile_stream",
            "message": "Send {\"type\": \"subscribe\", \"route_id\": N} to start receiving updates.",
        })

        while True:
            try:
                raw = await asyncio.wait_for(websocket.receive_text(), timeout=120.0)
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                msg_type = data.get("type")

                if msg_type == "subscribe":
                    route_id = data.get("route_id")
                    if route_id is not None:
                        subscribed_route = int(route_id)
                        websocket.scope["subscribed_route_id"] = subscribed_route
                        await websocket.send_json({
                            "type": "subscribed",
                            "route_id": subscribed_route,
                        })

                elif msg_type == "ping":
                    await websocket.send_json({"type": "pong"})

            except TimeoutError:
                await websocket.send_json({"type": "heartbeat"})

    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(websocket)
```

**`app/main.py`** — Already imports `websocket` router with `prefix="/api/v1"` and tags `["websocket"]`. Add a separate import so both handlers share the base path OR add the mobile websocket to the main v1 init. Since we already have `/api/v1/ws/live`, add the mobile endpoint as a new import:

Change in `app/api/v1/__init__.py` (or add to `main.py`):
```python
# In main.py, add after existing websocket import:
from app.api.v1 import websocket_mobile
app.include_router(websocket_mobile.router, prefix="/api/v1", tags=["websocket"])
```

The two WebSocket routers both register under `/api/v1` prefix:
- `/api/v1/ws/live` → admin (from `websocket.py`)
- `/api/v1/ws/mobile` → mobile (from `websocket_mobile.py`)

### Mobile App Protocol

```
CLIENT                              SERVER
   │                                   │
   │──── WebSocket /ws/mobile ────────►│  (with JWT in query)
   │◄─── {"type": "connected"} ────────│
   │                                   │
   │──── {"type": "subscribe",         │
   │      "route_id": 5} ────────────►│
   │◄─── {"type": "subscribed",       │
   │      "route_id": 5} ─────────────│
   │                                   │
   │◄─── {"type": "vehicle_position", │  (for route 5 only)
   │      "vehicle_id": 1,            │
   │      "occupancy_level": 1,       │
   │      "eta_payloads": {...}} ─────│
   │                                   │
   │──── {"type": "ping"} ────────────►│  (every 60s)
   │◄─── {"type": "pong"} ────────────│
```

---

## 5. TASK #3 — Deduplicate Telemetry Processing

### Problem
Telemetry processing logic exists in 3 places with drift:

| File | Has CV/Image | Has ETA | Has Redis Pipeline | Has Broadcast |
|------|-------------|---------|-------------------|---------------|
| `app/services/image_pipeline.py` | ✅ | ✅ (full) | ✅ (+ CV result) | ✅ (position + CV) |
| `app/api/v1/tracking.py` | ❌ | ✅ (full) | ✅ | ✅ (position only) |
| `app/api/v1/vehicles.py` | ❌ | ❌ | ❌ | ✅ (position only) |

### Solution: Single shared service with optional hooks

**New file: `app/services/telemetry_ingest.py`**

```python
"""
Unified telemetry ingestion service.

Handles the common pipeline for all telemetry sources:
  1. Vehicle resolution
  2. GPS validation
  3. Redis live pipeline update
  4. DB persistence (async or background)
  5. ETA computation
  6. Trip history recording
  7. WebSocket broadcast

Optional hooks:
  - image_bytes: if provided, runs CV analysis and broadcasts cv_result
  - compute_eta: if True, computes and stores route-stop ETAs
"""

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def process_telemetry(
    db: AsyncSession,
    device_id: str,
    lat: float,
    lon: float,
    speed: float,
    image_bytes: bytes | None = None,
    image_name: str | None = None,
    plate_number: str | None = None,
    bus_type: str | None = None,
    bus_capacity: int = 0,
    occupancy_level: int | None = None,
    compute_eta: bool = True,
    persist_raw: bool = True,
) -> dict[str, Any]:
    """
    Unified telemetry processing pipeline.
    
    This is the single entry point for ALL telemetry sources:
      - ESP32-CAM gateway (image_bytes provided, compute_eta=True)
      - SIM7600 tracking (no image, compute_eta=True)
      - Vehicles legacy endpoint (no image, compute_eta=False)
    
    Returns a result dict suitable for HTTP response.
    """
    from app.core.config import get_settings
    from app.crud import assignment as crud_assignment
    from app.crud import route as crud_route
    from app.crud import tracking as crud_tracking
    from app.crud import vehicle as crud_vehicle
    from app.services.image_pipeline import _resolve_vehicle, _validate_gps, _store_image
    from app.services.live_broadcast import broadcast_vehicle_position, broadcast_cv_result
    from app.services.redis_cache import set_bus_live_pipeline, update_cv_result
    from app.services.route_eta import estimate_route_stop_eta_payloads
    from app.services.route_validation import find_nearest_stop
    from app.utils.gps_validation import is_valid_coord, get_average_coord
    from app.services.redis_cache import get_last_coords
    from app.utils.redis_client import set_route_stop_etas

    settings = get_settings()
    result: dict[str, Any] = {
        "status": "received",
        "device_id": device_id,
    }

    # ── Step 1: Resolve vehicle ──
    try:
        vehicle, created = await _resolve_vehicle(
            db, device_id, plate_number, bus_type,
            capacity=bus_capacity if bus_capacity > 0 else None,
        )
    except ValueError as exc:
        return {"status": "rejected", "reason": str(exc), "device_id": device_id}

    result["vehicle_id"] = vehicle.id
    result["plate_number"] = vehicle.plate_number
    result["bus_type"] = vehicle.bus_type
    result["capacity"] = vehicle.capacity
    result["created"] = created

    # ── Step 2: Validate GPS ──
    route_stops = []
    if vehicle.route_id:
        route_stops = await crud_route.get_route_stops_ordered(db, vehicle.route_id)

    validated_lat, validated_lon, rejection = await _validate_gps(
        lat, lon, vehicle.plate_number, route_stops
    )
    if rejection:
        result["status"] = "rejected"
        result["reason"] = rejection
        result["vehicle_id"] = vehicle.id
        return result
    result["lat"] = validated_lat
    result["lon"] = validated_lon

    # ── Step 3: Image processing (optional) ──
    cv_result = None
    image_path = ""
    if image_bytes is not None:
        from app.services.image_pipeline import _yolo_detector
        try:
            image_path, image_saved = await _store_image(image_bytes, image_name)
            result["image_saved"] = image_saved
            result["image_path"] = image_path
        except Exception:
            result["image_saved"] = False

        capacity_for_cv = bus_capacity or vehicle.capacity
        cv_result = await _yolo_detector.detect(image_bytes, capacity_for_cv)
        cv_occupancy = int(cv_result["crowd_density"])

        if occupancy_level is None:
            occupancy_level = cv_occupancy
        else:
            occupancy_level = max(0, min(2, int(occupancy_level)))

        if occupancy_level == 0 and cv_result["people_count"] > 0:
            from app.services.cv_engine import estimate_density_from_people_count
            occupancy_level = estimate_density_from_people_count(
                cv_result["people_count"], capacity_for_cv
            )

        result["occupancy_level"] = occupancy_level
        result["cv"] = cv_result
        result["cv_occupancy_level"] = cv_occupancy

    elif occupancy_level is not None:
        occupancy_level = max(0, min(2, int(occupancy_level)))
        result["occupancy_level"] = occupancy_level

    # ── Step 4: Persist raw telemetry ──
    if persist_raw:
        raw_payload = {
            "source": "telemetry_service",
            "device_id": device_id,
            "plate_number": vehicle.plate_number,
            "bus_type": vehicle.bus_type,
            "capacity": vehicle.capacity or bus_capacity,
            "occupancy_level": occupancy_level,
        }
        if cv_result:
            raw_payload["cv"] = {
                "people_count": cv_result["people_count"],
                "crowd_density": cv_result["crowd_density"],
                "method": cv_result["method"],
            }

        await crud_tracking.create_raw_telemetry(
            db, vehicle.id, validated_lat, validated_lon,
            cv_result["people_count"] if cv_result else 0,
            raw_payload,
        )

    # ── Step 5: Update Redis ──
    assignment = await crud_assignment.get_active_assignment_by_vehicle(db, vehicle.id)
    assignment_id = assignment.id if assignment else 0

    try:
        await set_bus_live_pipeline(
            vehicle.plate_number, validated_lat, validated_lon,
            occupancy_level or 0, assignment_id,
        )
    except Exception:
        logger.exception("set_bus_live_pipeline failed for plate %s", vehicle.plate_number)

    if cv_result:
        try:
            await update_cv_result(
                plate=vehicle.plate_number,
                occupancy_level=occupancy_level or 0,
                people_count=cv_result["people_count"],
                face_count=cv_result.get("face_count", 0),
                head_blob_count=cv_result.get("head_blob_count", 0),
                crowd_density=cv_result["crowd_density"],
                confidence=cv_result["confidence"],
                method=cv_result["method"],
                image_path=image_path if result.get("image_saved") else None,
            )
        except Exception:
            logger.exception("update_cv_result failed for plate %s", vehicle.plate_number)

    # ── Step 6: ETA computation (optional) ──
    eta_payloads: dict = {}
    if compute_eta and vehicle.route and route_stops:
        try:
            eta_payloads = estimate_route_stop_eta_payloads(
                validated_lat, validated_lon, speed,
                occupancy_level or 0,
                vehicle.route.route_number, vehicle.route_id,
                route_stops,
                plate_number=vehicle.plate_number,
                vehicle_id=vehicle.id,
            )
            await set_route_stop_etas(vehicle.route.route_number, eta_payloads)
        except Exception:
            logger.exception("ETA computation failed for plate %s", vehicle.plate_number)

    result["eta_computed"] = bool(eta_payloads)
    result["route_checked"] = bool(vehicle.route_id)

    # ── Step 7: Update vehicle position in DB ──
    await crud_vehicle.update_position(db, vehicle.id, validated_lat, validated_lon, speed)

    # ── Step 8: Trip history ──
    if assignment and route_stops:
        nearest_stop = find_nearest_stop(validated_lat, validated_lon, route_stops)
        if nearest_stop is not None:
            try:
                await crud_tracking.create_trip_history_from_assignment(
                    db, assignment, nearest_stop,
                    validated_lat, validated_lon,
                    occupancy_level=occupancy_level,
                )
            except Exception:
                pass

    # ── Step 9: WebSocket broadcast ──
    ts = datetime.now(UTC).timestamp()
    await broadcast_vehicle_position(
        vehicle_id=vehicle.id,
        plate_number=vehicle.plate_number,
        lat=validated_lat,
        lon=validated_lon,
        speed=speed,
        route_id=vehicle.route_id,
        timestamp=ts,
        bus_type=vehicle.bus_type,
        occupancy_level=occupancy_level,
        eta_payloads=eta_payloads or None,
    )

    if cv_result:
        await broadcast_cv_result(
            vehicle_id=vehicle.id,
            plate_number=vehicle.plate_number,
            cv_result=cv_result,
            image_path=image_path if result.get("image_saved") else None,
            timestamp=ts,
        )

    result["status"] = "received"
    return result
```

### Then simplify the 3 calling endpoints:

**`app/api/v1/gateway.py`**, line ~55 — Replace the full pipeline call:
```python
# OLD (line 55):
result = await process_esp32_telemetry(...)

# NEW:
result = await process_telemetry(
    db=db, device_id=device_id, lat=lat, lon=lon, speed=speed,
    image_bytes=image_bytes, image_name=image.filename,
    plate_number=plate_number, bus_type=bus_type,
    bus_capacity=bus_capacity,
    compute_eta=True, persist_raw=True,
)
```

**`app/api/v1/tracking.py`**, line ~47 — Replace inline processing:
```python
# Replace everything from line 55 to line 166 with:
from app.services.telemetry_ingest import process_telemetry

result = await process_telemetry(
    db=db, device_id=data.device_id, lat=data.lat, lon=data.lon,
    speed=data.speed or 0.0,
    occupancy_level=resolve_occupancy_level(data.pixel_count, data.raw_payload),
    compute_eta=True, persist_raw=True,
)
return result
```

**`app/api/v1/vehicles.py`**, line ~124 — Replace the legacy endpoint:
```python
# Replace lines 129-176 with:
from app.services.telemetry_ingest import process_telemetry

result = await process_telemetry(
    db=db, device_id=data.device_id, lat=data.lat, lon=data.lon,
    speed=data.speed or 0.0,
    compute_eta=False, persist_raw=True,
)
return result
```

---

## 6. TASK #4 — Push Notification System (FCM)

### Problem
FCM tokens are stored via `POST /notifications/register-token`. `NotificationSetting` rows are created. But **no code ever sends a notification**. 

### Solution: Background task that checks ETAs and fires FCM

**New file: `app/tasks/notifications.py`**

```python
"""
Background notification sender.

Periodically checks all active bus assignments against user notification
settings and sends FCM push notifications when a bus ETA to the user's
subscribed stop is within their configured lead_time.
"""

import asyncio
import json
import logging
import time
from datetime import UTC, datetime

import httpx

from app.core.config import get_settings
from app.db.session import AsyncSessionLocal
from app.models.notification_setting import NotificationSetting
from app.models.assignment import Assignment
from app.models.route import Route, RouteStop
from app.models.stop import Stop
from app.models.user import User
from app.utils.redis_client import bus_live_key, get_redis, route_stop_key

logger = logging.getLogger(__name__)

FCM_SEND_URL = "https://fcm.googleapis.com/fcm/send"  # Legacy HTTP API
CHECK_INTERVAL_SECONDS = 60  # Check every minute


async def _send_fcm_notification(device_token: str, title: str, body: str, data: dict) -> bool:
    """
    Send a push notification using FCM Legacy HTTP API.
    Uses FCM_SERVER_KEY from settings (already in .env config).
    
    For production at scale, migrate to FCM HTTP v1 API with
    Firebase Admin SDK, but the legacy API is simpler and works
    with the existing FCM_SERVER_KEY config.
    """
    settings = get_settings()
    if not settings.FCM_SERVER_KEY:
        logger.warning("FCM_SERVER_KEY not configured — skipping notification")
        return False

    payload = {
        "to": device_token,
        "notification": {
            "title": title,
            "body": body,
            "sound": "default",
            "click_action": "FLUTTER_NOTIFICATION_CLICK",
        },
        "data": {k: str(v) for k, v in data.items()},
        "priority": "high",
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                FCM_SEND_URL,
                headers={
                    "Authorization": f"key={settings.FCM_SERVER_KEY}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
        if resp.status_code == 200:
            result = resp.json()
            if result.get("success", 0) > 0:
                logger.info("FCM notification sent to %s...%s", device_token[:8], device_token[-4:])
                return True
            else:
                logger.warning("FCM send failed: %s", result)
        else:
            logger.warning("FCM HTTP %d: %s", resp.status_code, resp.text)
    except Exception:
        logger.exception("FCM send error")

    return False


async def _get_user_fcm_token(user_id: int) -> str | None:
    """Retrieve stored FCM token from Redis."""
    try:
        r = await get_redis()
        return await r.get(f"fcm:{user_id}")
    except Exception:
        return None


async def check_and_send_notifications():
    """
    Main loop: check all notification settings against live bus ETAs.
    
    For each notification_setting:
      1. Get the route and stop
      2. Look up all live buses on that route
      3. For each bus, check its ETA to the subscribed stop
      4. If ETA <= lead_time_minutes → send push notification
    """
    settings = get_settings()
    if not settings.FCM_SERVER_KEY:
        logger.debug("FCM_SERVER_KEY not set — notification checker disabled")
        return

    async with AsyncSessionLocal() as db:
        try:
            from sqlalchemy import select
            from sqlalchemy.orm import selectinload

            # Load all notification settings with related user and route
            result = await db.execute(
                select(NotificationSetting)
                .options(
                    selectinload(NotificationSetting.user),
                    selectinload(NotificationSetting.route),
                )
            )
            all_settings = list(result.scalars().all())

            if not all_settings:
                return

            redis = await get_redis()

            for ns in all_settings:
                try:
                    user = ns.user
                    if not user:
                        continue

                    fcm_token = await _get_user_fcm_token(user.id)
                    if not fcm_token:
                        continue

                    # Look up live ETA for this route-stop combo
                    eta_key = route_stop_key(
                        _get_route_number(ns.route_id, db) or "",
                        ns.route_id,
                    )
                    # Check all buses' ETAs to this stop
                    # We need to check: route:{route_number}:stop:{stop_id}
                    # But the notification_settings doesn't have stop_id — it has route_id

                    # For now, notify based on the route. The user gets a general
                    # alert that a bus is approaching their saved route.
                    # To be more precise, we'd need stop_id in notification_settings.

                    # Find all buses currently on this route and their ETAs
                    route_stops_result = await db.execute(
                        select(Stop)
                        .join(RouteStop, RouteStop.stop_id == Stop.id)
                        .where(RouteStop.route_id == ns.route_id)
                        .order_by(RouteStop.sequence_order)
                    )
                    stops = list(route_stops_result.scalars().all())

                    route_number = _get_route_number(ns.route_id, db)
                    if not route_number:
                        continue

                    for stop in stops:
                        stop_eta_key = f"route:{route_number}:stop:{stop.id}"
                        eta_data = await redis.hgetall(stop_eta_key)
                        if not eta_data:
                            continue

                        try:
                            eta_seconds = float(eta_data.get("eta_seconds", 0))
                            computed_at = float(eta_data.get("computed_at", 0))
                        except (TypeError, ValueError):
                            continue

                        if computed_at <= 0:
                            continue

                        elapsed = max(0.0, time.time() - computed_at)
                        live_eta = max(0, int(eta_seconds - elapsed))

                        lead_time_seconds = ns.lead_time_minutes * 60

                        if 0 < live_eta <= lead_time_seconds:
                            # Bus is approaching! Send notification
                            plate = eta_data.get("bus_plate", "Unknown")
                            eta_minutes = max(1, live_eta // 60)

                            title = f"🚌 Bus Approaching {stop.name}"
                            body = (
                                f"Bus {plate} is about {eta_minutes} min away "
                                f"from {stop.name} on route {route_number}."
                            )

                            await _send_fcm_notification(
                                device_token=fcm_token,
                                title=title,
                                body=body,
                                data={
                                    "type": "bus_approaching",
                                    "route_number": route_number,
                                    "stop_name": stop.name,
                                    "eta_minutes": str(eta_minutes),
                                    "plate_number": plate,
                                },
                            )

                except Exception:
                    logger.exception(
                        "Error processing notification for user %s route %s",
                        ns.user_id, ns.route_id,
                    )

        except Exception:
            logger.exception("Notification check loop error")


async def notification_worker():
    """Long-running async worker that checks notifications periodically."""
    logger.info("Notification worker started (interval: %ds)", CHECK_INTERVAL_SECONDS)
    while True:
        try:
            await check_and_send_notifications()
        except Exception:
            logger.exception("Notification worker error")
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)


def _get_route_number(route_id: int, db) -> str | None:
    """Helper to get route number from route_id."""
    # This is a sync-ish helper — in the actual implementation,
    # pass route_number from the loaded relationship instead
    return None  # placeholder — see note below
```

### ⚠️ Important Fix Needed: `NotificationSetting` needs `stop_id`

Currently `NotificationSetting` (`app/models/notification_setting.py`) only has `user_id + route_id`. To know WHICH stop the user wants to be notified about, it needs a `stop_id` column. Without it, the notification system can only say "a bus is approaching your route" but not "a bus is approaching YOUR stop."

**Migration needed:**
```bash
# New migration: ALTER TABLE notification_settings ADD COLUMN stop_id INTEGER REFERENCES stops(id);
```

**File: `app/models/notification_setting.py`** — Add field:
```python
stop_id = Column(Integer, ForeignKey("stops.id"), nullable=True)
stop = relationship("Stop")
```

**File: `app/schemas/tracking.py`** — Update `NotificationSettingCreate`:
```python
class NotificationSettingCreate(BaseModel):
    user_id: int
    route_id: int
    stop_id: int | None = None  # NEW — specific stop to watch
    lead_time_minutes: int = 10
```

**File: `app/api/v1/notifications.py`** — Update `set_notification`:
```python
ns = NotificationSetting(
    user_id=body.user_id,
    route_id=body.route_id,
    stop_id=body.stop_id,  # NEW
    lead_time_minutes=body.lead_time_minutes,
)
```

### Wire up the notification worker in `app/main.py`:

```python
# In lifespan():
from app.tasks.notifications import notification_worker

@asynccontextmanager
async def lifespan(app: FastAPI):
    await manager.start()
    # Start notification background worker
    if settings.FCM_SERVER_KEY:
        notif_task = asyncio.create_task(notification_worker())
    yield
    if settings.FCM_SERVER_KEY:
        notif_task.cancel()
    await manager.stop()
    await close_redis()
    await close_redis_cache()
```

### FCM API to use

The project's `.env` has `FCM_SERVER_KEY=xxx` (placeholder). For real deployment:
1. Go to Firebase Console → Project Settings → Cloud Messaging
2. Use the **Server key** (Legacy API) — works with `https://fcm.googleapis.com/fcm/send`
3. OR migrate to HTTP v1 API using a Firebase service account JSON file

The `FCM_SEND_URL` and format in the code above use the **Legacy HTTP API** which is simpler and requires only the server key already in `.env`.

---

## 7. TASK #5 — Secure Unprotected Endpoints

### Problem (2 endpoints)

**File: `app/api/v1/favorites.py`, line 18:**
```python
@router.post("/favorites")
async def add_favorite(body: FavoriteCreate, db: AsyncSession = Depends(get_db)):
    # NO auth — anyone can add favorites for any user_id
```

**File: `app/api/v1/notifications.py`, line 23:**
```python
@router.post("/notifications/settings")
async def set_notification(body: NotificationSettingCreate, db):
    # NO auth — anyone can set notifications for any user_id
```

### Fix for `favorites.py` (`app/api/v1/favorites.py`, line 17-28):

```python
from app.core.security import get_current_user
from app.models.user import User

# OLD (line 17-18):
@router.post("/favorites")
async def add_favorite(body: FavoriteCreate, db: AsyncSession = Depends(get_db)):

# NEW:
@router.post("/favorites")
async def add_favorite(
    body: FavoriteCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Enforce ownership
    if body.user_id != current_user.id and current_user.role != "admin":
        raise HTTPException(403, "Can only add favorites for yourself")
```

Also add auth to `POST /ratings` (line 54) which has the same issue.

### Fix for `notifications.py` (`app/api/v1/notifications.py`, line 22-33):

```python
from app.core.security import get_current_user
from app.models.user import User

# OLD (line 22):
@router.post("/notifications/settings")
async def set_notification(
    body: NotificationSettingCreate, db: AsyncSession = Depends(get_db)
):

# NEW:
@router.post("/notifications/settings")
async def set_notification(
    body: NotificationSettingCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if body.user_id != current_user.id and current_user.role != "admin":
        raise HTTPException(403, "Can only set notification settings for yourself")
```

---

## 8. TASK #6 — Rate Limiter on vehicles/telemetry

### Problem
`app/api/v1/vehicles.py`, line 124 — `POST /api/v1/vehicles/telemetry` has NO rate limiter:

```python
@router.post("/vehicles/telemetry")   # ← NO @limiter.limit()!
async def receive_telemetry(...):
```

While `app/api/v1/gateway.py`, line 13 has:
```python
@router.post("/gateway/esp32/telemetry")
@limiter.limit("300/minute")          # ← has rate limiter
```

### Fix (`app/api/v1/vehicles.py`, line 124):

Add the limiter import and decorator:
```python
from app.core.limiter import limiter  # add this import

@router.post("/vehicles/telemetry")
@limiter.limit("300/minute")          # add this decorator
async def receive_telemetry(...):
```

---

## 9. MOBILE SEARCH GAP ANALYSIS & FIXES

### What the mobile app needs (your requirement):

> "User searches start and stop, system returns: all live buses passing through that place, their ETA, occupancy level, and the nearest stop for user to catch the bus."

### Verdict: `POST /api/v1/search/journey` already returns almost everything ✅

Here's a detailed examination of each requirement:

| Requirement | Returned? | Field in response | File & Line |
|---|---|---|---|
| All live buses passing through searched area | ✅ | `routes[].buses[]` — filtered by route match, direction, position recency | `search.py:220-339` |
| ETA from bus to boarding stop | ✅ | `routes[].buses[].eta_to_start_stop` + `.eta_live_to_start_stop` | `search.py:306-318` |
| Occupancy level per bus | ✅ | `routes[].buses[].occupancy_level` | `search.py:329` |
| Nearest stop for user to catch bus | ✅ | `start.stop_id`, `start.stop_name`, `start.distance_m` | `search.py:355-371` |

### Gaps found and fixes needed:

#### Gap A: `POST /api/v1/search/point-to-point` missing `eta_to_end_stop`

**File: `app/api/v1/search.py`, line 97-186**

The `point-to-point` endpoint (stop-ID-based search) returns `eta_to_start_stop` but does NOT return `eta_to_end_stop` (total trip duration). The mobile app needs this to show "arrives at your destination in X min."

**Fix** — in `search.py`, around line 165, inside the `route_buses` loop:

```python
# ADD after the eta_to_start_stop computation (after line 163):
eta_to_end = 0
eta_live_to_end = None
end_payload = eta_payloads.get(body.end_stop_id)
if end_payload:
    try:
        eta_to_end = int(float(end_payload.get("eta_seconds", 0)))
    except (TypeError, ValueError):
        eta_to_end = 0
    eta_live_to_end = compute_live_eta(
        end_payload.get("eta_seconds", 0),
        end_payload.get("computed_at", 0),
    )

# ADD eta_to_end and eta_live_to_end to route_buses.append() (line 165):
route_buses.append({
    "vehicle_id": bus.get("vehicle_id"),
    "plate_number": plate_number,
    "lat": float(lat), "lon": float(lon),
    "speed": float(bus.get("speed") or 0.0),
    "route_id": route.id,
    "assignment_id": bus.get("assignment_id"),
    "occupancy_level": int(bus.get("occupancy_level", 0)),
    "eta_to_start_stop": eta_to_start,
    "eta_live_to_start_stop": eta_live_to_start_stop,
    "eta_to_end_stop": eta_to_end,              # NEW
    "eta_live_to_end_stop": eta_live_to_end,    # NEW
})
```

#### Gap B: `search/journey` does not include `cv_data` (crowd image evidence)

**File: `app/api/v1/search.py`, line 220**

The journey search returns `occupancy_level` but not the detailed CV data. If the mobile app wants to show a "crowdedness" indicator with photo evidence:

**Fix** — in `search.py` journey route, around line 270, add:
```python
# After occupancy_level is determined (line 279), also fetch CV data:
cv_data = None
if redis is not None and plate_number:
    try:
        from app.services.redis_cache import get_cv_result
        cv = await get_cv_result(plate_number)
        if cv:
            cv_data = {
                "people_count": cv.get("people_count", 0),
                "crowd_density": cv.get("crowd_density", 0),
                "method": cv.get("method", "unknown"),
                "confidence": cv.get("confidence", 0),
            }
    except Exception:
        cv_data = None

# Add cv_data to route_buses.append() dict:
route_buses.append({
    ...
    "cv_data": cv_data,       # NEW — optional crowd detail
})
```

#### Gap C: No `last_seen` freshness indicator in search results

The mobile app needs to know if the bus position is fresh (e.g., "updated 10s ago"). The `timestamp` field already exists but its format depends on the source:

**Fix** — ensure `search.py` always includes a `position_age_seconds` field:
```python
# In both search endpoints, add to each bus dict:
"position_age_seconds": max(0, int(time.time() - float(bus.get("timestamp", time.time()))))
```

#### Gap D: `search/journey` returns routes even if NO live buses match

**File: `app/api/v1/search.py`, line 225-354**

Currently, routes are included in results even when `route_buses = []`. This means the mobile app shows routes that have no active buses right now. Consider whether this is intended or if empty routes should be filtered out.

**Fix** — At line 341, after building `route_buses`:
```python
# Only include routes that have at least one live bus:
if not route_buses:
    continue  # skip routes with no live buses
```

#### Gap E: Geocoding won't work without API key

**File: `app/services/geocoding.py`, line 22**

`GOOGLE_MAPS_API_KEY` is set to `xxx` in `.env`, which means `geocode_text()` will always return `None`. Journey search with text queries (e.g., "Meskel Square") will fail.

**Fix:** You need a real Google Maps API key, OR use a free alternative like Nominatim (OpenStreetMap):

```python
# Option: Add Nominatim fallback in geocoding.py
async def geocode_text_nominatim(query: str) -> dict | None:
    """Free geocoding via OpenStreetMap Nominatim (no API key needed)."""
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(
                "https://nominatim.openstreetmap.org/search",
                params={"q": query, "format": "json", "limit": 1},
                headers={"User-Agent": "BusTrack/1.0"},
            )
        if resp.status_code != 200:
            return None
        results = resp.json()
        if not results:
            return None
        best = results[0]
        return {
            "lat": float(best["lat"]),
            "lon": float(best["lon"]),
            "provider": "nominatim",
            "label": best.get("display_name", query),
        }
    except Exception:
        return return None
```

---

## 10. EXECUTION ORDER & DEPENDENCIES

```
Priority 1 (Critical — break production if not fixed):
  ┌─────────────────────────────────────────────────────────────┐
  │ Task #1: WebSocket Redis Pub/Sub (multi-worker fix)         │
  │   → Fixes 50% message loss in production                   │
  │   → Files: app/services/websocket.py (rewrite)              │
  │             app/services/live_broadcast.py (2 lines)        │
  │             app/main.py (startup/shutdown hooks)            │
  └─────────────────────────────────────────────────────────────┘

Priority 2 (High — incomplete features):
  ┌─────────────────────────────────────────────────────────────┐
  │ Task #6: Rate limiter on vehicles/telemetry                 │
  │   → 1 line change in app/api/v1/vehicles.py                 │
  │                                                             │
  │ Task #5: Auth on favorites + notifications/settings          │
  │   → 2 files, ~10 lines each                                │
  │                                                             │
  │ Task #9a: Fix point-to-point eta_to_end_stop                │
  │   → ~15 lines in app/api/v1/search.py                       │
  └─────────────────────────────────────────────────────────────┘

Priority 3 (New features):
  ┌─────────────────────────────────────────────────────────────┐
  │ Task #2: Mobile WebSocket endpoint                          │
  │   → New file: app/api/v1/websocket_mobile.py                │
  │   → Depends on Task #1 (Pub/Sub) being done first           │
  │                                                             │
  │ Task #4: Push notifications (FCM)                           │
  │   → New file: app/tasks/notifications.py                    │
  │   → DB migration: add stop_id to notification_settings      │
  │   → Update: app/main.py (startup worker)                    │
  │   → Update: app/api/v1/notifications.py (model + schema)    │
  │                                                             │
  │ Task #3: Deduplicate telemetry processing                   │
  │   → New file: app/services/telemetry_ingest.py              │
  │   → Simplify: gateway.py, tracking.py, vehicles.py          │
  └─────────────────────────────────────────────────────────────┘

Priority 4 (Nice to have):
  ┌─────────────────────────────────────────────────────────────┐
  │ Task #9b: Add cv_data to search results                     │
  │ Task #9c: Add position_age_seconds                          │
  │ Task #9d: Filter empty routes                               │
  │ Task #9e: Nominatim geocoding fallback                      │
  └─────────────────────────────────────────────────────────────┘
```

---

## APPENDIX: COMPLETE FILE-BY-FILE CHANGE LIST

| File | Change | Task |
|------|--------|------|
| `app/services/websocket.py` | Rewrite with Redis Pub/Sub | #1 |
| `app/services/live_broadcast.py` | Change `manager.broadcast()` → `manager.publish()` x2 | #1 |
| `app/main.py` | Add `manager.start()`/`manager.stop()` to lifespan, import notification worker | #1, #4 |
| `app/api/v1/websocket_mobile.py` | **NEW FILE** — mobile WebSocket endpoint | #2 |
| `app/services/telemetry_ingest.py` | **NEW FILE** — unified telemetry pipeline | #3 |
| `app/api/v1/gateway.py` | Simplify to call `process_telemetry()` | #3 |
| `app/api/v1/tracking.py` | Simplify to call `process_telemetry()` | #3 |
| `app/api/v1/vehicles.py` | Simplify to call `process_telemetry()`, add `@limiter.limit` | #3, #6 |
| `app/tasks/notifications.py` | **NEW FILE** — FCM push notification worker | #4 |
| `app/models/notification_setting.py` | Add `stop_id` column + relationship | #4 |
| `app/schemas/tracking.py` | Add `stop_id` to `NotificationSettingCreate` | #4 |
| `app/api/v1/notifications.py` | Add auth to `set_notification`, include `stop_id` | #4, #5 |
| `app/api/v1/favorites.py` | Add auth to `add_favorite` | #5 |
| `app/api/v1/search.py` | Add `eta_to_end_stop`, `cv_data`, `position_age_seconds` | #9a, #9b, #9c |
| `app/services/geocoding.py` | Add Nominatim fallback | #9e |
| `alembic/` | New migration for `notification_settings.stop_id` | #4 |

---

*End of plan. Each task is independent unless noted. Start with Task #1 (critical production fix), then #6 and #5 (quick wins), then proceed to new features.*
