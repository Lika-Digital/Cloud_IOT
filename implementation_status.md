# Implementation Status — Smart Circuit Breaker Monitoring + Remote Reset (v3.8)

## Session started: 2026-04-24

Feature scope: subscribe to `opta/breakers/+/status` and handle new `BreakerTripped`
event on `opta/events`; persist breaker state + metadata on `SocketConfig`; log every
trip/reset into new `breaker_events` table; stop active power session on trip with
`end_reason="breaker_trip"`; expose internal admin endpoints and a parallel ERP
external API for breaker status, history, reset, and marina-wide active alarms;
Control Center gains a red alarm banner + per-socket SocketBreakerPanel with Hardware
Info, Reset button (with confirmation + 15 s timeout), and history modal; PedestalView
gains a ⚡ overlay on tripped circles; `breaker_alarm` is webhookable to ERP.

**Approved design decisions (2026-04-24):**
- URL params use numeric `{socket_id}` (1–4); internal conversion to `Q{n}` for MQTT.
- New breaker UI extracted to `SocketBreakerPanel.tsx` to keep SocketCard bounded.
- Alarm banner state: Zustand in-memory; acknowledgements kept in `sessionStorage`.
- Metadata merge: only write keys present in the payload — never overwrite with null.
- BreakerTripped affects power sessions only. Water sessions never touched.
- Breaker history modal uses a new `GET /api/pedestals/{pid}/sockets/{sid}/breaker/history?limit=10`.
- Reset button 15 s watchdog on the frontend; error toast if still tripped after timeout.
- Lightning bolt on socket circle uses emoji `⚡` (matches existing `📷` convention).
- Browser Notification on `breaker_alarm` for admin role only (mirrors `session_created`).
- `breaker_trip_count` is cumulative forever — never auto-reset.
- ERP routes follow v3.3 pattern — direct FastAPI routes registered in `main.py`
  before the `ext_api_gateway_router` catch-all.
- Socket id taken from MQTT topic path on `opta/breakers/{socket_id}/status`;
  payload `socketId` is only a sanity check.
- New `docs/firmware_requirements.md` captures the retained-MQTT recommendation
  for breaker status so the Arduino team publishes with retain flag.
- API Gateway UI groups the 5 new endpoints automatically via
  `category: "Breaker Management"` on each catalog entry. No hand-written JSX.
- Release flow: push develop with normal test gate, pause for explicit user
  approval, then merge and push main with `CLOUD_IOT_RELEASE=1`.
- `breaker_alarm` registered with `webhook: True` so ERP gets push on trip.
- `breaker_reset_sent` event dropped from EVENT_CATALOG — the state transition
  to `resetting` already broadcasts `breaker_state_changed`, so a separate
  event would be redundant and trip the drift guard.
- No SNMP trap. No mobile app changes.

### Files — Status

| # | File | Status | Notes |
|---|------|--------|-------|
| 1 | `backend/app/models/socket_config.py` | COMPLETE | Added 9 breaker columns: breaker_state, breaker_last_trip_at, breaker_trip_cause, breaker_trip_count, breaker_type, breaker_rating, breaker_poles, breaker_rcd, breaker_rcd_sensitivity |
| 2 | `backend/app/models/breaker_event.py` | COMPLETE | New model + table; indexed on (pedestal_id, socket_id, timestamp) |
| 3 | `backend/app/models/session.py` | COMPLETE | Added `end_reason: Mapped[str]` nullable 64-char column |
| 4 | `backend/app/database.py` | COMPLETE | Added breaker_event import + 10 migration entries (9 socket_configs + 1 sessions.end_reason) |
| 5 | `backend/app/services/mqtt_client.py` | COMPLETE | Added `opta/breakers/+/status` to TOPICS |
| 6 | `backend/app/services/session_service.py` | COMPLETE | `complete()` accepts optional `end_reason` kwarg; writes to `Session.end_reason` |
| 7 | `backend/app/services/mqtt_handlers.py` | COMPLETE | OPTA_BREAKER_RE + dispatch branch; `_handle_opta_breaker_status` (upsert SocketConfig, increment trip_count on fresh trip, metadata merge preserving nulls, broadcast `breaker_state_changed`); `_handle_event_breaker_tripped` (breaker_events log, stop power session with end_reason="breaker_trip", broadcast `session_completed` + `breaker_alarm`) |
| 8 | `backend/app/routers/breakers.py` | COMPLETE | New router: POST /reset (admin), GET status + socket history (default 10) + pedestal history (50). Shared helpers `get_cabinet_id`, `publish_breaker_reset`, `serialize_breaker_status`, `serialize_event`, `perform_breaker_reset`, `broadcast_resetting` reused by ERP router |
| 9 | `backend/app/routers/ext_breaker_endpoints.py` | COMPLETE | 5 ERP routes: breakers list, single-socket + 5 events, POST reset (initiated_by="erp-service"), pedestal history, marina_id alarm aggregator. Reuses shared helpers from breakers.py |
| 10 | `backend/app/main.py` | COMPLETE | Imports + include_router for breakers_router and ext_breaker_router (the latter before ext_api_gateway_router catch-all) |
| 11 | `backend/app/services/api_catalog.py` | COMPLETE | Added 5 ENDPOINT_CATALOG entries (all `category: "Breaker Management"`) + 3 EVENT_CATALOG entries (breaker_state_changed, breaker_alarm, breaker_reset_sent). Events flow through existing dispatch_webhook hook — no additional wiring required |
| 12 | `frontend/src/store/index.ts` | COMPLETE | Added `socketBreakerStates` + `setBreakerState` (partial-patch merge, never overwrites with null); `activeBreakerAlarms` list + `addBreakerAlarm` / `clearBreakerAlarm` / `acknowledgeBreakerAlarm`. Acknowledgements persist to `sessionStorage['ackedBreakerAlarms']` per D3 |
| 13 | `frontend/src/hooks/useWebSocket.ts` | COMPLETE | Destructured `setBreakerState`, `addBreakerAlarm`; added `breaker_state_changed` case (partial-patch update + auto-clear banner on `closed`) and `breaker_alarm` case (adds key + admin-only Notification) |
| 14 | `frontend/src/api/breakers.ts` | COMPLETE | Typed client: BreakerStatus + BreakerEvent types; `getSocketBreakerStatus`, `getSocketBreakerHistory` (limit default 10), `getPedestalBreakerHistory`, `postBreakerReset` |
| 15 | `frontend/src/components/pedestal/SocketBreakerPanel.tsx` | COMPLETE | New component: status dot + label, Hardware Info block (type, rating, poles, RCD, sensitivity, trips, cause — all fallback to "Not reported"), admin-only Reset with inline confirm dialog + 15 s timeout watchdog, History button opens modal. 409 surfaces "Breaker is not in tripped state" toast |
| 16 | `frontend/src/components/pedestal/BreakerHistoryModal.tsx` | COMPLETE | Modal fetches /api/pedestals/{pid}/sockets/{sid}/breaker/history?limit=10, renders event list with colour-coded event_type, shows trip_cause + current_at_trip + operator/erp-service badge |
| 17 | `frontend/src/components/pedestal/PedestalControlCenter.tsx` | COMPLETE | Import SocketBreakerPanel; mount inside SocketCard (after autoSkipReason, before admin controls); destructure activeBreakerAlarms + acknowledgeBreakerAlarm; red alarm banner at top (after feedback toasts) lists tripped `Q{n}` sockets on THIS pedestal, Acknowledge button dismisses via sessionStorage |
| 18 | `frontend/src/components/pedestal/PedestalView.tsx` | COMPLETE | Destructure `socketBreakerStates`; compute `breakerTripped` for electricity sockets; render red ⚡ overlay top-right of the button when tripped. Existing ring/bg colour logic untouched |
| 19 | `tests/backend/test_breaker_monitoring.py` | COMPLETE | 21 tests (TC-BR-01..21) covering MQTT parse + no-null-overwrite + trip-count + BreakerTripped session stop + WS broadcasts + internal 409/publish/audit + ERP 409/publish/audit + invalid token + list / socket 5 events / history 50 / marina alarms / catalog registration |
| 20 | `tests/backend/conftest.py` | COMPLETE | Added breaker_event model import so tables are created in the test DB |
| 21 | `frontend/e2e/breaker.spec.ts` | COMPLETE | Playwright — Hardware Info "Not reported" default; Reset button hidden for monitor, visible for admin only when tripped, hidden when closed; alarm banner shows Q{n} label when socket is tripped. Store seeding via `window.__APP_STORE__` (see note for wiring) |
| 22 | `docs/firmware_requirements.md` | COMPLETE | New doc captures the v3.8 retain-flag recommendation for `opta/breakers/+/status` per D13; lists every currently-contracted topic with retain flag for cross-team reference |
| 23 | `frontend/src/store/index.ts` (touched again) | COMPLETE | Exposed `useStore` as `window.__APP_STORE__` at module end so Playwright can seed breaker state without waiting for the mocked WebSocket |
| 24 | `README.md` | COMPLETE | Newest-first v3.8 changelog entry — MQTT topic, internal endpoints, 5 ERP endpoints, WS events, UI features, test delta 275 → 292, Wire: list |

## Test run result: 292 passed, 0 failed (2026-04-24) — 271 pre-existing + 21 new breaker cases (test counts include TC-BR-01..21)

## Pending before release
- Run Playwright e2e locally (`tests/playwright_e2e.sh`) — backend suite already green.
- Commit on develop with full test gate.
- PAUSE for explicit user approval before merging to main.

---

---

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
| 18 | `README.md` | COMPLETE | Changelog v3.6 entry added; test count 262; WS events table updated with `session_telemetry` / `session_ended` mobile-only rows |

## Test run result: 262 passed, 0 failed (2026-04-21) — 248 v3.5 + 14 new mobile QR cases. Released as `c515790` to `origin/main` + `origin/develop`.

---
---

# Implementation Status — Auto-Discovery + QR Grid (v3.7)

## Session started: 2026-04-21

Feature scope: MQTT messages Opta already publishes should now auto-create
database rows for new pedestals and sockets (no manual registration), and
every socket should have a printable QR PNG on disk ready to download. The
dashboard adds a QR Codes section to Control Center and a QR icon on the
pedestal cards.

**Approved design decisions (2026-04-21):**
- Reuse existing `PedestalConfig.last_heartbeat` as `last_seen_at`. Add only `first_seen_at: DateTime` and `status: String` columns.
- Do NOT add `GET /api/pedestals/{cab}/sockets/{sid}/qr` — v3.6's `GET /api/mobile/socket/{pid}/{sid}/qr` already covers it. Only new endpoints: `GET /api/pedestals/{cab}/qr/all` (ZIP) + `POST /api/pedestals/{cab}/qr/regenerate` (admin).
- QR PNG text label is embedded only in the new disk-cached PNG. The v3.6 on-demand endpoint stays byte-identical.
- `pedestal_registered` WS event throttled to one per pedestal per 60 s so reconnect storms don't spam the dashboard.
- Tiny in-house toast component (no external lib) — single global slice in the store.
- New QR Codes section lives at the **top** of Control Center, above the cabinet-status card. Does NOT touch event log / ack log / diagnostic / health sections.
- QR icon on both `PedestalCard.tsx` grid view and the sidebar list item.

### Files — Status

| # | File | Status | Notes |
|---|------|--------|-------|
| 1 | `implementation_status.md` | IN PROGRESS | Feature header + per-file log |
| 2 | `backend/app/models/pedestal_config.py` | COMPLETE | Added `first_seen_at: Column(DateTime, nullable=True)` + `status: Column(String, nullable=True, default="online")`. Comment on `last_heartbeat` clarifies it plays the last_seen_at role per the v3.7 design decision. |
| 3 | `backend/app/database.py` | COMPLETE | Added two rows to the `_migrate_schema` migrations list: `pedestal_configs.first_seen_at DATETIME` + `pedestal_configs.status TEXT DEFAULT 'online'`. Safe idempotent ALTER per existing pattern. |
| 4 | `backend/app/services/qr_service.py` | COMPLETE (NEW) | Functions: `generate_socket_qr` (idempotent), `regenerate_socket_qr`, `get_socket_qr_path`, `generate_all_qr_for_pedestal`, `delete_all_qr_for_pedestal`, `qr_dir`. 300×300 PNG with 50px text label beneath (`{cabinet_id_spaced} — {socket_id}`). Target dir `backend/static/qr/` auto-created on import. TTF fallback to Pillow default font. Smoke-tested. |
| 5 | `backend/app/services/mqtt_handlers.py` | COMPLETE | `_cabinet_to_pedestal_id` now prettifies `name` + sets `first_seen_at`/`status` on new PedestalConfig + schedules `_announce_new_pedestal` (QR pre-gen + `pedestal_registered is_new=True`). New `_announce_pedestal_heartbeat` with 60s throttle called from `_handle_opta_status`. New `_auto_discover_socket_config` idempotently creates SocketConfig from `_handle_marina_socket` and triggers per-socket QR PNG generation on first sight. All QR/DB failures caught + logged; MQTT flow never crashes. |
| 6 | `backend/app/routers/qr.py` | COMPLETE (NEW) | Two admin-only endpoints: `GET /api/pedestals/{cab}/qr/all` (zip with 4 PNGs, `Content-Disposition: attachment; filename="{cab}_qr_codes.zip"`, auto-generates missing files) and `POST /api/pedestals/{cab}/qr/regenerate` (deletes + rebuilds, returns summary). Resolves by `opta_client_id` string, 404 on unknown cabinet. |
| 7 | `backend/app/main.py` | COMPLETE | Imports + registers `qr_router.router`. The `qr_service` module auto-creates `backend/static/qr/` on import, so no additional startup hook is needed. |
| 8 | `backend/app/services/api_catalog.py` | COMPLETE | `qr.pedestal_all` + `qr.pedestal_regenerate` endpoints added; `pedestal_registered` event added to EVENT_CATALOG. |
| 9 | `frontend/src/api/index.ts` | COMPLETE | `getPedestalQrAll(cabinetId) → Blob` and `regeneratePedestalQrs(cabinetId) → RegenerateResponse` wrappers added alongside the existing v3.6 `getSocketQrBlob`. |
| 10 | `frontend/src/store/index.ts` | COMPLETE | Global `toasts` slice with `addToast` (dedupes by id) + `removeToast`. Variants: info/success/warning/error. Supports optional `actionLabel` + `actionHref` for the "View" link on new-pedestal notifications. |
| 11 | `frontend/src/hooks/useWebSocket.ts` | COMPLETE | `case 'pedestal_registered':` adds an info toast only when `is_new=true`; dedupes via id `pedestal-registered-{cab}`. Reconnect heartbeats (`is_new=false`) are no-ops. |
| 12 | `frontend/src/components/ui/ToastContainer.tsx` | COMPLETE (NEW) | ~40-line self-contained renderer; bottom-right stack; 10 s auto-dismiss; optional action link for "View"; mounted once in `Layout.tsx`. |
| 13 | `frontend/src/components/pedestal/PedestalControlCenter.tsx` | COMPLETE | New collapsible `QrCodesSection` (+ inner `QrCell`) placed above the existing Cabinet Status card. 2×2 grid reuses v3.6's `getSocketQrBlob` endpoint per socket. Top-right buttons: Download All (calls `getPedestalQrAll`, saves `{cab}_qr_codes.zip`) and Regenerate (admin-only, calls `regeneratePedestalQrs` then bumps a nonce to refetch all 4 PNGs). Each cell has Download + Copy URL buttons. Untouched: event log, ack log, diagnostic panels. |
| 13a | `frontend/src/api/pedestalConfig.ts` + `src/store/index.ts` | COMPLETE | `PedestalHealth` type extended with `opta_client_id` so the QR section can resolve the cabinet id from the already-loaded health map (no extra fetch). |
| 13b | `backend/app/routers/pedestal_config.py` | COMPLETE | `/api/pedestals/health` response now includes `opta_client_id` per pedestal. |
| 14 | `frontend/src/components/pedestal/PedestalCard.tsx` | COMPLETE | Added a 🔖 QR icon button (shown when health has `opta_client_id`) that opens a `PedestalQrGridModal` without triggering the card's onClick. Modal reuses the new shared `SocketQrGrid` and has its own Download All button. Copy-URL feedback goes through the global toast store. |
| 14a | `frontend/src/components/pedestal/SocketQrGrid.tsx` | COMPLETE (NEW) | Shared 4-socket QR grid extracted so Control Center and the dashboard modal both reuse it (fixes DRY with the earlier inline `QrCell` duplicate). |
| 15 | `tests/backend/test_pedestal_auto_discovery.py` | COMPLETE (NEW) | 13 cases: pedestal auto-create + name prettification + operator-rename survival + last_heartbeat bump; socket auto-config creation + auto_activate=true preservation; QR PNG write on first socket + idempotency on repeat; `/qr/all` zip structure + content-disposition + PNG magic check; `/qr/regenerate` mtime proof; 404 on unknown cabinet; `pedestal_registered` is_new=true/false + 60 s throttle. `clean_fs` fixture wipes SocketConfig + PNG files to guarantee first-contact semantics across runs. |
| 16 | `README.md` | COMPLETE | Changelog v3.7 entry at top per the merge-to-main rule; test count bumped 262 → 275; WebSocket events table gains `pedestal_registered`; Test Suite bullet added for auto-discovery coverage. |

## Test run result: 275 passed, 0 failed (2026-04-21) — 262 v3.6 + 13 new auto-discovery cases. Ready for release.






