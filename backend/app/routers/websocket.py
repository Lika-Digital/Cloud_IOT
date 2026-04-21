import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from ..services.websocket_manager import ws_manager
from ..auth.tokens import decode_token

router = APIRouter(tags=["websocket"])
logger = logging.getLogger(__name__)


@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    token: str | None = Query(default=None),
):
    """Main WebSocket endpoint.

    Three token modes are supported:
      - No token → anonymous operator-dashboard view, receives global broadcasts.
      - Long-lived customer JWT (`role="customer"`) → same as anonymous plus
        customer-scoped filtering metadata.
      - Short-lived `ws_session` JWT from `/api/mobile/qr/claim` → subscribes
        this connection to `broadcast_to_session(session_id, ...)` so the
        mobile app receives real-time telemetry only for its own session.
    """
    customer_id: int | None = None
    subscribed_session_id: int | None = None

    if token:
        try:
            payload = decode_token(token)
            if payload:
                role = payload.get("role")
                if role == "customer":
                    customer_id = int(payload["sub"])
                elif role == "ws_session":
                    customer_id = int(payload["sub"])
                    sid = payload.get("session_id")
                    if isinstance(sid, int):
                        subscribed_session_id = sid
        except Exception as e:
            logger.warning(f"WebSocket: invalid token ignored — {e}")

    await ws_manager.connect(websocket, customer_id=customer_id)
    if subscribed_session_id is not None:
        ws_manager.subscribe_to_session(websocket, subscribed_session_id)

    try:
        while True:
            data = await websocket.receive_text()
            if len(data) > 1024:
                logger.warning("WebSocket: oversized frame (%d bytes) — closing connection", len(data))
                await websocket.close(code=1009)
                break
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
    except Exception as e:
        logger.warning(f"WebSocket error: {e}")
        ws_manager.disconnect(websocket)
