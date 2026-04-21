# Mobile API Contract (v3.6)

Authoritative reference for the Expo customer app. The mobile surface is
**monitoring only** — the app may claim a session and watch it live, but
never stops it via API.

---

## Base URLs

| Environment | REST | WebSocket |
|---|---|---|
| Production | `https://marina.lika.solutions` | `wss://marina.lika.solutions/ws` |
| LAN dev    | `http://<NUC-IP>:8000`           | `ws://<NUC-IP>:8000/ws`          |

All responses are `application/json` unless noted.

---

## Authentication

Two separate JWTs are used — do not mix them.

| Token | Source | Lifetime | Use for |
|---|---|---|---|
| Customer token | `POST /api/customer/auth/login` (password) — `role="customer"` | 30 days | every REST call below |
| `ws_session` token | `POST /api/mobile/qr/claim` — `role="ws_session"` | 1 hour | **only** `?token=` on `/ws` |

The customer token is stored in `expo-secure-store` on device (see `mobile/src/store/secureTokenStorage.ts`). The `ws_session` token is returned fresh from every successful `/qr/claim`; the app should use the latest one and re-claim when it expires or changes session.

---

## QR URL format

Every physical socket has a static QR code pointing at:

```
https://marina.lika.solutions/mobile/socket/{pedestal_id}/{socket_id}
```

- `pedestal_id` may be either a numeric DB id (e.g. `7`) or an `opta_client_id` string (e.g. `MAR_KRK_ORM_01`).
- `socket_id` is one of `Q1`, `Q2`, `Q3`, `Q4`.

The QR contains nothing else — it's a plain URL. Scanning it should open the mobile app's landing route with those two params.

---

## REST endpoints

All endpoints are prefixed `/api/mobile/`. Every endpoint requires the customer JWT in `Authorization: Bearer <token>` unless noted.

### `POST /api/mobile/qr/claim`

Primary scan endpoint. Claims the active session (if one exists) for the caller and returns the view the app should render.

**Request body**

```json
{
  "pedestal_id": "MAR_KRK_ORM_01",
  "socket_id": "Q1"
}
```

**Response 200** — `status` is one of `no_session`, `claimed`, `already_owner`, `read_only`:

```jsonc
// status == "no_session"  — socket idle/pending, user plugged in but no session yet
{
  "status": "no_session",
  "pedestal_id": "MAR_KRK_ORM_01",
  "socket_id": "Q1",
  "socket_state": "idle" | "pending"
}

// status == "claimed"     — socket's unowned session was just claimed
// status == "already_owner" — caller already owned this session
// status == "read_only"   — some other customer owns this session
{
  "status": "claimed",
  "session_id": 4123,
  "pedestal_id": "MAR_KRK_ORM_01",
  "socket_id": "Q1",
  "socket_state": "active",
  "session_started_at": "2026-04-21T12:34:56.789Z",
  "duration_seconds": 12,
  "energy_kwh": 0.042,
  "power_kw": 0.8,
  "is_owner": true,
  "websocket_token": "<short-lived JWT — use on /ws>"
}
```

**Errors**

| Status | When |
|---|---|
| 401 / 403 | Missing / invalid customer token |
| 404 `Pedestal not found` | `pedestal_id` not in DB |
| 404 `Socket not found on this pedestal` | `socket_id` not in `Q1..Q4` |

### `GET /api/mobile/sessions/{session_id}/live`

Polling fallback for when the WebSocket isn't available.

**Response 200**

```json
{
  "session_id": 4123,
  "socket_state": "active",
  "duration_seconds": 245,
  "energy_kwh": 1.8,
  "power_kw": 3.2,
  "last_updated_at": "2026-04-21T12:38:21.000Z"
}
```

**Errors**

- `403` if caller is not the session owner.
- `404` if session does not exist.

### `GET /api/mobile/socket/{pedestal_id}/{socket_id}/qr`

**Admin only** — returns a PNG QR code pointing at the mobile landing URL. Mobile clients must NOT call this (they receive `401/403`). Used by the dashboard to download printable QR stickers.

Response: `image/png` with `Content-Disposition: inline; filename="{pedestal_id}_{socket_id}_qr.png"`.

---

## WebSocket — live telemetry

Connect to `/ws?token=<websocket_token>` using the token from the most recent successful `/qr/claim`. Ping with the text `ping`; the server responds `pong` every 20 s.

All messages are JSON with shape `{ "event": "...", "data": {...} }`. The subscriber receives the following events for its session:

| Event | Payload (`data`) | Fired when |
|---|---|---|
| `session_telemetry` | `session_id, pedestal_id, socket_id, duration_seconds, energy_kwh, power_kw, timestamp` | Firmware emits a `TelemetryUpdate` MQTT event for the socket |
| `socket_state_changed` | `session_id, pedestal_id, socket_id, state (idle/pending/active/fault), resource, timestamp` | Backend computes a new state for the socket |
| `session_ended` | `session_id, pedestal_id, socket_id, energy_kwh, water_liters, ended_at` | Session was completed by operator, UserPluggedOut, or SessionEnded — **server closes the socket after this event** |

The mobile app must handle a server-initiated close after `session_ended` and transition to the session summary screen.

---

## Authority model (important)

- **Monitoring only.** The mobile app has no stop endpoint. `POST /api/customer/sessions/{id}/stop` intentionally returns `403` for every customer-authenticated call.
- **Physical unplug is the customer's only stop mechanism.** Firmware emits `UserPluggedOut` → backend stops the session → `session_ended` event on the WS.
- **Activate** — only when auto-activate is off AND the socket is pending, the mobile app may call `POST /api/customer/sessions/start` (existing endpoint) to start a new session.
- **Operator override.** Admins can stop any session at any time from the dashboard via `POST /api/controls/{session_id}/stop`. Monitors cannot stop.

---

## Session-ownership state model

`Session.customer_id` and `Session.owner_claimed_at` distinguish three cases:

| `customer_id` | `owner_claimed_at` | Meaning |
|---|---|---|
| `NULL` | `NULL` | Unclaimed auto-activated session. `/qr/claim` will set both. |
| `N` | `NULL` | Session was started from the mobile app (`/api/customer/sessions/start`). |
| `N` | `T` | Session was unclaimed and later claimed via QR scan at `T`. |

There is no separate `owner_user_id` column. The spec originally proposed one pointing at the `users` (operator) table — which would always be NULL since operators never scan QR codes. Reusing `customer_id` keeps the data model honest.

---

## Known limitations / TODO — Phase 2

- **Marina access control is intentionally skipped in v3.6.** Any authenticated customer may claim any socket on any pedestal. For a prepaid walk-up model this is the desired behaviour — guarding by marina membership would block paying walk-ins.
  - If a multi-marina rollout requires segmentation later, add `Pedestal.marina_id` + `MarinaCustomerAccess` table + a `_check_marina_access(customer, pedestal)` dependency. Return `403 "You do not have access to this marina"` from `/qr/claim` step 4.
- `/api/mobile/sessions/{id}/stop` does not exist. The spec proposed it but the v3.6 authority decision (mobile = monitoring only) removes it from scope.
- `AutoActivationLog` rows (from v3.5) accumulate without rotation. Not a mobile-API concern but mentioned here for visibility.

---

## Example mobile flow

1. User opens the app — customer JWT from SecureStore is attached to axios.
2. User scans socket QR → deep-link opens `mobile/socket/[pedestal_id]/[socket_id].tsx`.
3. Screen calls `POST /api/mobile/qr/claim`. Response drives the view:
   - `no_session` → show socket state + (if pending) manual Activate button.
   - `claimed` / `already_owner` → connect WS with `websocket_token`, render live meter.
   - `read_only` → same live meter, disabled controls, "managed by another user" banner.
4. WS events update `duration_seconds`, `energy_kwh`, `power_kw` in-place.
5. On `session_ended` the app disconnects the WS (or expects a server close) and shows a summary screen. No stop button anywhere.
