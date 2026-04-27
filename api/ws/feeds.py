from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import asyncio
import logging

from api.middleware import validate_ws_token

log = logging.getLogger(__name__)

router = APIRouter()

_connections: list[WebSocket] = []


async def broadcast(event: str, data: dict):
    message = {"event": event, "data": data}
    for ws in _connections[:]:
        try:
            await ws.send_json(message)
        except Exception:
            try:
                _connections.remove(ws)
            except ValueError:
                pass


@router.websocket("/ws/feeds")
async def websocket_feed(websocket: WebSocket):
    # Token comes via ?token=<bearer> query param. Reject before accept() to
    # avoid leaking any feed data to unauthenticated clients.
    token = websocket.query_params.get("token")
    user_id = validate_ws_token(token)
    if not user_id:
        await websocket.close(code=1008)  # policy violation
        log.warning("WebSocket rejected: missing or invalid token")
        return

    await websocket.accept()
    _connections.append(websocket)
    log.info(f"WebSocket connected user={user_id} ({len(_connections)} total)")
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        try:
            _connections.remove(websocket)
        except ValueError:
            pass
        log.info(f"WebSocket disconnected ({len(_connections)} total)")
