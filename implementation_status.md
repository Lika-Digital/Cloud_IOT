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


