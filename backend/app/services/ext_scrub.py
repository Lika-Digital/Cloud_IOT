"""What the ERP is never given — one filter on every /api/ext response (spec §16.3d, owner
2026-10-16).

The gateway proxies as admin (D3), so whatever an admin route returns, the ERP receives. Two
things must not travel that way, whatever a route returns now or later:

  * **the camera credentials** — `camera_stream_url` carries the username and password inside the
    address (`routers/pedestal_config.py`, the camera settings save), and `camera_username`,
    `camera_password` are the same secret. Removed wherever they occur, and any URL's
    `user:password@` part is cut from every string — so a route that adds a new field holding
    such an address does not release the password either.
  * **the customer's name** (`customer_name`) — the ERP has its own customer records; it gets
    `customer_id`, `nfc_user_id`, `erp_ref`, which is what it bills on.

ONE place, an ASGI middleware on the path prefix, rather than a fix in each route: "otherwise
the first person who puts the field back releases the password again" (owner). The value is
never logged.
"""
from __future__ import annotations

import json
import re

EXT_PREFIX = "/api/ext/"
DROPPED_KEYS = frozenset({"camera_stream_url", "camera_username", "camera_password",
                          "customer_name"})
# scheme://user:password@host → scheme://host
_USERINFO = re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://)[^/@\s\"']*@")


def scrub(value):
    if isinstance(value, dict):
        return {k: scrub(v) for k, v in value.items() if k not in DROPPED_KEYS}
    if isinstance(value, list):
        return [scrub(v) for v in value]
    if isinstance(value, str) and "@" in value:
        return _USERINFO.sub(r"\1", value)
    return value


class ExtResponseScrubber:
    """Pure ASGI: buffers JSON responses under /api/ext/ and passes everything else through
    untouched (a stream or a picture is never buffered)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http" or not scope.get("path", "").startswith(EXT_PREFIX):
            await self.app(scope, receive, send)
            return

        start: dict | None = None
        chunks: list[bytes] = []
        is_json = False

        async def wrapped(message):
            nonlocal start, is_json
            if message["type"] == "http.response.start":
                headers = {k.lower(): v for k, v in message.get("headers", [])}
                is_json = b"json" in headers.get(b"content-type", b"")
                if not is_json:
                    await send(message)
                    return
                start = message
                return
            if message["type"] == "http.response.body" and is_json:
                chunks.append(message.get("body", b""))
                if message.get("more_body"):
                    return
                body = b"".join(chunks)
                try:
                    body = json.dumps(scrub(json.loads(body)), ensure_ascii=False).encode("utf-8")
                except ValueError:
                    pass                                   # not parseable: sent as it was
                headers = [(k, v) for k, v in start.get("headers", [])
                           if k.lower() != b"content-length"]
                headers.append((b"content-length", str(len(body)).encode()))
                await send({**start, "headers": headers})
                await send({"type": "http.response.body", "body": body, "more_body": False})
                return
            await send(message)

        await self.app(scope, receive, wrapped)
