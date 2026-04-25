"""WebSocket endpoint for live bus updates (admin dashboard)."""

import asyncio
import json

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.core.security import decode_token
from app.crud.user import get_user_by_id
from app.db.session import AsyncSessionLocal
from app.services.websocket import manager

router = APIRouter()


@router.websocket("/ws/live")
async def websocket_live(
    websocket: WebSocket,
    token: str | None = Query(
        None,
        description="Admin JWT (same value as Authorization Bearer)",
    ),
):
    """Stream `vehicle_position` JSON messages. Requires admin JWT in query `token`."""
    await websocket.accept()

    if not token:
        try:
            await websocket.send_json({"type": "error", "detail": "missing_token"})
        except Exception:
            pass
        await websocket.close(code=1008)
        return

    payload = decode_token(token)
    if not payload or payload.get("type") != "access":
        try:
            await websocket.send_json({"type": "error", "detail": "invalid_token"})
        except Exception:
            pass
        await websocket.close(code=1008)
        return

    try:
        user_id = int(payload["sub"])
    except (TypeError, ValueError):
        await websocket.close(code=1008)
        return

    async with AsyncSessionLocal() as db:
        user = await get_user_by_id(db, user_id)
    if not user or user.role != "admin":
        try:
            await websocket.send_json({"type": "error", "detail": "admin_only"})
        except Exception:
            pass
        await websocket.close(code=1008)
        return

    manager.register(websocket)
    try:
        await websocket.send_json({"type": "connected", "detail": "fleet_stream"})
        while True:
            try:
                raw = await asyncio.wait_for(websocket.receive_text(), timeout=90.0)
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if data.get("type") == "ping":
                    await websocket.send_json({"type": "pong"})
            except asyncio.TimeoutError:
                await websocket.send_json({"type": "heartbeat"})
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(websocket)
