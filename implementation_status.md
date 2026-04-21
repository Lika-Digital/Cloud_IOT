# Implementation Status — External Pedestal API Endpoints (v3.3)

## Session started: 2026-04-11
## Previous feature (CV Extension) — all sections complete. See git log for details.

---

## Current Feature: Three New External API Endpoints + Gateway Health Indicators

### Files — Status

| # | File | Status | Notes |
|---|------|--------|-------|
| 1 | `backend/app/services/api_catalog.py` | COMPLETE | Added 3 catalog entries |
| 2 | `backend/app/routers/ext_pedestal_endpoints.py` | COMPLETE | New file — 3 direct ext routes |
| 3 | `backend/app/routers/pedestal_config.py` | COMPLETE | Extended health endpoint + UserSessionLocal module-level import |
| 4 | `backend/app/main.py` | COMPLETE | ext_pedestal_router included before gateway catch-all |
| 5 | `frontend/src/api/externalApi.ts` | COMPLETE | ExtPedestalHealth type + getExtPedestalHealth() added |
| 6 | `frontend/src/pages/ApiGateway.tsx` | COMPLETE | Health dots + "not enabled" labels + health state |
| 7 | `tests/backend/test_ext_pedestal_endpoints.py` | COMPLETE | 17 tests (TC-EP-01..11 + auth + grab_failure) — 212/212 total |

## Test run result: 212 passed, 0 failed (2026-04-11)

---

## Design Decisions

- New endpoints live at `/api/ext/pedestals/{pedestal_id}/...` as **direct FastAPI routes**
  (NOT proxied through gateway catch-all `ANY /api/ext/{path:path}`).
- Router included in `main.py` BEFORE `ext_api_gateway_router` so specific routes win.
- `pedestal_id` param accepts numeric PK string or opta_client_id string.
- Per-endpoint enable/disable reuses existing `allowed_endpoints` JSON in ExternalApiConfig.
- Returns 503 (not 403) for disabled/unavailable feature per spec.
- Auth failures: 401/403. Gateway globally inactive: 503 "Not enabled".
- Health endpoint extended: each pedestal entry gets `ext_berths_occupancy`,
  `ext_camera_frame`, `ext_camera_stream` with `enabled`, `available`, `reason`.
- Frame grab reuses `berth_analyzer.grab_snapshot()`.
- Catalog IDs: `berths.occupancy_ext`, `camera.frame_ext`, `camera.stream_ext`

---
---

# Implementation Status — Socket Plug State Machine (v3.4)

## Session started: 2026-04-21

Feature scope: extend the socket state flow with a `pending` state driven by
firmware `UserPluggedIn` / `UserPluggedOut` events; broadcast a unified
`socket_state_changed` WebSocket event; reject operator `activate` commands
when no plug is inserted; render yellow pending indicators + pending tooltip
in Control Center and the pedestal picture overlay.

**Approved design decisions (2026-04-21):**
- NO new DB column — state is computed from `SocketState.connected` + active-session lookup and broadcast only.
- `socket_state_changed` is additive; existing `user_plugged_in`, `session_*` events kept for backwards compat.
- Activate rejection uses HTTP 409 + detail `"Socket has no plug inserted"`.
- Water valves out of scope (sockets Q1–Q4 only).
- Pending colour: Tailwind `yellow-400`.

### Files — Status

| # | File | Status | Notes |
|---|------|--------|-------|
| 1 | `implementation_status.md` | IN PROGRESS | Feature header + per-file log |
| 2 | `backend/app/services/mqtt_handlers.py` | COMPLETE | helper `_broadcast_socket_state`, `_set_socket_connected`, new `_handle_event_user_plugged_out`, `UserPluggedOut` dispatcher case, `socket_state_changed` broadcasts from UserPluggedIn/Out, OutletActivated (→active), SessionEnded (→pending|idle) |
| 3 | `backend/app/routers/controls.py` | COMPLETE | `direct_socket_cmd` returns HTTP 409 "Socket has no plug inserted" when `SocketState.connected=False` on activate; imports `status`; de-duplicated `_socket_name_to_id` call |
| 4 | `backend/app/services/api_catalog.py` | COMPLETE | Added `socket_state_changed` entry to EVENT_CATALOG |
| 5 | `frontend/src/store/index.ts` | COMPLETE | Added `socketComputedStates` record + `setSocketComputedState(pedestal_id, socket_id, state)` setter |
| 6 | `frontend/src/hooks/useWebSocket.ts` | COMPLETE | Added `setSocketComputedState` destructure; added `case 'socket_state_changed':` that writes to computed state and syncs pendingSockets |
| 7 | `frontend/src/components/pedestal/PedestalControlCenter.tsx` | COMPLETE | yellow `pending` StateBadge variant; SocketCard prefers `socketComputedStates`; Stop replaces Activate when `active`; Activate disabled unless `pending` with "No plug inserted" tooltip on idle + "Plug inserted — awaiting activation" on pending; CmdButton accepts `title` |
| 8 | `frontend/src/components/pedestal/PedestalView.tsx` | COMPLETE | ZoneButton consumes `socketComputedStates` for electricity sockets; pending ring/bg switched from amber to yellow; tooltip text "Plug inserted — awaiting activation" when pending |
| 9 | `tests/backend/test_socket_plug_state_machine.py` | COMPLETE | 8 test cases (TC-SP-01..07 + extra `activate rejected when no SocketState row` guard) — all green |
| 10 | `tests/backend/test_direct_controls.py` | COMPLETE | Seed SocketState.connected=True before TC-DC-01/02 activate path so activate guard is satisfied |
| 11 | `implementation_status.md` | IN PROGRESS | This file — final entry after release push |

## Test run result: 238 passed, 0 failed (2026-04-21) — 230 existing + 8 new state-machine cases

## Key design outcomes

- Computed state lives in broadcasts + frontend cache only; no new DB column.
- `socket_state_changed` broadcast from: `_handle_event_user_plugged_in` (→pending or active), `_handle_event_user_plugged_out` (→idle), `_handle_event_outlet_activated` (→active), `_handle_event_session_ended` (→pending if connected, else idle).
- Existing `user_plugged_in` / `session_*` events preserved; old clients still work.
- Frontend `pendingSockets` store kept in sync with `socketComputedStates` so legacy `ZoneButton` amber path is still correct until all consumers migrate.
- Activate guard is server-side enforcement: `HTTP 409 "Socket has no plug inserted"`. UI already blocks the click before the request is sent.
- Water valves untouched; spec explicitly scoped to electricity sockets Q1–Q4.
- Pending colour: `yellow-400` (Tailwind `#facc15`).

## WS event catalog drift guard

`tests/backend/test_ws_event_catalog.py` was already configured — `socket_state_changed` added to `EVENT_CATALOG` and also broadcast from code, so the AST drift check passes automatically.

---
---

# Implementation Status — Per-Socket Auto-Activation (v3.5)

## Session started: 2026-04-21

Feature scope: on top of the v3.4 plug state machine, allow operators to flip
a per-socket `auto_activate` toggle. When true, the backend fires the
`activate` command automatically after `UserPluggedIn`, gated by 5 safety
preconditions and a 2-second stabilisation delay. When false, everything
behaves exactly as today (manual Activate click in Control Center).

**Approved design decisions (2026-04-21):**
- Door state persisted as `PedestalConfig.door_state` (string, default `"unknown"`). `unknown` treated same as `open` for auto-activate — safe after restart until firmware confirms `closed`.
- Fault state tracked in a module-level dict inside `mqtt_handlers.py`; no DB column.
- `last_diagnostic_at` also module-level dict, written by the diagnostics router, read by auto-activate check. 60 s window.
- 2-second `asyncio.sleep` before publishing; re-check computed state after sleep — abort if socket is no longer pending (operator manually activated / plug yanked).
- `AutoActivationLog` rows accumulate; no rotation yet.
- No global feature flag; per-socket only.
- Colours: green `AUTO` badge (`text-green-400`), amber skip warning (`text-amber-300 bg-amber-900/30`).

### Files — Status

| # | File | Status | Notes |
|---|------|--------|-------|
| 1 | `implementation_status.md` | IN PROGRESS | This file — header + per-file log |
| 2 | `backend/app/models/pedestal_config.py` | COMPLETE | Added `door_state: Column(String, default="unknown")` — values `open / closed / unknown` |
| 3 | `backend/app/models/socket_config.py` | COMPLETE (NEW) | SocketConfig(id, pedestal_id, socket_id, auto_activate, created_at, updated_at) + UNIQUE(pedestal_id, socket_id) |
| 4 | `backend/app/models/auto_activation_log.py` | COMPLETE (NEW) | AutoActivationLog(id, pedestal_id, socket_id, timestamp, result=success|skipped, reason, session_id) + index on (pedestal_id, socket_id, timestamp) |
| 5 | `backend/app/database.py` | COMPLETE | Register `socket_config` + `auto_activation_log` in `init_db`; add `pedestal_configs.door_state TEXT DEFAULT 'unknown'` to the migration list |
| 6 | `backend/app/services/mqtt_handlers.py` | COMPLETE | Module-level `socket_fault_state` + `last_diagnostic_at` dicts; door_state persisted in `_handle_marina_door`; fault tracking in `_handle_opta_socket`; new `_log_auto_activation`, `_broadcast_auto_activate_skipped`, `_auto_activate_precondition_check`, `_maybe_auto_activate` (all 5 checks + 2s sleep + post-sleep re-check); `_handle_event_user_plugged_in` kicks off the coroutine when SocketConfig.auto_activate is True and computed state is pending; `asyncio` import added |
| 7 | `backend/app/routers/diagnostics.py` | COMPLETE | Writes `last_diagnostic_at[pedestal_id] = utcnow()` immediately before publishing `opta/cmd/diagnostic` — gives auto-activate a 60 s lockout window |
| 8 | `backend/app/routers/pedestal_config.py` | COMPLETE | 3 new endpoints appended — GET `/api/pedestals/{pid}/sockets/config` returns all 4 sockets with default `auto_activate=false`; PATCH `/sockets/{sid}/config` admin-only; GET `/sockets/{sid}/auto-activate-log` returns last 20 newest-first |
| 9 | `backend/app/services/api_catalog.py` | COMPLETE | 3 endpoints (sockets.config_list / config_patch / auto_log) + 1 event (socket_auto_activate_skipped) — keeps AST drift guards green |
| 10 | `frontend/src/api/index.ts` | COMPLETE | `SocketAutoActivateConfig`, `AutoActivateLogEntry` types + `getSocketConfigs`, `setSocketConfig`, `getAutoActivateLog` wrappers |
| 11 | `frontend/src/store/index.ts` | COMPLETE | `socketAutoActivate` + `setSocketAutoActivate`; `socketAutoSkipReasons` + `setSocketAutoSkipReason` + `clearSocketAutoSkipReason` |
| 12 | `frontend/src/hooks/useWebSocket.ts` | COMPLETE | Added `setSocketAutoSkipReason` / `clearSocketAutoSkipReason` destructures; new `case 'socket_auto_activate_skipped':` sets reason + schedules 30 s auto-clear via setTimeout; `case 'socket_state_changed':` now also clears the reason on any transition away from pending |
| 13 | `frontend/src/components/pedestal/PedestalControlCenter.tsx` | COMPLETE | `useEffect` loads `getSocketConfigs` on open; optimistic `onAutoActivateChange` via `setSocketConfig` with rollback; SocketCard gains `autoActivate` / `autoSkipReason` / `onAutoActivateChange` props; green `AUTO` badge next to socket id; auto-activate toggle with loading guard and ✓ indicator; amber skip-reason banner below status block; pending tooltip switches to "Plug inserted — auto-activating in 2s" when `autoActivate === true`; manual Activate fallback preserved |
| 14 | `frontend/src/components/pedestal/PedestalView.tsx` | COMPLETE | ZoneButton reads `socketAutoActivate[key]`; tooltip for pending state switches to "Plug inserted — auto-activating in 2s" when enabled, else "Plug inserted — awaiting activation" |
| 15 | `tests/backend/test_socket_auto_activate.py` | COMPLETE (NEW) | 10 cases: default false, PATCH admin-only, auto=False no publish, auto=True publishes after delay + success log, 4 parametrised skip paths (door open, fault, heartbeat stale, diagnostic running), already-active skip, log endpoint returns 20 newest-first with correct shape |
| 16 | `tests/backend/conftest.py` | COMPLETE | Import `socket_config` + `auto_activation_log` so `Base.metadata.create_all` builds the test tables |

## Test run result: 248 passed, 0 failed (2026-04-21) — 238 existing + 10 new auto-activate cases. Drift guards pass (new event + 3 new endpoints registered in api_catalog).

## Key design outcomes

- No new DB column beyond `pedestal_configs.door_state` and the two new tables (`socket_configs`, `auto_activation_log`).
- Fault + diagnostic tracking via module-level dicts in `mqtt_handlers.py` — process-local state for a single uvicorn worker, no DB churn.
- `_handle_event_user_plugged_in` ALWAYS invokes `_maybe_auto_activate` when the flag is set (even when computed state is already active) so the "already active" skip is audited rather than silent.
- 2-second stabilisation sleep happens ONLY after the first precondition pass — fast-fail bad configurations without waiting.
- Post-sleep re-check guards against operator race (manual activate) and plug removal during the window.
- Every decision (success or each skip reason) writes one row to `auto_activation_log`; log keeps unbounded growth for now.
- Frontend toggle updates optimistically; rollback on PATCH failure.
- Warning auto-clears after 30 s OR on any transition away from pending (whichever comes first).

---
---

# Implementation Status — QR-Code Mobile Session Ownership + Real-Time Monitoring (v3.6)

## Session started: 2026-04-21

Feature scope: customer scans the QR on a physical socket → backend claims the
existing active session for that customer → mobile app shows real-time kWh /
kW / duration via per-session WebSocket. Customer app is **monitoring only** —
customer has no stop capability anywhere. Operator keeps absolute SW control
from the dashboard (admin role only for stop/override). Physical unplug via
UserPluggedOut remains the customer's only way to end a session.

**Approved design decisions (2026-04-21):**
- DB: reuse existing `Session.customer_id`; add **only** `owner_claimed_at`. Do not add `owner_user_id`.
- Customer stop is removed — `/api/customer/sessions/{id}/stop` returns 403 for customer role. No `/api/mobile/sessions/{id}/stop` endpoint at all.
- New `/api/mobile/` router for genuinely new endpoints only: `qr/claim`, `sessions/{id}/live`, `socket/{pid}/{sid}/qr`.
- Marina access control skipped; any authenticated customer may claim any socket. Phase-2 TODO in docs/mobile_api.md.
- Operator override authority = `admin` role only. `monitor` stays read-only.
- WebSocket token: 1-hour JWT, re-issued on re-claim.
- `qrcode[pil]` added to backend/requirements.txt.

### Files — Status

| # | File | Status | Notes |
|---|------|--------|-------|
| 1 | `implementation_status.md` | IN PROGRESS | Feature header + per-file log (this) |
| 2 | `backend/app/models/session.py` | COMPLETE | Added `owner_claimed_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)` — reuses `customer_id` per design decision |
| 3 | `backend/app/database.py` | COMPLETE | Added `("sessions", "owner_claimed_at", "DATETIME")` to `_migrate_schema` migration list |
| 4 | `backend/requirements.txt` | COMPLETE | `qrcode[pil]==8.0` added; smoke-tested PNG generation (468 bytes) |
| 5 | `backend/app/routers/customer_sessions.py` | COMPLETE | `POST /api/customer/sessions/{id}/stop` now raises 403 for every customer-authenticated call — monitoring-only model enforced at the router. Original handler body kept unreachable for future re-enable reference. |
| 6 | `backend/app/services/websocket_manager.py` | COMPLETE | `_session_subs: dict[int, set[WebSocket]]`; `subscribe_to_session`, `unsubscribe_from_session`, `broadcast_to_session(session_id, message, close_after=False)`. `disconnect()` now also removes the socket from all session sub-sets. `session_subscriber_count` property for metrics / tests. |
| 7 | `backend/app/routers/websocket.py` | COMPLETE | `/ws` now recognises `role="ws_session"` tokens (new). Extracts `session_id` claim and calls `subscribe_to_session`. Customer and anonymous modes unchanged for backwards compat. |
| 8 | `backend/app/auth/tokens.py` | COMPLETE | `create_websocket_token(session_id, customer_id)` — 1h TTL, `role="ws_session"`, includes `session_id` claim. Distinct role so the token cannot be reused against long-lived customer APIs. |
| 9 | `backend/app/routers/mobile.py` | COMPLETE (NEW) | `POST /qr/claim` branches to claimed / already_owner / read_only / no_session; `GET /sessions/{id}/live` owner-only 403 guard; `GET /socket/{pid}/{sid}/qr` admin-only PNG generation (qrcode box_size=10, ERROR_CORRECT_M); helper functions for pedestal resolve + socket validation; marina-access TODO inline comment. |
| 10 | `backend/app/services/mqtt_handlers.py` | COMPLETE | `_handle_event_telemetry_update` emits `session_telemetry` via `broadcast_to_session` (carrying duration/kwh/kw); `_handle_event_session_ended` pushes `session_ended` to subscribers with `close_after=True`; `_broadcast_socket_state` also fans out to the session channel when an active session exists for the socket |
| 11 | `backend/app/main.py` | COMPLETE | Imports `mobile` router and `app.include_router(mobile_router.router)` after customer_auth group |
| 12 | `backend/app/services/api_catalog.py` | COMPLETE | 3 endpoints (`mobile.qr_claim`, `mobile.session_live`, `mobile.socket_qr`) + 2 events (`session_telemetry`, `session_ended`) added; drift guards pass |
| 12a | `tests/backend/test_ws_event_catalog.py` | COMPLETE | `session_telemetry` + `session_ended` added to `INTERNAL_EVENTS` since they're per-session pushes only, not consumed by the dashboard switch |
| 12b | `tests/backend/test_sessions.py` | COMPLETE | `test_stop_session` now asserts 403 + tidies up via `_complete_session_direct`; cleanup calls in other tests swapped for direct DB writes |
| 12c | `tests/backend/test_workflow.py` | COMPLETE | Bulk-replaced 7 customer-stop cleanup calls with new `_complete_via_db` helper; `test_tc_stop_01` updated to assert 403 + admin-stop path; `test_tc_workflow_01` step 7 uses admin stop |
| 12d | `tests/backend/test_gap_session_fields.py` | COMPLETE | 3 customer-stop cleanup calls swapped for `_complete_via_db_gap` helper |
| 12e | `tests/backend/test_operator_approval.py` | COMPLETE | 6 customer-stop cleanup calls swapped for `_complete_via_db_op` helper |
| 12f | `tests/backend/_session_helpers.py` | COMPLETE (NEW) | Shared `complete_session` / `complete_all_active_for_pedestal` helpers |
| 13 | `frontend/src/components/pedestal/PedestalControlCenter.tsx` | COMPLETE | Each SocketCard now shows a 📱 icon with a "Mobile owner: {name}" tooltip when the active session has a customer_id; a new `QR` button opens a modal that fetches `GET /api/mobile/socket/{pid}/{sid}/qr`, renders the PNG, shows the encoded URL, and has a Download button that saves as `{pid}_{socketName}_qr.png`. New `getSocketQrBlob` helper added in `frontend/src/api/index.ts`. |
| 14 | `mobile/app/(app)/mobile/socket/[pedestal_id]/[socket_id].tsx` | COMPLETE (NEW) | QR landing screen, 4 view states (loading / no_session / claimed / read_only / ended); WebSocket subscribe with `websocket_token`; REST polling fallback every 5 s; session_ended → summary screen. No Stop button anywhere — monitoring only. |
| 15 | `mobile/src/api/mobile.ts` | COMPLETE (NEW) | `qrClaim` + `sessionLive` wrappers + response types |
| 16 | `docs/mobile_api.md` | COMPLETE (NEW) | Full contract: base URLs, auth model (customer JWT vs ws_session JWT), QR URL format, 3 REST endpoints with request/response schemas + error matrix, WebSocket event catalog (`session_telemetry`, `session_state_changed`, `session_ended`), authority model explaining monitoring-only, `owner_claimed_at` semantics table, Phase-2 marina-access TODO |
| 17 | `tests/backend/test_mobile_qr_claim.py` | COMPLETE (NEW) | 14 cases covering: auth, 404 pedestal/socket, no_session branch, claimed / already_owner / read_only paths, owner_claimed_at persistence, websocket_token validity + session_id claim, live endpoint owner 200 / non-owner 403, admin QR PNG + customer 403, TelemetryUpdate → `session_telemetry` fan-out, SessionEnded → `session_ended` + channel close. Reuses shared conftest. |
| 18 | `README.md` | PENDING | Changelog v3.6 entry |





