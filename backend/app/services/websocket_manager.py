import asyncio
import json
import logging
from fastapi import WebSocket

logger = logging.getLogger(__name__)

# Max time to wait for a single client to accept a message before treating it as dead
_SEND_TIMEOUT = 5.0


class WebSocketManager:
    def __init__(self):
        # List of (websocket, customer_id | None)
        self._connections: list[tuple[WebSocket, int | None]] = []

    async def connect(self, websocket: WebSocket, customer_id: int | None = None):
        await websocket.accept()
        self._connections.append((websocket, customer_id))
        logger.info(f"WebSocket connected (customer_id={customer_id}). Total: {len(self._connections)}")

    def disconnect(self, websocket: WebSocket):
        self._connections = [(ws, cid) for ws, cid in self._connections if ws is not websocket]
        logger.info(f"WebSocket disconnected. Total: {len(self._connections)}")

    async def broadcast(self, message: dict):
        if not self._connections:
            return
        data = json.dumps(message)
        dead: list[WebSocket] = []
        for ws, _ in self._connections:
            try:
                await asyncio.wait_for(ws.send_text(data), timeout=_SEND_TIMEOUT)
            except asyncio.TimeoutError:
                logger.warning("WebSocket send timed out — dropping stale connection")
                dead.append(ws)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

    @property
    def connection_count(self) -> int:
        return len(self._connections)


ws_manager = WebSocketManager()
