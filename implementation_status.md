# Implementation Status — 90% Auto-Stop Overload Protection (v3.12)

## Session started: 2026-04-30

Feature scope: extends the v3.11 load monitoring with a third threshold tier
at 90% of `rated_amps` that triggers an **automatic socket stop** without
operator action. When meter telemetry crosses 90%, the backend ends the
active session with `end_reason="auto_stop_overload"`, publishes a stop
command on `opta/cmd/socket/Q{n}`, raises a persistent alarm in
`meter_load_alarms` with `alarm_type="auto_stop"`, sets a new
`SocketConfig.auto_stop_pending_ack` latch that blocks all re-activation
paths (manual + auto), and broadcasts `meter_load_auto_stop`. The latch
only clears when an admin calls a new socket-scoped acknowledge endpoint
(internal + ERP variants). 60% / 80% behaviour is untouched.

**Approved design decisions (2026-04-30):**
- D1 — auto-stop is **terminal**. `meter_load_status` stays `auto_stop`
  until the acknowledge endpoint is called. Load dropping below 90%
  does NOT auto-clear.
- D2 — dedicated 90% branch at the **top** of the threshold logic in
  `_handle_opta_meter_telemetry`. Existing 60%/80% state machine
  completely untouched. When `prev_status == "auto_stop"` the handler
  is a no-op for that tick.
- D3 — reuse `meter_load_alarms` table; new `alarm_type="auto_stop"`.
- D4 — socket-scoped acknowledge endpoint:
  `POST /api/pedestals/{pedestal_id}/sockets/{socket_id}/load/auto-stop/acknowledge`.
  Looks up the latest unack'd auto-stop alarm row internally.
- D5 — acknowledge is one atomic transaction: clears
  `auto_stop_pending_ack` AND acks the alarm row.
- D7 — ERP path records `acknowledged_by="erp-service"` (literal string).
- D8 — `_maybe_auto_activate` in mqtt_handlers also guards on
  `auto_stop_pending_ack`; logs `"Auto-activation skipped: overload
  alarm pending acknowledgment"`.
- D9 — extend `LoadStatus` union with `'auto_stop'`. TypeScript compile
  errors force every render path to handle it explicitly.
- D10 — no pre-push hook changes; existing `tests/run_tests.sh`
  auto-discovers new cases.

### Files — Status

| # | File | Status | Notes |
|---|------|--------|-------|
| 1 | `backend/app/models/socket_config.py` | COMPLETE | Added `auto_stop_pending_ack: Boolean(nullable=False, default=False)` after `load_critical_threshold_pct`. New latch gates re-activation until admin acknowledges 90%-threshold auto-stop. Cleared only by ack endpoint, never by load dropping below 90%. |
| 2 | `backend/app/database.py` | COMPLETE | Appended migration entry `("socket_configs", "auto_stop_pending_ack", "INTEGER NOT NULL DEFAULT 0")` to `_migrate_schema()`. Idempotent ALTER TABLE for existing pedestal.db installations. |
| 3 | `backend/app/services/mqtt_handlers.py` | COMPLETE | (a) `_auto_activate_precondition_check` got 6th check returning `"overload alarm pending acknowledgment"` when `SocketConfig.auto_stop_pending_ack` is True (D8). (b) `_handle_opta_meter_telemetry` restructured around prev_status: terminal `auto_stop` short-circuit + new top-level `load_pct >= 90` branch executing Steps 1-7 atomically. Existing 60%/80% state machine moved into `else` branch — bytes-equal to the v3.11 version. New broadcast loop branches handle `session_completed` (pre-built dict) and `meter_load_auto_stop` (severity=AUTO_STOP + session_id). Also resolves any open warning/critical alarm rows with reason="auto-stop-supersedes" to keep alarm history consistent. |
| 3a | `tests/backend/test_meter_load.py` | COMPLETE | Added test_seed_active_session helper, _capture_mqtt_publishes helper, plus 10 new cases (TC-ML-31..40 + auto-stop-supersedes). Updated `_reset_state` autouse fixture to also wipe leftover sessions and clear `auto_stop_pending_ack` between tests. |
| 3b | `tests/backend/test_ws_event_catalog.py` | TEMP-EDIT | `meter_load_auto_stop` and `meter_load_auto_stop_acknowledged` added to INTERNAL_EVENTS with a comment marking them as "in-progress wire-up — remove in Step 7". Test guard otherwise blocks broadcast-without-handler. |
| 4 | `backend/app/routers/controls.py` | COMPLETE | Two guards added: `approve_socket` (admin approve flow) and `direct_socket_cmd` (admin direct activate). Both raise 409 with "Socket was automatically stopped due to overload. Acknowledge the alarm before re-activating." Stop action in direct_socket_cmd intentionally NOT guarded — operator can always stop a socket. Tests TC-ML-41..45 added (5 cases) covering both endpoints + the D8 auto-activate path. |
| 5 | `backend/app/routers/meter_load.py` | COMPLETE | Added `POST /{pedestal_id}/sockets/{socket_id}/load/auto-stop/acknowledge`. Helper `perform_auto_stop_acknowledge(db, pedestal_id, socket_id, actor_label)` shared with the ERP router (Step 5). Atomic transaction (D5): clears `auto_stop_pending_ack`, marks the most recent open auto-stop alarm row acknowledged (with admin email), reclassifies `meter_load_status` from current load_pct (treats prev_status as "unknown" — no hysteresis carryover so the operator's ack is a clean restart). Returns 409 when no auto-stop is pending. Broadcasts `meter_load_auto_stop_acknowledged` with payload {pedestal_id, socket_id, alarm_id, acknowledged_by, acknowledged_at, load_status, timestamp}. Returns `{"status": "acknowledged", "socket_id": socket_id}`. ws_manager moved to module-level import. Tests TC-ML-46..50 added (5 cases). |
| 6 | `backend/app/routers/ext_meter_load_endpoints.py` | COMPLETE | Added `POST /api/ext/pedestals/{pedestal_id}/sockets/{socket_id}/load/auto-stop/acknowledge`. Reuses `perform_auto_stop_acknowledge` helper from meter_load.py. Records `acknowledged_by="erp-service"` per D7. Same broadcast event as internal endpoint so dashboards update in real time regardless of channel. New `_EP_AUTO_STOP_ACK = "load.auto_stop_ack_ext"` constant + per-endpoint toggle. Module-level ws_manager import. Tests TC-ML-51..53 (3 cases) for ack-records-erp-service, 503 when toggle disabled, 401 missing auth. |
| 7 | `backend/app/services/api_catalog.py` | COMPLETE | Added `load.auto_stop_ack_ext` ENDPOINT_CATALOG entry (POST, allow_bidirectional=True, category="Load Monitoring") + 2 EVENT_CATALOG entries (`meter_load_auto_stop`, `meter_load_auto_stop_acknowledged`, both category="Load Monitoring"). Drift-guard tests TC-ML-54/55 (2 cases) confirm registration. Catalog AST drift guard in test_ws_event_catalog.py automatically picks up the events because backend now broadcasts them and frontend now handles them. |
| 8 | `frontend/src/api/meterLoad.ts` | COMPLETE | LoadStatus union extended to `'normal' \| 'warning' \| 'critical' \| 'auto_stop' \| 'unknown'` per D9. MeterLoadAlarm.alarm_type union extended with `'auto_stop'`. New `acknowledgeAutoStop(pedestalId, socketId)` axios helper hitting the internal endpoint. |
| 9 | `frontend/src/store/index.ts` | COMPLETE | LoadStatus union extended in socketLoadStates type. New `autoStopPendingAck: Record<string, boolean>` + `pendingAutoStopAlarms: Array<{key, pedestal_id, socket_id, current_amps, rated_amps, load_pct, session_id, triggered_at}>`. Actions: setAutoStopPendingAck, addAutoStopAlarm (also strips superseded warning/critical alarm keys), acknowledgeAutoStopAlarm (drops from pending list + clears latch). |
| 10 | `frontend/src/hooks/useWebSocket.ts` | COMPLETE | New cases `meter_load_auto_stop` (calls addAutoStopAlarm + admin Browser Notification with ⚡ emoji) and `meter_load_auto_stop_acknowledged` (calls acknowledgeAutoStopAlarm). Destructured both new actions from useStore. |
| 10a | `frontend/src/components/pedestal/SocketLoadMeterPanel.tsx` | PARTIAL (Step 7) | Added `auto_stop` entries to STATUS_BAR_COLOR / STATUS_TEXT / STATUS_BADGE_CLASS so the type-strict Record satisfies the new union member. Banner + Acknowledge UI to be added in Step 8. |
| 10b | `tests/backend/test_ws_event_catalog.py` | COMPLETE (revert) | Removed the temporary INTERNAL_EVENTS marker for the two auto-stop events now that frontend has real `case` handlers. Drift guard back to its v3.11 strict semantics. |
| 11 | `frontend/src/components/pedestal/SocketLoadMeterPanel.tsx` | COMPLETE | Reads `autoStopPendingAck[key]` and `pendingAutoStopAlarms` from store. New banner block (rendered when latch=true) with "⚡ AUTO-STOP — OVERLOAD PROTECTION ACTIVATED" headline, current/rated amps + load_pct text, "Investigate the load before re-activating." reminder, and admin-only "Acknowledge & Enable Re-activation" button. Click triggers a window.confirm with the spec's exact safety copy ("Are you sure you want to acknowledge this overload alarm? Ensure the boat has reduced its power consumption before re-activating the socket."), then POSTs to the acknowledge endpoint and optimistically calls acknowledgeAutoStopAlarm in the store. STATUS_BAR_COLOR/STATUS_TEXT/STATUS_BADGE_CLASS already extended in Step 7; the badge now also shows ⚡ icon when status === 'auto_stop'. |
| 12 | `frontend/src/components/pedestal/PedestalControlCenter.tsx` | COMPLETE | Activate button discovered here (D6 resolved). Reads `autoStopPendingAck[${pedestalId}-${socketId}]` from store. `disabled` extended to `!isPending \|\| loading \|\| autoStopPending`. Tooltip prefers "Acknowledge the overload alarm first" over the existing plug-state tooltips when latch is set. Stop button intentionally untouched — operator can always stop. |
| 13 | `frontend/src/pages/SystemHealth.tsx` | COMPLETE | Added "AUTO-STOP ALARMS" card above all other alarm cards (red border-2, distinct visual weight). Each row shows severity dot, AUTO-STOP label, pedestal+socket id, current/rated amps, load_pct, optional session id (overlaid from pendingAutoStopAlarms when WS payload was captured), timestamp, status text ("Pending acknowledgment" red bold vs "Acknowledged" grey), and admin Acknowledge button (with same window.confirm safety copy as the panel). Existing v3.11 Meter Load Alarms card filters out auto_stop entries to avoid duplication. loadHw merge logic extended to treat any pendingAutoStopAlarms entry as the highest severity, promoting nav badge to 'auto_stop'. Re-merge useEffect dep list extended so badge updates instantly on WS event. |
| 13a | `frontend/src/store/index.ts` | COMPLETE (Step 9 follow-up) | hwAlarmLevel union extended from `'none' \| 'warning' \| 'critical'` to include `'auto_stop'`. |
| 13b | `frontend/src/components/layout/Layout.tsx` | COMPLETE | NavItem.hwAlarm union extended; auto_stop badge rendered as red dot with red-300 ring and distinct tooltip "Socket auto-stopped — overload alarm pending acknowledgment". |
| 14 | `tests/backend/test_meter_load.py` | COMPLETE | 25 new TC-ML-31..55 cases (Steps 2/3/4/5/6 tests merged into a single file in step order). New helpers: `_seed_active_session`, `_capture_mqtt_publishes`, `_seed_socket_state`, `_set_auto_stop_latch`, `_trigger_auto_stop`. Existing `_reset_state` autouse fixture extended to wipe leftover sessions and clear auto_stop_pending_ack between tests. |
| 15 | `README.md` | COMPLETE | v3.12 changelog entry inserted at the top of "## Changelog", newest-first per project convention. Documents all backend + frontend touchpoints, design decisions D1/D7/D8/D9 in plain operator-readable terms, the 25-test delta (339 → 364), and explicitly notes the no-hardcoded-rated_amps invariant. |

### Section currently being worked on: Step 11 — COMMIT + PUSH (in progress)
### Final test counts: 364/364 backend pytest passing. TypeScript clean.
### Awaiting: explicit user approval before merging develop → main with CLOUD_IOT_RELEASE=1.

---

---

# Implementation Status — Live Socket Meter Telemetry + Load Monitoring (v3.11)

## Session started: 2026-04-28

Feature scope: Arduino reports the per-cabinet hardware configuration on
`opta/config/hardware` (meter type, phases, ratedAmps, modbusAddress per
socket) and live meter readings on `opta/meters/+/telemetry` every 5 s.
Backend stores everything dynamically — no hardcoded values for cabinet,
meter type, phase count, rated current, or socket count anywhere. Load
percentage is computed from the live current vs the stored rated_amps;
warning/critical thresholds are operator-configurable per socket. Alarm
state machine writes to a new `meter_load_alarms` table with auto-resolve
on return-to-normal and 2 % hysteresis to prevent threshold-edge chatter.
Control Center socket card gets a new `SocketLoadMeterPanel` (sibling to
v3.8 SocketBreakerPanel) with read-only Hardware Info, phase-aware load
bars (single bar for 1Φ, three stacked bars for 3Φ), and admin threshold
editor. System Health page gains a third alarm card for open meter load
alarms with Acknowledge / Resolve actions. ERP gets 5 new
`/api/ext/.../load*` endpoints under category "Load Monitoring".

**Approved design decisions (2026-04-28):**
- D1 (b): new `SocketLoadMeterPanel.tsx` — clean separation from breaker panel.
- D2 (b): 3-phase load uses `max(L1,L2,L3) / rated_amps × 100` (electrically
  correct — bottleneck phase). Single-phase = `currentAmps / rated_amps × 100`.
  This intentionally **diverges from the spec** which had a flawed total/rated
  formula.
- D3 (b): 2 % hysteresis on resolve. Only resolve warning when load drops to
  `warning_threshold − 2`, same gap on critical.
- D4: alarm state machine — `normal→warning` insert+broadcast,
  `warning→critical` auto-resolve warning (resolved_by="auto-upgrade") +
  insert critical, `critical→warning` auto-resolve critical
  (resolved_by="auto-downgrade") + insert warning, `*→normal` resolve all
  open rows (resolved_by="auto-resolve") + broadcast `meter_load_resolved`.
- D5: live meter fields stored as received even before hardware config
  arrives. Only `load_pct` / `load_status` / alarm pipeline are skipped.
- D6: `routers/meter_load.py` (internal admin) + `routers/ext_meter_load_endpoints.py`
  (ERP). Mirrors v3.8 split.
- D7: third "Meter Load Alarms" card on SystemHealth page; existing hardware
  alarm banners untouched.
- D8 (a): merge load alarm severity into existing `hwAlarmLevel` — single
  unified hardware-severity badge.
- D9: Acknowledge flips DB column (alarm visible but dimmed, badge ignores).
  Resolve is admin-only manual close. Auto-resolve uses `resolved_by="auto-resolve"`.
- D10 (b): three stacked horizontal bars per phase for 3Φ; one bar for 1Φ.
  Bottleneck phase still drives `load_pct` and alarm thresholds.
- D11: defaults — warning 60 %, critical 80 %.
- D12: hardware config dedup mirrors v3.8 breaker-metadata rule — only
  update fields present in payload, never overwrite existing with null.
- D13: `docs/firmware_requirements.md` gains v3.11 section documenting both
  contracts. Note dormant pattern same as v3.8 breakers.
- D14: ~30 tests using `_simulate(topic, payload)` pattern from v3.8 suite.
- D15: mobile out of scope.
- Out of scope: Arduino sketch changes (firmware team), Modbus polling code,
  per-meter serial-number lookup table.

### Files — Status

| # | File | Status | Notes |
|---|------|--------|-------|
| 1 | `backend/app/models/socket_config.py` | COMPLETE | 21 new columns: 5 hw-config + 6 single-phase live + 6 per-phase live + 3 derived load + 2 thresholds. All nullable except meter_load_status (default "unknown") and the two threshold defaults (60/80) |
| 2 | `backend/app/models/meter_load_alarm.py` | COMPLETE | One row per threshold crossing; resolved_at distinguishes open/historical; resolved_by encodes operator/auto-* origin; acknowledged column is separate from resolved |
| 3 | `backend/app/database.py` | COMPLETE | Imported meter_load_alarm; added 21 ALTER TABLE entries to _migrate_schema() in the v3.11 block |
| 4 | `backend/app/services/mqtt_client.py` | COMPLETE | Added `opta/config/hardware` + `opta/meters/+/telemetry` to TOPICS |
| 5 | `backend/app/services/mqtt_handlers.py` | COMPLETE | 2 regex (OPTA_HW_CONFIG_RE, OPTA_METER_RE) + dispatch branches; `_handle_opta_hardware_config` (no-overwrite-with-null per D12, broadcasts `hardware_config_updated`); `_handle_opta_meter_telemetry` (parses 1Φ/3Φ generically, stores live data even when rated_amps null per D5, computes load_pct via max(L1..L3)/rated for 3Φ per D2, runs `_classify_load` state machine with 2% hysteresis per D3, transitions per D4 with auto-upgrade/auto-downgrade/auto-resolve audit, broadcasts `meter_load_warning`/`meter_load_critical`/`meter_load_resolved` plus a per-tick `meter_telemetry_received`) |
| 6 | `backend/app/routers/meter_load.py` | COMPLETE | 5 admin endpoints + ack/resolve. Shared `serialize_load_state` / `serialize_alarm` re-exported to ERP file. PATCH validates `warning < critical` |
| 7 | `backend/app/routers/ext_meter_load_endpoints.py` | COMPLETE | 5 ERP routes mirroring v3.8 ext_breaker pattern. Reuses serialize_* helpers from meter_load.py. Marina endpoint LIKE-matches `MAR_{marina_id}_%` |
| 8 | `backend/app/main.py` | COMPLETE | imports + include_router for both meter_load_router and ext_meter_load_router (latter before gateway catch-all) |
| 9 | `backend/app/services/api_catalog.py` | COMPLETE | 5 ENDPOINT_CATALOG entries (load.*_ext, all category="Load Monitoring") + 4 EVENT_CATALOG entries (hardware_config_updated, meter_load_{warning,critical,resolved}) |
| 10 | `frontend/src/store/index.ts` | COMPLETE | `socketHardwareConfig` (patch-merge, key=`${pid}-${sid}`), `socketLoadStates` with default thresholds + load_status='unknown', `activeCriticalLoadAlarms` / `activeWarningLoadAlarms` with auto-promote/demote across severity in addLoadAlarm |
| 11 | `frontend/src/api/meterLoad.ts` | COMPLETE | Typed client: getSocketLoad, getPedestalLoad, patchLoadThresholds, getPedestalLoadAlarms, getSocketLoadHistory, acknowledgeLoadAlarm, resolveLoadAlarm |
| 12 | `frontend/src/components/pedestal/SocketLoadMeterPanel.tsx` | COMPLETE | Hardware Info read-only with "Awaiting hardware configuration from device" amber state; load bar(s) phase-aware (3 stacked for 3Φ, single for 1Φ); status badge/animation green/yellow/red; admin threshold editor with frontend validation matching backend |
| 13 | `frontend/src/components/pedestal/PedestalControlCenter.tsx` + `useWebSocket.ts` | COMPLETE | SocketLoadMeterPanel mounted as sibling after SocketBreakerPanel; 5 WS cases (hardware_config_updated, meter_telemetry_received, meter_load_warning, meter_load_critical, meter_load_resolved) — admin gets Browser Notification on critical |
| 14 | `frontend/src/pages/SystemHealth.tsx` | COMPLETE | Imports meterLoad client; new "Meter Load Alarms" card (per D7) listing open rows with Acknowledge + Resolve buttons; loadHw() merges hardware + load severity into single hwAlarmLevel (D8); loadLoadAlarms iterates visible pedestals every 15 s; useEffect on alarm-list lengths re-triggers merge |
| 15 | `tests/backend/test_meter_load.py` | COMPLETE | 30 tests covering hw config writes/updates/no-overwrite-with-null, broadcast event, telemetry phase detection, single-phase + 3-phase load formula (max(L1..L3) per D2), all 4 alarm state transitions, hysteresis, no-duplicate-on-same-status, threshold validation, GET endpoints, ack/resolve, ERP endpoints, drift guard. **30/30 green** |
| 16 | `tests/backend/conftest.py` | COMPLETE | Imports meter_load_alarm so create_all picks up the new table |
| 17 | `docs/firmware_requirements.md` | COMPLETE | New v3.11 section: opta/config/hardware contract + opta/meters/+/telemetry single/3-phase payload contracts + dormant-pattern note + bottleneck-phase formula explanation |
| 18 | `README.md` | COMPLETE | Newest-first v3.11 changelog with full feature description, 339-test count, Wire: list |

## Test run result: 339 passed, 0 failed (2026-04-28) — 313 prior + 26 new (30 in test_meter_load.py - 4 that overlap with existing in same module). TypeScript: clean.

## Pending before release
- ✅ pytest 339/339; ✅ TS clean; ✅ docs updated.
- Stage v3.11 files, commit on develop, push develop with full pre-push gate.
- PAUSE for explicit user approval before merging to main.
- After main merge: regenerate `docs/User Guide.docx` with v3.10 + v3.11 sections.

---

---

# Implementation Status — Configurable Daily LED Schedule (v3.10)

## Session started: 2026-04-28

Feature scope: per-pedestal daily LED on/off schedule (HH:MM, color, days-of-week).
Backend scheduler ticks every minute, compares marina-local time against
configured `on_time` / `off_time`, publishes `opta/cmd/led` with the
operator-chosen color/state. New `led_schedules` table (one row per pedestal).
4 admin endpoints for CRUD + immediate test. New `LedScheduleSection` in the
Control Center with on/off time pickers, color selector, day-of-week
checkboxes, Save/Test/Delete buttons, and a forward-looking "Next on / Next
off" preview that re-renders every minute. WebSocket `led_changed` event fires
on both scheduled and manual LED commands so the dashboard reflects state in
real time.

**Approved design decisions (2026-04-28):**
- D1 (b): single global `MARINA_TIMEZONE` env var (default `UTC`, on-site set
  to `Europe/Zagreb`). Per-pedestal TZ deferred.
- D2: endpoints co-located in `pedestal_config.py` (mirrors v3.9 valves).
- D3: color enum `{green, blue, red, yellow}` only — `white` deferred until
  firmware confirms support; flagged in `docs/firmware_requirements.md`.
- D4 (a): scheduler `await asyncio.sleep(60)` with HH:MM dedup.
- D5: in-memory `_led_schedule_last_fired: dict[int, dict[str, str]]` keyed
  by pedestal_id, slots `on` and `off` holding `YYYY-MM-DD HH:MM`. Restart
  duplicates absorbed by Opta's 16-entry msgId idempotency cache.
- D6: days-of-week stored as comma-separated `0..6` string (Mon=0, Sun=6).
  Validated unique + in-range on PUT.
- D7 (a): 5-minute grace window — fire missed on/off if backend was down for
  less than 5 min, otherwise log warning + skip.
- D8 (a): new `led_changed` WebSocket event broadcast on BOTH scheduled fires
  AND the existing manual `setLed` endpoint (retroactive consistency). Added
  to `EVENT_CATALOG`.
- D9 (a): `POST /led-schedule/test` returns 404 when no schedule exists.
- D10: 7 raw day checkboxes, no presets.
- D11: "Next on / Next off" preview computed on the frontend, re-rendered
  via `setInterval(60_000)` on mount.
- Out of scope: multiple windows per day, sunset/sunrise, mobile, ERP webhook
  for `led_changed` (operator can opt in via API Gateway page later).

### Files — Status

| # | File | Status | Notes |
|---|------|--------|-------|
| 1 | `backend/app/models/led_schedule.py` | COMPLETE | One row per pedestal; HH:MM strings, comma-sep days 0..6, color default green |
| 2 | `backend/app/database.py` | COMPLETE | init_db imports led_schedule so create_all picks up `led_schedules` |
| 3 | `backend/app/config.py` | COMPLETE | New `marina_timezone: str = "UTC"` setting; production .env sets `Europe/Zagreb` |
| 4 | `backend/app/services/led_scheduler.py` | COMPLETE | `_marina_now()` (zoneinfo), `_parse_days`, `_should_fire` (grace window), `_publish_led` shared helper, `tick_once(db, now_utc=None)` testable, `run_scheduler()` lifespan loop. Module-level `_led_schedule_last_fired` dict |
| 5 | `backend/app/routers/controls.py` | COMPLETE | `set_pedestal_led` now broadcasts `led_changed` with `source="manual"` after publish |
| 6 | `backend/app/routers/pedestal_config.py` | COMPLETE | 4 endpoints (GET/PUT/DELETE/POST-test). Validators for HH:MM, color enum, unique-sorted days. PUT/DELETE clear the per-pedestal dedup slot so a fresh save fires inside the grace window |
| 7 | `backend/app/main.py` | COMPLETE | `led_scheduler_task = asyncio.create_task(_run_led_scheduler())` + cancellation in shutdown |
| 8 | `backend/app/services/api_catalog.py` | COMPLETE | 4 ENDPOINT_CATALOG entries (led_schedule.{get,upsert,delete,test}) + 1 EVENT_CATALOG entry (led_changed) |
| 9 | `frontend/src/api/ledSchedule.ts` | COMPLETE | get/upsert/delete/test typed client + LedSchedule and LedScheduleBody types |
| 10 | `frontend/src/components/pedestal/LedScheduleSection.tsx` | COMPLETE | Auto LED toggle + on/off time inputs + 4-color swatches + 7-day checkboxes + live Next On / Next Off preview (60 s setInterval) + Save/Test/Delete buttons. Validators mirror backend. 404 from Test prompts to Save first |
| 11 | `frontend/src/components/pedestal/PedestalControlCenter.tsx` + `useWebSocket.ts` | COMPLETE | LedScheduleSection mounted between LED Control and Danger Zone; useWebSocket adds `led_changed` case that toasts admin-only when source=scheduler (manual fires already self-feedback) |
| 12 | `tests/backend/test_led_schedule.py` | COMPLETE | 13 tests (TC-LS-01..10 + 4 parametrised invalid HH:MM cases). Tests directly call `tick_once(db, now_utc=...)` for time-deterministic scheduler verification |
| 13 | `tests/backend/conftest.py` | COMPLETE | imports led_schedule model |
| 14 | `backend/requirements.txt` | COMPLETE | added `tzdata>=2024.1` for Windows zoneinfo lookups |
| 15 | `docs/firmware_requirements.md` | COMPLETE | New v3.10 section flagging that `white` is not firmware-validated |
| 16 | `README.md` | COMPLETE | Newest-first v3.10 entry — full feature description + 13 new tests + tzdata note + Wire: list |

## Test run result: 313 passed, 0 failed (2026-04-28) — 299 prior + 14 new (13 LED + 1 from re-running breakers/valves catalog drift). TypeScript: clean.

## Pending before release
- ✅ pytest 313/313; ✅ TS clean; ✅ docs updated.
- Stage v3.10 files, commit on develop, push develop with full pre-push gate.
- PAUSE for explicit user approval before merging to main.

---

---

# Implementation Status — Per-Valve Auto-Activation + Post-Diagnostic Auto-Open (v3.9)

## Session started: 2026-04-24

Feature scope: add a per-valve `auto_activate` flag (mirrors v3.5 socket flag but
for V1/V2) with default `True`. When `opta/diagnostic` returns and the per-valve
sensor reports `ok`, backend publishes `{"action":"activate"}` on
`opta/cmd/water/V{n}` for every valve whose `auto_activate=True` — unless
(a) an active water session already exists on that valve, or (b) an operator
manually stopped the valve in the last 10 minutes. The auto-fire creates a
`customer_id=NULL` "unattributed" water session so incoming flow readings are
still attributable to a row (even though no invoice is produced). 30 s after
each auto-open, a fire-and-forget watchdog checks the latest flow reading and
broadcasts `valve_flow_warning` if flow is still 0 — informational only, the
valve stays open.

**Approved design decisions (2026-04-24):**
- Default `auto_activate=True` for new valves (opposite of sockets). Hardware
  valve is normally-closed; flow meter provides immediate operator visibility.
- D1 option (b): create `customer_id=NULL` session when auto-activation fires
  without a customer. Flow is tracked via the existing `_handle_water_flow`
  pipeline; no invoice is produced.
- D2 option (b): per-valve sensor ok gates auto-open. Diagnostic response
  parser must be extended to expose per-valve `water_v1_ok` / `water_v2_ok`.
- D3 option (b): 10-minute cooldown after an operator-initiated manual stop.
  Prevents diagnostic from becoming an accidental water-on button.
- D4: no-op if an active water session already exists on that valve.
- D5: sockets entirely unchanged — still require `UserPluggedIn`.
- D6: v3.7 auto-discovery pattern — create ValveConfig row once with default
  `auto_activate=True`, never overwrite operator toggles afterwards.
- D7 option (a): new `valve_config` table (not generalised SocketConfig).
- D8: separate module-level dicts in mqtt_handlers — rename the existing
  `last_diagnostic_at` to `last_diagnostic_lockout_at` for socket auto-activate
  clarity, and add `last_diagnostic_ok_at` as the valve auto-open enabler.
- D9: five mandatory tests cover happy path, auto_activate=False skip,
  active-session skip, per-valve sensor filter, and orphan-session flow
  attribution.
- Additional guard: 30-second zero-flow watchdog after each auto-open. Logs a
  warning + broadcasts `valve_flow_warning` WebSocket event when flow stays 0.
  Non-destructive — valve remains open; operator sees banner + Browser Notification.

### Files — Status

| # | File | Status | Notes |
|---|------|--------|-------|
| 1 | `backend/app/models/valve_config.py` | COMPLETE | New `valve_configs` table; auto_activate default True per design D |
| 2 | `backend/app/database.py` | COMPLETE | init_db imports valve_config so create_all creates `valve_configs` |
| 3 | `backend/app/services/mqtt_handlers.py` | COMPLETE | Renamed `last_diagnostic_at` → `last_diagnostic_lockout_at` with back-compat alias; added `last_diagnostic_ok_at` + `last_valve_manual_stop_at` dicts; new `_auto_discover_valve_config` helper; `_handle_marina_water` now auto-discovers valve config; extended `_handle_opta_diagnostic` with per-valve `water_v{n}` keys and post-diag `_maybe_auto_open_valve` tasks per valve whose sensor is ok; new `_maybe_auto_open_valve` coroutine (4 guards: auto_activate flag, active session, 10-min cooldown, cabinet_id present) + `_check_valve_flow_after_30s` zero-flow watchdog that broadcasts `valve_flow_warning` |
| 4 | `backend/app/services/session_service.py` | SKIPPED | No change needed — firmware emits OutletActivated with customer_id=None in response to auto-open activate command; existing `_handle_event_outlet_activated` path handles unattributed sessions natively |
| 5 | `backend/app/routers/diagnostics.py` | SKIPPED | No change needed — auto-open is driven by MQTT response handler, not the HTTP endpoint. The existing `last_diagnostic_at` reference still works via back-compat alias |
| 6 | `backend/app/routers/controls.py` | COMPLETE | Stamp `last_valve_manual_stop_at[(pid, vid)]` both in `_publish_session_control` water stop branch AND in `direct_water_cmd` stop branch so any operator-initiated stop triggers the 10-min cooldown |
| 7 | `backend/app/routers/pedestal_config.py` | COMPLETE | Added ValveConfigUpdate body + `GET /api/pedestals/{pid}/valves/config` + `PATCH /api/pedestals/{pid}/valves/{vid}/config` (admin only). Default-true fallback returned for never-configured valves. Co-located with sibling socket config endpoints |
| 8 | `backend/app/main.py` | SKIPPED | No change — endpoints piggyback on existing `pedestal_config_router` already registered |
| 9 | `backend/app/services/api_catalog.py` | COMPLETE | Added 2 ENDPOINT_CATALOG entries (valves.config_list / valves.config_patch) + 1 EVENT_CATALOG entry (valve_flow_warning) |
| 10 | `frontend/src/store/index.ts` | COMPLETE | `valveAutoActivate` Record + setter mirroring socketAutoActivate; `valveFlowWarnings` list + add/clear. Keyed `${pedestal_id}-${valve_id}` |
| 11 | `frontend/src/api/valveConfig.ts` | COMPLETE | getValveConfigs, setValveConfig typed client |
| 12 | `frontend/src/hooks/useWebSocket.ts` | COMPLETE | Destructured `addValveFlowWarning`; new case `valve_flow_warning` writes to store + fires admin Browser Notification |
| 13 | `frontend/src/components/pedestal/PedestalControlCenter.tsx` | COMPLETE | WaterCard extended: AUTO toggle mirroring SocketCard, green AUTO / amber UNATTRIBUTED badges, zero-flow amber banner when valveFlowWarnings contains the key. ControlCenter loads `getValveConfigs` on mount; `onValveAutoActivateChange` optimistic PATCH with rollback |
| 14 | `tests/backend/test_valve_auto_activate.py` | COMPLETE | 7 tests (TC-VA-01..07) — all five mandatory cases per D9 + auto-discovery default + GET/PATCH endpoints. Autouse fixture wipes manual-stop dict + active water sessions on the test cabinet between tests |
| 15 | `tests/backend/conftest.py` | COMPLETE | Added valve_config import so create_all picks up the new table |
| 16 | `frontend/src/hooks/useWebSocket.ts` (touched again) | COMPLETE | Tightened body type for valve_flow_warning Notification (TS strict mode) |
| 17 | `README.md` | COMPLETE | Newest-first v3.9 entry — flag default, post-diag flow + 3 guards, unattributed sessions, zero-flow watchdog, 7 new tests, Wire: list |

## Pending before release
- ✅ pytest 299/299; ✅ TS clean.
- Commit on develop, push develop with full test gate.
- PAUSE for explicit user approval before merging to main.

## Test run result: 299 passed, 0 failed (2026-04-25) — 292 prior + 7 new TC-VA cases. TypeScript: clean.

---

---

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

## Release status

- ✅ Commit `716f6b3` on develop.
- ✅ Pre-commit + pre-push gates green (pytest 292/292, bandit, semgrep, gap 1-4, detect-secrets, pip-audit).
- ⚠️ Playwright e2e **skipped** in the pre-push hook because the backend was not running on :8000. The spec itself is committed and will run automatically the next time the hook fires with a live backend (e.g. `bash tests/playwright_e2e.sh` with `uvicorn` up).
- ✅ `716f6b3` pushed to `origin/develop` (`2f9af0e..716f6b3`).
- ✅ User approved merge. `main` fast-forwarded to `6e8ab32`.
- ✅ Pushed to `origin/main` with `CLOUD_IOT_RELEASE=1` — all pre-push gates green; Playwright skipped (no backend on :8000 at push time, same as develop push).
- Final state: `main` and `develop` both at `6e8ab32`, synced with `origin`.

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






