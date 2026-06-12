"""WebSocket endpoint for mobile clients (passenger app).

Provides real-time bus position + ETA updates filtered by route.
Replaces the need for mobile apps to poll GET /vehicles/positions.

Protocol:
  1. Client connects with JWT in query string
  2. Server validates token, accepts connection
  3. Client sends: {"type": "subscribe", "route_id": 5}
  4. Server streams vehicle_position messages for route 5 only
  5. Client can change subscription: {"type": "subscribe", "route_id": 42}
  6. Client sends: {"type": "ping"} → server responds {"type": "pong"}
"""

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
    """Real-time bus updates for the mobile passenger app.

    Authentication:
        Pass JWT as query parameter: ws://host/api/v1/ws/mobile?token=<jwt>

    Subscription:
        After connecting, send: {"type": "subscribe", "route_id": <int>}

    Messages from server (vehicle_position for subscribed route):
        {
            "type": "vehicle_position",
            "vehicle_id": 1,
            "plate_number": "ABC-123",
            "lat": 9.032,
            "lon": 38.746,
            "speed": 25.0,
            "route_id": 5,
            "timestamp": 1717185600.0,
            "bus_type": "Anbessa",
            "occupancy_level": 1,
            "eta_payloads": {
                "<stop_id>": {
                    "stop_name": "Meskel Square",
                    "eta_seconds": 120,
                    "distance_m": 800,
                    "computed_at": 1717185600.0
                }
            }
        }

    Messages from server (cv_result — crowd analysis):
        {
            "type": "cv_result",
            "vehicle_id": 1,
            "plate_number": "ABC-123",
            "timestamp": 1717185600.0,
            "cv": {
                "people_count": 12,
                "face_count": 3,
                "head_blob_count": 1,
                "crowd_density": 1,
                "is_crowded": false,
                "method": "yolov8_multi(person:8+face:3+head:1)",
                "confidence": 0.72,
                "foreground_ratio": 0.35,
                "inference_ms": 142.3
            }
        }
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

    # Register with no route filter initially (will filter after subscribe)
    manager.register_mobile(websocket, route_id=None)

    try:
        await websocket.send_json({
            "type": "connected",
            "detail": "mobile_stream",
            "message": 'Send {"type": "subscribe", "route_id": N} to start receiving updates.',
        })

        while True:
            try:
                raw = await asyncio.wait_for(
                    websocket.receive_text(), timeout=120.0
                )
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                msg_type = data.get("type")

                if msg_type == "subscribe":
                    route_id = data.get("route_id")
                    stop_id = data.get("stop_id")
                    if route_id is not None:
                        try:
                            route_id = int(route_id)
                        except (TypeError, ValueError):
                            await websocket.send_json({
                                "type": "error",
                                "detail": "route_id must be an integer",
                            })
                            continue
                        websocket.scope["subscribed_route_id"] = route_id
                        if stop_id is not None:
                            try:
                                stop_id = int(stop_id)
                            except (TypeError, ValueError):
                                await websocket.send_json({
                                    "type": "error",
                                    "detail": "stop_id must be an integer",
                                })
                                continue
                            websocket.scope["subscribed_stop_id"] = stop_id
                        else:
                            websocket.scope.pop("subscribed_stop_id", None)
                        resp = {"type": "subscribed", "route_id": route_id}
                        if stop_id is not None:
                            resp["stop_id"] = stop_id
                        await websocket.send_json(resp)

                elif msg_type == "unsubscribe":
                    websocket.scope["subscribed_route_id"] = None
                    await websocket.send_json({
                        "type": "unsubscribed",
                    })

                elif msg_type == "ping":
                    await websocket.send_json({"type": "pong"})

            except TimeoutError:
                await websocket.send_json({"type": "heartbeat"})

    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(websocket)
