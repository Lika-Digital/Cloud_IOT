import asyncio
import logging
import time
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from ..services.websocket_manager import ws_manager
from ..auth.tokens import decode_token

router = APIRouter(tags=["websocket"])
logger = logging.getLogger(__name__)


_BEARER = "bearer"


def _token_from_subprotocol(websocket: WebSocket) -> str | None:
    """The operator JWT from `Sec-WebSocket-Protocol: bearer, <jwt>`.

    The header, not the query string: uvicorn's access log and nginx's write the full request
    target, so `/ws?token=...` would put every operator token into two logs. A browser sets
    this header from `new WebSocket(url, ["bearer", token])`.
    """
    raw = websocket.headers.get("sec-websocket-protocol", "")
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if len(parts) == 2 and parts[0] == _BEARER:
        return parts[1]
    return None


async def _close_at_expiry(websocket: WebSocket, exp: float | None) -> None:
    """Close the connection when its token expires — a token is checked at the handshake, so
    without this a socket opened once would stream for ever, past expiry and past logout."""
    if not exp:
        return
    await asyncio.sleep(max(0.0, float(exp) - time.time()))
    try:
        await websocket.close(code=1008)
    except Exception:
        pass


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """Live dashboard feed — for an authenticated OPERATOR only (2026-10-12, part A).

    Measured before this change: an anonymous client got 101 and the cabinet's whole telemetry
    stream. Now identity is proved with the same function every HTTP route uses
    (auth.dependencies.operator_from_token), BEFORE the connection is accepted or joins any
    broadcast. A refused client is closed during the handshake (HTTP 403): it receives no
    message — not even an empty one. Refused: no token, a non-JWT, an expired token, a pre-2FA
    (totp_pending) token, customer and ws_session tokens (D6.1: customers live in the ERP).

    The pre-2FA token is refused by the role check, so the feed opens only after the second
    factor. The connection is closed when the token expires.
    """
    from ..auth.dependencies import OperatorAuthError, operator_from_token
    from ..auth.user_database import get_user_db
    # from ..auth.user_database import UserSessionLocal

    token = _token_from_subprotocol(websocket)
    payload = None
    role = None
    if token:
        # 2026-10-12, part B: the user is looked up through get_user_db — THE SAME provider, and
        # the same override, as every HTTP route. It used UserSessionLocal directly, so under
        # test /ws checked the developer's real users.db instead of the test database: an
        # operator who exists only in the test DB was refused, and TC-WSA-06 passed only
        # because the test admin's id happened to match an active user in the real file.
        # The generator is closed at once — no session is held open for the connection's life.
        provider = websocket.app.dependency_overrides.get(get_user_db, get_user_db)
        gen = provider()
        db = next(gen)
        try:
            _user, payload = operator_from_token(token, db)
            role = _user.role  # part B: decides whether this connection sees customer identity
        except (OperatorAuthError, KeyError, ValueError, TypeError):
            payload = None
        finally:
            gen.close()
    if payload is None:
        # Never log the token. The reason is enough to count refusals.
        logger.info("WebSocket refused: %s", "no operator token" if not token
                    else "token is not a valid operator login")
        await websocket.close(code=1008)
        return

    await ws_manager.connect(websocket, subprotocol=_BEARER, role=role)
    expiry = asyncio.create_task(_close_at_expiry(websocket, payload.get("exp")))
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
        pass
    except Exception as e:
        logger.warning(f"WebSocket error: {e}")
    finally:
        expiry.cancel()
        ws_manager.disconnect(websocket)


# ── 2026-10-12: the pre-part-A handler, COMMENTED OUT, not deleted. ──────────────────────
# It accepted any connection: no token -> "anonymous operator-dashboard view"; an invalid
# token was ignored and the client treated as anonymous; customer and ws_session tokens were
# accepted from ?token= in the query string. Every one of those received the global broadcast.
# @router.websocket("/ws")
# async def websocket_endpoint(
#     websocket: WebSocket,
#     token: str | None = Query(default=None),
# ):
#     """Main WebSocket endpoint.

#     Three token modes are supported:
#       - No token → anonymous operator-dashboard view, receives global broadcasts.
#       - Long-lived customer JWT (`role="customer"`) → same as anonymous plus
#         customer-scoped filtering metadata.
#       - Short-lived `ws_session` JWT from `/api/mobile/qr/claim` → subscribes
#         this connection to `broadcast_to_session(session_id, ...)` so the
#         mobile app receives real-time telemetry only for its own session.
#     """
#     customer_id: int | None = None
#     subscribed_session_id: int | None = None

#     if token:
#         try:
#             payload = decode_token(token)
#             if payload:
#                 role = payload.get("role")
#                 if role == "customer":
#                     customer_id = int(payload["sub"])
#                 elif role == "ws_session":
#                     customer_id = int(payload["sub"])
#                     sid = payload.get("session_id")
#                     if isinstance(sid, int):
#                         subscribed_session_id = sid
#         except Exception as e:
#             logger.warning(f"WebSocket: invalid token ignored — {e}")

#     await ws_manager.connect(websocket, customer_id=customer_id)
#     if subscribed_session_id is not None:
#         ws_manager.subscribe_to_session(websocket, subscribed_session_id)

#     try:
#         while True:
#             data = await websocket.receive_text()
#             if len(data) > 1024:
#                 logger.warning("WebSocket: oversized frame (%d bytes) — closing connection", len(data))
#                 await websocket.close(code=1009)
#                 break
#             if data == "ping":
#                 await websocket.send_text("pong")
#     except WebSocketDisconnect:
#         ws_manager.disconnect(websocket)
#     except Exception as e:
#         logger.warning(f"WebSocket error: {e}")
#         ws_manager.disconnect(websocket)
