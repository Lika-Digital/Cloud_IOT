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
        self._broadcast_hooks: list = []
        # v3.6 — per-session subscriptions for mobile QR-claim clients.
        # Maps session_id → set of WebSockets that want live telemetry /
        # lifecycle events for that specific session only. A connection can
        # subscribe to at most one session (the one it claimed via QR).
        self._session_subs: dict[int, set[WebSocket]] = {}

    def add_broadcast_hook(self, fn) -> None:
        """Register a coroutine function called after every broadcast."""
        self._broadcast_hooks.append(fn)

    async def connect(self, websocket: WebSocket, customer_id: int | None = None):
        await websocket.accept()
        self._connections.append((websocket, customer_id))
        logger.info(f"WebSocket connected (customer_id={customer_id}). Total: {len(self._connections)}")

    def disconnect(self, websocket: WebSocket):
        self._connections = [(ws, cid) for ws, cid in self._connections if ws is not websocket]
        # Also remove from any session subscription set so a disconnected
        # mobile client stops receiving targeted pushes.
        for sid, subs in list(self._session_subs.items()):
            subs.discard(websocket)
            if not subs:
                del self._session_subs[sid]
        logger.info(f"WebSocket disconnected. Total: {len(self._connections)}")

    def subscribe_to_session(self, websocket: WebSocket, session_id: int) -> None:
        """Register `websocket` to receive `broadcast_to_session(session_id, …)`
        messages. Called from the `/ws` handler after a `websocket_token` JWT
        is validated."""
        self._session_subs.setdefault(session_id, set()).add(websocket)
        logger.info(f"WebSocket subscribed to session {session_id}. Subs: {len(self._session_subs[session_id])}")

    def unsubscribe_from_session(self, websocket: WebSocket, session_id: int) -> None:
        subs = self._session_subs.get(session_id)
        if subs:
            subs.discard(websocket)
            if not subs:
                del self._session_subs[session_id]

    async def broadcast(self, message: dict):
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
        for hook in self._broadcast_hooks:
            asyncio.create_task(hook(message))

    async def broadcast_to_session(self, session_id: int, message: dict, *,
                                   close_after: bool = False) -> None:
        """Send `message` only to WebSockets subscribed to `session_id`.

        Used for mobile-client live telemetry and session lifecycle events so a
        customer only sees their own socket's data, not every pedestal's.
        Global operator-dashboard broadcasts still go through `broadcast()`.

        `close_after=True` closes each subscriber after delivering the message —
        used for `session_ended` so the mobile client knows the channel is done.
        """
        subs = self._session_subs.get(session_id)
        if not subs:
            return
        data = json.dumps(message)
        dead: list[WebSocket] = []
        for ws in list(subs):
            try:
                await asyncio.wait_for(ws.send_text(data), timeout=_SEND_TIMEOUT)
                if close_after:
                    try:
                        await ws.close(code=1000, reason="session ended")
                    except Exception:
                        pass
                    dead.append(ws)
            except asyncio.TimeoutError:
                logger.warning("Session-scoped WS send timed out — dropping")
                dead.append(ws)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

    @property
    def connection_count(self) -> int:
        return len(self._connections)

    @property
    def session_subscriber_count(self) -> int:
        return sum(len(s) for s in self._session_subs.values())


ws_manager = WebSocketManager()
