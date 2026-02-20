"""WebSocket endpoint for live bus updates."""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.services.websocket import manager

router = APIRouter()


@router.websocket("/ws/live")
async def websocket_live(websocket: WebSocket):
    """WebSocket for live bus location updates."""
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            await manager.broadcast({"type": "ping", "data": data})
    except WebSocketDisconnect:
        manager.disconnect(websocket)
