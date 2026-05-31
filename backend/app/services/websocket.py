"""WebSocket connection manager with Redis Pub/Sub for cross-worker broadcasting.

Architecture:
  - Each worker maintains its own local set of WebSocket connections
  - When any worker wants to broadcast, it publishes to a Redis channel
  - ALL workers receive the Redis message and forward to their local clients
  - This works with any number of Gunicorn/Uvicorn workers

Channels:
  - ws:vehicle_position  — bus position + occupancy updates
  - ws:cv_result         — CV crowd analysis results

Replaced the old in-memory-only ConnectionManager that broke with
multi-worker Gunicorn deployments (each worker had its own list, so
only ~50% of messages reached clients).
"""

import asyncio
import json
import logging
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
        try:
            loop = asyncio.get_running_loop()
            self._sub_task = loop.create_task(self._subscribe_loop())
            logger.info("WebSocket Redis subscriber started")
        except RuntimeError:
            # No running loop yet — will be started from lifespan
            logger.debug("No running event loop — deferring subscriber start")

    async def stop(self):
        """Stop the subscriber. Called on app shutdown."""
        self._running = False
        if self._sub_task:
            self._sub_task.cancel()
            try:
                await self._sub_task
            except asyncio.CancelledError:
                pass
        # Close all local connections gracefully
        for ws in list(self._local_connections):
            try:
                await ws.close()
            except Exception:
                pass
        self._local_connections.clear()

    # ── Local connection management ──────────────────────────────────────

    def register(self, websocket: WebSocket) -> None:
        """Register an already-accepted WebSocket (for admin endpoints)."""
        self._local_connections.add(websocket)
        logger.debug(
            "WebSocket registered locally (total: %d)", len(self._local_connections)
        )

    def disconnect(self, websocket: WebSocket) -> None:
        self._local_connections.discard(websocket)

    @property
    def local_count(self) -> int:
        return len(self._local_connections)

    # ── Cross-worker broadcast via Redis ─────────────────────────────────

    async def publish(self, channel: str, message: dict) -> None:
        """
        Publish a message to Redis. All workers (including this one)
        will receive it in _subscribe_loop.
        """
        try:
            client = await asyncio.wait_for(get_redis(), timeout=REDIS_TIMEOUT)
            await asyncio.wait_for(
                client.publish(channel, json.dumps(message)),
                timeout=REDIS_TIMEOUT,
            )
        except Exception:
            logger.warning(
                "Redis publish failed for channel %s", channel, exc_info=True
            )

    async def _subscribe_loop(self):
        """
        Background task: subscribe to Redis channels and forward
        messages to local WebSocket connections.

        Auto-reconnects on failure with 5-second backoff.
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
          - Admin WebSockets (no filter): receive ALL positions
          - Mobile WebSockets: filtered by route_id (see websocket_mobile.py)
        """
        dead: list[WebSocket] = []

        for ws in self._local_connections:
            try:
                await ws.send_json(data)
            except Exception:
                dead.append(ws)

        for ws in dead:
            self.disconnect(ws)


# Singleton — one per worker process
manager = ConnectionManager()
