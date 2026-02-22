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
    # Extract customer_id from JWT if provided (mobile app)
    customer_id: int | None = None
    if token:
        try:
            payload = decode_token(token)
            if payload and payload.get("role") == "customer":
                customer_id = int(payload["sub"])
        except Exception as e:
            logger.warning(f"WebSocket: invalid token ignored — {e}")

    await ws_manager.connect(websocket, customer_id=customer_id)
    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
    except Exception as e:
        logger.warning(f"WebSocket error: {e}")
        ws_manager.disconnect(websocket)
