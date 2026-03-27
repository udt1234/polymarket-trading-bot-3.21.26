from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import asyncio
import logging

log = logging.getLogger(__name__)

router = APIRouter()

_connections: list[WebSocket] = []


async def broadcast(event: str, data: dict):
    message = {"event": event, "data": data}
    for ws in _connections[:]:
        try:
            await ws.send_json(message)
        except Exception:
            _connections.remove(ws)


@router.websocket("/ws/feeds")
async def websocket_feed(websocket: WebSocket):
    await websocket.accept()
    _connections.append(websocket)
    log.info(f"WebSocket connected ({len(_connections)} total)")
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        _connections.remove(websocket)
        log.info(f"WebSocket disconnected ({len(_connections)} total)")
