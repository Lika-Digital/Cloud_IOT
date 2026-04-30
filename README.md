# Smart Pedestal IoT Management — Cloud_IOT

Full-stack IoT monitoring, session management, and customer billing platform for a smart marina pedestal with 4 electricity sockets and 1 water meter.

Deployed on an **Intel Atom x7425E NUC** running Ubuntu 24.04. Managed remotely via Cloudflare Tunnel / Tailscale.

---

## Architecture

```
Arduino OPTA (MQTT client)       IP Camera (RTSP/ONVIF)    SNMP Sensor (UDP :1620)
        │ MQTT                            │                         │
        ▼                                 │                         │
Mosquitto Broker (:1883)                  │                         │
        │                                 │                         │
        └──────────── FastAPI Backend (:8000) ────────────────────────
                              │
                    ┌─────────┴──────────┐
                    │   SQLite DBs        │
                    │  pedestal.db        │  ← IoT data, alarms, error logs
                    │  data/users.db      │  ← auth, customers, billing
                    └─────────────────────┘
                              │ WebSocket + REST
                              ▼
                    React Dashboard (:5173 / Nginx)
                              │
                    Expo Mobile App (iOS/Android)
```

---

## Changelog

Every merge to `main` must be described here before the push. Entries are newest-first; each references its commit hash so the history on disk matches what operators actually see on the NUC after `upgrade.sh`.

### 2026-04-30 — 90 % auto-stop overload protection (v3.12)
- Adds a third threshold tier on top of v3.11 load monitoring: when meter
  telemetry shows a socket reaching **90 % of `rated_amps`**, the backend
  automatically ends the active session, publishes a stop command on
  `opta/cmd/socket/Q{n}` (same payload shape as the operator's direct
  command), and writes a persistent alarm. The 60 % / 80 % thresholds and
  their state machine are completely untouched.
- New `socket_configs.auto_stop_pending_ack` boolean (default `false`).
  Set atomically by the auto-stop sequence; cleared only by the new
  acknowledge endpoint, never by the load dropping back below 90 %.
  Migration is idempotent ALTER TABLE per the existing pattern.
- Auto-stop is **terminal**: once `meter_load_status` flips to
  `auto_stop`, the existing classifier is bypassed for that socket
  until an admin acknowledges. Live readings still update every tick;
  only the state-machine transitions are suspended.
- New session `end_reason="auto_stop_overload"` distinguishes the
  protective stop from operator stop or `breaker_trip`.
- New `meter_load_alarms.alarm_type="auto_stop"` row created on every
  trip. Pre-existing open `warning` / `critical` rows for the same
  socket are auto-resolved with `resolved_by="auto-stop-supersedes"`
  so the alarm history stays consistent.
- Re-activation guard added in three places:
  `POST /api/controls/sockets/{pid}/{sid}/approve`,
  `POST /api/controls/pedestal/{pid}/socket/{Q}/cmd` (action `activate`
  only — `stop` stays unguarded so the operator can always stop), and
  `_maybe_auto_activate` (the v3.5 plug-in auto-fire). All three return
  HTTP 409 / log skip-reason `"overload alarm pending acknowledgment"`
  while the latch is set.
- New socket-scoped acknowledge endpoint
  `POST /api/pedestals/{pid}/sockets/{sid}/load/auto-stop/acknowledge`
  (admin only). Atomic transaction: clears the latch, marks the latest
  open auto-stop row acknowledged with the admin's email, reclassifies
  `meter_load_status` from the live `load_pct` (treats prev_status as
  `unknown` so the operator's ack is a clean restart with no hysteresis
  carryover). Returns `{"status":"acknowledged","socket_id":N}`.
- ERP twin at `/api/ext/.../auto-stop/acknowledge` mirrors the internal
  semantics but records `acknowledged_by="erp-service"` so the audit
  trail can distinguish operator from ERP-driven acks. Registered as
  `load.auto_stop_ack_ext` under api_catalog category "Load Monitoring".
- Two new WebSocket events: `meter_load_auto_stop` (severity
  `AUTO_STOP`, payload includes the ended `session_id`) and
  `meter_load_auto_stop_acknowledged`. Both registered in EVENT_CATALOG
  so the External API webhook can opt into them.
- Frontend `LoadStatus` union extended with `'auto_stop'` (D9 — TS
  errors at every render path force explicit handling). New store
  fields `autoStopPendingAck` and `pendingAutoStopAlarms` plus
  `setAutoStopPendingAck` / `addAutoStopAlarm` /
  `acknowledgeAutoStopAlarm` actions.
- `SocketLoadMeterPanel.tsx` gets a prominent red banner — "⚡ AUTO-STOP
  — OVERLOAD PROTECTION ACTIVATED" — with the stop-time amps/percentage
  readout and an admin-only "Acknowledge & Enable Re-activation"
  button. Click triggers a `window.confirm` with the spec's safety copy
  ("Are you sure you want to acknowledge this overload alarm? Ensure
  the boat has reduced its power consumption…") before posting.
- Control Center Activate button is disabled with tooltip *"Acknowledge
  the overload alarm first"* whenever `autoStopPendingAck[key]` is
  true, on top of the existing plug-inserted guard.
- System Health page adds a fourth alarm card "AUTO-STOP ALARMS"
  rendered above the v3.11 "Meter Load Alarms" card. Each row shows
  pedestal+socket id, current/rated amps at trip, percentage, optional
  ended session id, timestamp, status text ("Pending acknowledgment"
  vs "Acknowledged"), and admin Acknowledge button. Existing v3.11
  card filters out auto_stop rows so they're not duplicated.
- Nav badge `hwAlarmLevel` extended with `'auto_stop'` — takes
  precedence over `'critical'` so an unacknowledged 90 % trip is the
  most prominent indicator on the sidebar (red dot with a brighter
  red-300 ring).
- Admin role gets a Browser Notification on `meter_load_auto_stop`
  with the ⚡ emoji and the load percentage.
- 25 new backend tests (`test_meter_load.py` — TC-ML-31..55):
  - 90 % boundary fires / 89.9 % does not fire / terminal state
    short-circuits a re-trip / load drop below 90 % keeps status
    auto_stop until ack
  - MQTT publish payload (topic, action, msgId, cabinetId)
  - Session completion with `end_reason="auto_stop_overload"`
  - Alarm row insertion with `alarm_type="auto_stop"`
  - Latch flips True; broadcast severity / session_id present
  - Open warning/critical superseded with `auto-stop-supersedes`
  - 409 from `approve_socket` and `direct_socket_cmd` activate;
    stop unaffected; `_auto_activate_precondition_check` returns
    the documented skip reason
  - Acknowledge endpoint (internal) clears latch, marks alarm with
    admin email, broadcasts `meter_load_auto_stop_acknowledged`,
    409 when nothing pending, allows re-activate after ack
  - ERP acknowledge records `erp-service`, 503 when toggle off,
    401 missing auth
  - api_catalog drift guards for the new endpoint + events
  Total backend suite **339 → 364 passing, 0 failures**. TypeScript
  clean (the `LoadStatus` union extension forced explicit handling
  in `STATUS_BAR_COLOR` / `STATUS_TEXT` / `STATUS_BADGE_CLASS` and
  the nav-badge `hwAlarmLevel` map — exactly the safety net D9 was
  designed to provide).
- The implementation strictly never hardcodes a `rated_amps` value
  anywhere — the 90 % calculation derives entirely from
  `SocketConfig.rated_amps` populated by `opta/config/hardware`
  during pedestal discovery, and the auto-stop branch is skipped
  with a warning log when `rated_amps` is null.

### 2026-04-28 — Live socket meter telemetry + load monitoring (v3.11)
- Two new MQTT topics — `opta/config/hardware` (one-shot per cabinet, lists
  meter type / phases / ratedAmps / modbusAddress per socket) and
  `opta/meters/+/telemetry` (per-socket live readings every 5 s). Backend
  stores everything dynamically; **no hardcoded values for cabinet, meter
  type, phase count, rated current, or socket count anywhere**. Single- and
  three-phase sockets are handled by the same code path — only the payload
  fields differ.
- New nullable columns on `socket_configs`: 5 hardware-config + 6 single-phase
  live readings + 6 per-phase live readings + 3 derived load fields
  (`meter_load_pct`, `meter_load_status`, `meter_load_updated_at`) + 2
  operator thresholds (`load_warning_threshold_pct` default 60,
  `load_critical_threshold_pct` default 80).
- New `meter_load_alarms` table — one row per threshold crossing.
  `resolved_at IS NULL` ⇒ alarm currently active; otherwise historical.
  `resolved_by` encodes whether closure was operator email, `auto-resolve`,
  `auto-upgrade`, or `auto-downgrade`. Separate `acknowledged` flag (with
  `acknowledged_by` operator email) lets an operator silence a still-active
  alarm without resolving it.
- Alarm state machine: `normal → warning` inserts a warning row;
  `warning → critical` auto-resolves the warning (`resolved_by="auto-upgrade"`)
  and inserts a critical row; `critical → warning` auto-downgrades; any state
  to `normal` resolves all open rows for the socket (`resolved_by="auto-resolve"`)
  and broadcasts `meter_load_resolved`.
- 2 % hysteresis on resolve direction prevents alarm chatter on borderline
  loads. Going UP requires the bare threshold; going DOWN requires
  `threshold − 2`.
- **Three-phase load percentage uses `max(L1, L2, L3) / ratedAmps × 100`**
  (bottleneck phase, electrically correct), not the spec's literal
  `currentAmpsTotal / ratedAmps × 100` which would alarm immediately on
  perfectly healthy 3-phase loads. Single-phase is the obvious
  `currentAmps / ratedAmps × 100`.
- Backend handlers degrade gracefully: meter telemetry arriving before any
  hardware config still stores raw current/voltage/power/etc., only the
  load-percentage and alarm-pipeline are skipped (with a single warning log
  per arrival).
- 5 internal admin endpoints under `/api/pedestals/{pid}/...load*` — GET
  socket / pedestal load, PATCH thresholds (validates warning < critical and
  both in 1..99), GET alarms (open only), GET socket history (last 50). Plus
  POST `…/load/alarms/{id}/acknowledge` and `…/resolve` for the System Health
  action buttons.
- 5 ERP endpoints under `/api/ext/...` (mirror v3.8 pattern, registered before
  the gateway catch-all). All sit under api_catalog category
  **"Load Monitoring"**, so the existing data-driven ApiGateway page
  auto-renders them as a dedicated group with no JSX changes.
- 4 new WebSocket events — `hardware_config_updated`, `meter_load_warning`,
  `meter_load_critical`, `meter_load_resolved` — plus a low-volume
  `meter_telemetry_received` per-tick update so the dashboard load bars
  update live.
- Frontend: new `SocketLoadMeterPanel.tsx` sibling component, mounted after
  `SocketBreakerPanel` inside each SocketCard. Shows read-only Hardware Info
  (or amber *"Awaiting hardware configuration from device"* when the Arduino
  hasn't reported yet), a phase-aware load bar (one bar for 1Φ, three stacked
  bars for 3Φ — operator sees phase imbalance at a glance), secondary meter
  readings (V, P, PF, f), and an admin-only threshold editor. Critical state
  fires a Browser Notification for admin role.
- System Health page gets a third alarm card "Meter Load Alarms" with
  Acknowledge / Resolve buttons per row; `hwAlarmLevel` badge merges hardware
  and load severity into a single indicator.
- 30 new backend tests (`test_meter_load.py` — TC-ML-01..30): hardware-config
  parse + no-overwrite-with-null + ws broadcast, telemetry skip-no-config
  with warning log, single + three-phase detection from payload shape,
  bottleneck-phase formula, all 4 state transitions including hysteresis,
  no-duplicate-on-same-status, ERP auth (401), threshold validation,
  acknowledge/resolve, drift guard. Total backend suite **313 → 339 passing,
  0 failures**. TypeScript clean.
- `docs/firmware_requirements.md` gains a new v3.11 section with both topic
  contracts. Until firmware publishes them the feature is dormant — same
  pattern as v3.8 breakers.
- Wire: `backend/app/models/{socket_config.py, meter_load_alarm.py (new)}`,
  `backend/app/database.py`,
  `backend/app/services/{mqtt_client.py, mqtt_handlers.py, api_catalog.py}`,
  `backend/app/routers/{meter_load.py (new), ext_meter_load_endpoints.py (new)}`,
  `backend/app/main.py`,
  `frontend/src/{store/index.ts, hooks/useWebSocket.ts}`,
  `frontend/src/api/meterLoad.ts (new)`,
  `frontend/src/components/pedestal/{SocketLoadMeterPanel.tsx (new), PedestalControlCenter.tsx}`,
  `frontend/src/pages/SystemHealth.tsx`,
  `tests/backend/{test_meter_load.py (new), conftest.py}`,
  `docs/firmware_requirements.md`.

### 2026-04-28 — Configurable daily LED schedule (v3.10)
- Per-pedestal daily LED on/off schedule. Operator picks `on_time`,
  `off_time` (HH:MM), `color`, and which days of the week from the new
  **LED Schedule** section in the Control Center. One row per pedestal
  in the new `led_schedules` table.
- Background scheduler ticks every 60 seconds and compares marina-local
  time against each enabled schedule. Color set is `{green, blue, red,
  yellow}` — `white` is intentionally not validated yet on the firmware
  side (see `docs/firmware_requirements.md`).
- New `MARINA_TIMEZONE` env var (default `UTC`). Production NUC sets it
  to `Europe/Zagreb` so an operator-entered "20:00" means 20:00 local.
  Single global setting; per-pedestal timezone is deferred until needed.
- 5-minute grace window — if the backend was just restarted and missed
  the exact tick by less than 5 minutes, the scheduler still fires the
  on/off command (D7). Beyond 5 minutes the missed fire is logged and
  skipped. In-memory dedup dict ensures no double-fire within the same
  HH:MM window; restart duplicates are absorbed by the Opta's 16-entry
  `msgId` idempotency cache.
- Four new admin endpoints:
  `GET /api/pedestals/{pid}/led-schedule` (admin + monitor),
  `PUT /api/pedestals/{pid}/led-schedule` (admin),
  `DELETE /api/pedestals/{pid}/led-schedule` (admin),
  `POST /api/pedestals/{pid}/led-schedule/test` (admin — fires LED on
  with the configured color; 404 when no schedule exists, per D9).
- New `led_changed` WebSocket event broadcast on **both** scheduled fires
  and the existing manual `setLed` endpoint (retroactively wired — the
  manual path was silent before). Payload `source` field distinguishes
  `"manual"` vs `"scheduler"`. Dashboard surfaces a small toast for
  scheduler-driven events so operators see the schedule actually fired.
- Frontend: new `LedScheduleSection` between LED Control and the Reset
  card. Auto-toggle, on/off `<input type="time">` pickers, four color
  swatches, seven day-of-week chips, Save / Test LED / Delete Schedule
  buttons, and a live "Next On / Next Off" preview that re-renders every
  minute (D11) so the operator can verify the schedule will fire when
  expected.
- 13 new backend tests (`test_led_schedule.py` — TC-LS-01..10 plus 4
  invalid-HH:MM parametrised cases). Tests call `led_scheduler.tick_once`
  directly with a deterministic `now_utc` rather than waiting on the
  60 s loop. Total suite 299 → 313 passing, 0 failures. TypeScript clean.
- `tzdata>=2024.1` added to `requirements.txt` — Linux NUC has the IANA
  database via `/usr/share/zoneinfo` natively, but Windows dev/test boxes
  need the PyPI package for `zoneinfo.ZoneInfo` lookups to work.
- Wire: `backend/app/models/led_schedule.py` (new),
  `backend/app/database.py`, `backend/app/config.py`,
  `backend/app/services/led_scheduler.py` (new),
  `backend/app/services/api_catalog.py`,
  `backend/app/routers/{controls.py, pedestal_config.py}`,
  `backend/app/main.py`, `backend/requirements.txt`,
  `frontend/src/api/ledSchedule.ts` (new),
  `frontend/src/components/pedestal/LedScheduleSection.tsx` (new),
  `frontend/src/components/pedestal/PedestalControlCenter.tsx`,
  `frontend/src/hooks/useWebSocket.ts`,
  `tests/backend/{test_led_schedule.py (new), conftest.py}`,
  `docs/firmware_requirements.md`.

### 2026-04-25 — Per-valve auto-activation + post-diagnostic auto-open (v3.9)
- Each water valve (V1, V2) now has its own `auto_activate` flag — mirror of the
  v3.5 socket flag but with the **default flipped to True**. The hardware is
  normally-closed so an auto-open requires a real backend command, and the flow
  meter provides immediate visibility if anything unexpected happens.
- When `opta/diagnostic` returns and a valve's individual sensor reports `ok`,
  backend publishes `{"action":"activate"}` on `opta/cmd/water/V{n}` for every
  valve whose `auto_activate=True` — provided three guards pass: (a) no
  pre-existing active water session on that valve, (b) operator has not manually
  stopped the valve in the last 10 minutes, (c) cabinet has a configured
  `opta_client_id`. Per-valve sensor parsing is exposed in the diagnostic
  response as `water_v1` / `water_v2` keys.
- Unattributed sessions: when the firmware emits `OutletActivated` in response
  to a backend-initiated auto-open, the resulting session has `customer_id=NULL`.
  The dashboard surfaces this with an amber `UNATTRIBUTED` badge on the valve
  card so the operator knows flow is being measured but not billed.
- Zero-flow safety watchdog: 30 s after each auto-open publish, backend checks
  the latest `lpm` reading. If still zero, it broadcasts `valve_flow_warning`
  WebSocket event + writes a hardware warning log + fires a Browser Notification
  for admin operators. Informational only — the valve stays open so the operator
  can investigate (likely a disconnected hose).
- New `valve_configs` table (`pedestal_id`, `valve_id`, `auto_activate` default
  TRUE). Auto-discovered on first contact via the v3.7 pattern: created once
  with the default, never overwritten so operator toggles survive reconnects.
- Two new admin endpoints: `GET /api/pedestals/{pid}/valves/config` returns
  defaults for any valve never explicitly configured, `PATCH /api/pedestals/{pid}/valves/{vid}/config`
  toggles the flag.
- Refactored MQTT handlers: `last_diagnostic_at` renamed to
  `last_diagnostic_lockout_at` for clarity (back-compat alias preserved so
  existing imports still work). New `last_diagnostic_ok_at` and
  `last_valve_manual_stop_at` module-level dicts. The socket `diagnostic in
  progress` lockout is now distinct from the valve `post-diagnostic trigger`
  semantics — same timestamp would have meant opposite things.
- Control Center: WaterCard gains a green AUTO badge + an amber UNATTRIBUTED
  badge + a zero-flow warning banner. Auto-activate toggle styled identically
  to the SocketCard one. Optimistic PATCH with rollback on failure.
- 7 new backend tests (`test_valve_auto_activate.py` — TC-VA-01..07) cover the
  happy path, every guard (auto_activate=False, active session, sensor fault,
  10-min cooldown), default-true on first auto-discovery, and the GET/PATCH
  endpoints. Total suite: 292 → 299 passing, 0 failures. TypeScript clean.
- Wire: `backend/app/models/valve_config.py` (new),
  `backend/app/database.py`, `backend/app/services/mqtt_handlers.py`,
  `backend/app/services/api_catalog.py`,
  `backend/app/routers/{controls.py, pedestal_config.py}`,
  `frontend/src/{store/index.ts, hooks/useWebSocket.ts}`,
  `frontend/src/api/valveConfig.ts` (new),
  `frontend/src/components/pedestal/PedestalControlCenter.tsx`,
  `tests/backend/{test_valve_auto_activate.py (new), conftest.py}`.

### 2026-04-24 — Smart circuit breaker monitoring + remote reset (v3.8)
- New MQTT topic `opta/breakers/{socket_id}/status` carries live breaker state
  (`closed | tripped | open | resetting`) and breaker hardware metadata (type,
  rating, poles, RCD yes/no, RCD sensitivity). The Opta publishes whatever is
  wired on the cabinet — backend never hardcodes breaker descriptions and, per
  the "no-overwrite-with-null" rule, preserves previously-reported metadata
  when a subsequent payload omits it.
- New `BreakerTripped` event on `opta/events` appends to the new `breaker_events`
  audit table, stops any active power session on the affected socket with
  `end_reason="breaker_trip"`, and broadcasts a persistent `breaker_alarm`
  WebSocket event. Admin browsers also get a Browser Notification.
- `SocketConfig` extended with 9 nullable breaker columns
  (`breaker_state`, `breaker_last_trip_at`, `breaker_trip_cause`,
  `breaker_trip_count`, `breaker_type`, `breaker_rating`, `breaker_poles`,
  `breaker_rcd`, `breaker_rcd_sensitivity`). `breaker_trip_count` is cumulative
  forever. `Session` gains a nullable `end_reason` column. All via `_migrate_schema()`
  so existing pedestal DBs upgrade in place with no manual SQL.
- Internal admin endpoints: `POST /api/pedestals/{pid}/sockets/{sid}/breaker/reset`
  (returns 409 when not tripped, 200 with `reset_command_sent` otherwise, writes
  an audit row tagged with the operator email, publishes
  `opta/cmd/breaker/Q{n}` and broadcasts `breaker_state_changed → resetting`).
  Read-only GETs for state, per-socket history (`?limit=10` default), and last 50
  events across all sockets of a pedestal.
- ERP external API (direct FastAPI routes registered before the
  `/api/ext/{path:path}` gateway catch-all, same pattern as the v3.3
  ext-pedestal endpoints):
  - `GET /api/ext/pedestals/{pid}/breakers` — state + metadata for all sockets.
  - `GET /api/ext/pedestals/{pid}/sockets/{sid}/breaker` — state + last 5 events.
  - `POST /api/ext/pedestals/{pid}/sockets/{sid}/breaker/reset` — ERP-triggered
    remote reset; audit row tagged `reset_initiated_by="erp-service"` so it is
    distinguishable from operator resets.
  - `GET /api/ext/pedestals/{pid}/breaker/history` — last 50 events.
  - `GET /api/ext/marinas/{marina_id}/breaker/alarms` — every socket currently
    in `tripped` or `resetting` state across all pedestals whose cabinet id
    matches `MAR_{marina_id}_...`.
- WebSocket events: `breaker_state_changed` carries the full metadata bundle;
  `breaker_alarm` fires on BreakerTripped. Both flow through the existing
  `dispatch_webhook` hook, so enabling them in `ExternalApiConfig.allowed_events`
  pushes them to the ERP webhook with no additional wiring.
- Control Center: red alarm banner at the top when any socket on the current
  pedestal is tripped, listing Q{n} labels and an Acknowledge button
  (dismisses via sessionStorage — returns on full reload). New
  `SocketBreakerPanel` inside each SocketCard shows the coloured state dot,
  Hardware Info (all fields render "Not reported" when Arduino didn't publish),
  admin-only Reset Breaker button with confirm dialog + 15 s timeout watchdog,
  and a History button opening a modal with the last 10 events (operator
  username vs ERP tag is surfaced per row).
- PedestalView: small red ⚡ lightning-bolt overlay on the socket circle when
  the breaker is tripped. Existing ring/bg colour logic is untouched.
- API Configuration UI: the 5 new ERP endpoints auto-group under a new
  **Breaker Management** category in the existing ApiGateway table (catalog-
  driven, no JSX changes needed).
- 21 new backend tests (`test_breaker_monitoring.py` — TC-BR-01..21) covering
  payload parsing, no-null-overwrite rule, trip-count edge semantics,
  BreakerTripped → session stop, MQTT reset payload shape, internal & ERP 409
  guards, ERP 403 on invalid token, list / single-socket-with-5-events /
  pedestal-history-capped-50 / marina-alarms-filter / api_catalog drift guard.
  New Playwright spec `breaker.spec.ts` covers Hardware Info default,
  admin-only Reset visibility, and alarm banner. Total suite: 275 → 292 passing.
- New `docs/firmware_requirements.md` records the retain-flag recommendation
  for `opta/breakers/+/status` so backend restarts see the current state
  immediately via the MQTT retained message.
- Wire: `backend/app/models/{socket_config.py, session.py, breaker_event.py}`,
  `backend/app/database.py`, `backend/app/services/{mqtt_client.py, mqtt_handlers.py, session_service.py, api_catalog.py}`,
  `backend/app/routers/{breakers.py, ext_breaker_endpoints.py}`,
  `backend/app/main.py`,
  `frontend/src/{store/index.ts, hooks/useWebSocket.ts, api/breakers.ts}`,
  `frontend/src/components/pedestal/{SocketBreakerPanel.tsx, BreakerHistoryModal.tsx, PedestalControlCenter.tsx, PedestalView.tsx}`,
  `tests/backend/{test_breaker_monitoring.py, conftest.py}`,
  `frontend/e2e/breaker.spec.ts`,
  `docs/firmware_requirements.md`.

### 2026-04-21 — MQTT auto-discovery + QR bundle (v3.7)
- Unknown cabinets appearing on `opta/status` now register themselves automatically. `Pedestal.name` is prettified once on first creation (`MAR_KRK_ORM_01` → `MAR KRK ORM 01`); operator renames are never overwritten afterwards. New `PedestalConfig.first_seen_at` column stamps the moment; `status` column tracks `online`/`offline`. `last_heartbeat` keeps playing the `last_seen_at` role (no redundant column).
- Unknown sockets appearing on `opta/sockets/Q*/status` auto-create a `SocketConfig` row (`auto_activate=false` default) and trigger a printable QR PNG on disk.
- QR labels (new): 300×300 PNG with a "{cabinet spaced} — Q{n}" text caption beneath the matrix, saved to `backend/static/qr/{cabinet_id}_{socket_id}.png`. Idempotent — subsequent writes are skipped until explicitly regenerated.
- Two new admin endpoints: `GET /api/pedestals/{cab}/qr/all` streams a ZIP of all 4 PNGs; `POST /api/pedestals/{cab}/qr/regenerate` deletes the disk cache + rebuilds. The single-socket preview (`GET /api/mobile/socket/{pid}/{sid}/qr`) from v3.6 stays as-is.
- New `pedestal_registered` WebSocket event fires with `is_new=true` on first contact and `is_new=false` on reconnect. Throttled to one broadcast per pedestal per 60 s so reconnect storms cannot spam the dashboard.
- Dashboard: new **QR Codes** collapsible section at the top of Control Center with a 2×2 grid, per-cell Download + Copy URL buttons, top-right Download All + Regenerate buttons. Existing Cabinet Status / Event Log / ACK Log / Diagnostic panels are untouched.
- Pedestal grid: each `PedestalCard` now shows a 🔖 icon that opens a modal with the same QR grid + Download All without navigating away from the fleet view.
- New **Toast tray** (bottom-right, 10 s auto-dismiss) shows `New pedestal discovered: {name} ({cab})` with a View link that deep-links to the pedestal detail page.
- 13 new backend tests (`test_pedestal_auto_discovery.py`) covering discovery, name-pretty + admin-rename protection, SocketConfig auto-create + preservation, QR cache idempotency, ZIP structure, regenerate mtime proof, and the 60 s throttle. 262 → 275 total.
- Wire: `backend/app/services/qr_service.py` (new), `backend/app/routers/qr.py` (new), `backend/app/services/api_catalog.py` + drift guards updated, `frontend/src/components/pedestal/SocketQrGrid.tsx` shared component, `frontend/src/components/ui/ToastContainer.tsx` new global tray.

### 2026-04-21 — QR-code mobile ownership + per-session telemetry (v3.6)
- Every socket now has a static QR printed on its label; scanning it opens `/mobile/socket/{pedestal_id}/{socket_id}` in the customer app and claims the active session for the scanning customer. Claim branches: `no_session`, `claimed`, `already_owner`, `read_only`.
- **Mobile authority model is monitoring-only.** `POST /api/customer/sessions/{id}/stop` now returns **403** for every customer call — the customer ends a session by physically unplugging the cable (firmware emits `UserPluggedOut`). Operator stop from the dashboard (admin role) is the only software-side stop.
- New `/api/mobile/` router (3 endpoints): `POST /qr/claim`, `GET /sessions/{id}/live` (polling fallback; owner-only 403 guard), `GET /socket/{pid}/{sid}/qr` (admin-only PNG download).
- New `Session.owner_claimed_at` column (nullable). `customer_id` is reused; there is **no** new `owner_user_id` — operators do not claim sessions via QR.
- WebSocket manager gains per-session subscriptions — `broadcast_to_session(session_id, ...)` fans out `session_telemetry` / `session_ended` / `socket_state_changed` only to the mobile client that claimed that session. Global operator dashboard broadcasts are unchanged.
- New short-lived `websocket_token` JWT (1 h, `role="ws_session"`) returned by `/qr/claim`; the mobile app passes it on `/ws?token=...` to establish the per-session subscription.
- Dashboard Control Center: every electricity socket now shows a `QR` button that opens a modal with the printable PNG + URL preview + Download (`{pid}_{Qn}_qr.png`), and a 📱 indicator when the active session has a mobile owner (tooltip shows the owner's name).
- Mobile app (Expo): new deep-link route `app/(app)/mobile/socket/[pedestal_id]/[socket_id].tsx` with loading / claimed / read-only / no-session / ended view states. No Stop button anywhere.
- `docs/mobile_api.md` (NEW) — authoritative mobile contract with auth model, REST schemas, WebSocket event catalog, `owner_claimed_at` semantics table, and Phase-2 marina-access TODO.
- 14 new backend tests (`test_mobile_qr_claim.py`) — auth, 404 branches, all 4 claim paths, `owner_claimed_at` persistence, websocket_token validity, live endpoint auth, QR PNG + customer-403, `session_telemetry` fan-out, `session_ended` + channel close. 248 → 262 total.
- Marina access control **intentionally skipped** — any authenticated customer may claim any socket (prepaid walk-up model). Documented in `docs/mobile_api.md` as Phase-2 TODO.

### 2026-04-21 — Per-socket auto-activation (v3.5)
- New per-socket `auto_activate` flag (default off) — operator toggles it from the Control Center socket card. When enabled, the backend auto-fires the activate command after `UserPluggedIn`, with a 2-second firmware stabilisation delay.
- 5 precondition checks gate the auto-fire (all must pass, in order): door closed (unknown ≡ open), no active fault on the pedestal, heartbeat within 300 s, socket not already active, no diagnostic in the last 60 s. Any failure produces a `socket_auto_activate_skipped` WebSocket event with the reason string and logs a row to the new `auto_activation_log` table.
- Post-sleep re-check before publish — aborts if the operator manually activated during the 2 s window or the plug was yanked.
- Door state now persisted on `PedestalConfig.door_state` (`open | closed | unknown`) so auto-activate survives a service restart.
- 3 new admin endpoints: `GET /api/pedestals/{pid}/sockets/config`, `PATCH /api/pedestals/{pid}/sockets/{sid}/config` (admin-only), `GET /api/pedestals/{pid}/sockets/{sid}/auto-activate-log`.
- Frontend: green `AUTO` badge next to the socket id, optimistic toggle with rollback, amber skip-reason banner below the status block (auto-clears after 30 s or when state leaves pending), dynamic tooltip `"Plug inserted — auto-activating in 2s"` vs. `"awaiting activation"` on the pedestal picture overlay.
- 10 new tests (`test_socket_auto_activate.py`) covering default-false, PATCH admin auth, every skip path, happy path with 2 s delay, and the 20-row log endpoint. 238 → 248 total.
- Existing socket plug state machine (v3.4) preserved as-is; auto-activate layers on top and is a no-op for sockets where the flag is false.

### 2026-04-21 — `4123e8b`  Socket plug state machine (v3.4)
- New `pending` socket state (yellow) in the state flow
  `idle → UserPluggedIn → pending → activate → active → stop → pending|idle`.
- Firmware event `UserPluggedOut` is now handled: active session is stopped cleanly before the socket goes idle.
- Unified `socket_state_changed` WebSocket event — single source of truth for dashboard + Control Center circle colours.
- Operator `activate` rejected with **HTTP 409 "Socket has no plug inserted"** when no plug is reported — prevents the firmware from energising an empty outlet.
- UI: yellow circle on the pedestal picture and yellow `PENDING` badge in the Control Center, both with tooltip "Plug inserted — awaiting activation". Activate button is disabled unless `pending`; Stop button replaces Activate when `active`.
- 8 new tests (`test_socket_plug_state_machine.py`) covering every transition + the 409 guard.

### 2026-04-20 — `72f91ff`  Mobile JWT moved to OS keychain
- Customer JWT migrated from plaintext `AsyncStorage` to `expo-secure-store` (iOS Keychain / Android Keystore).
- Automatic one-shot migration on first launch: existing AsyncStorage tokens are promoted to SecureStore and removed.
- Mobile dependency added: `expo-secure-store ~15.0.7` → run `cd mobile && npm install` once before the next build.

### 2026-04-20 — `c72e389`  Auth hardening
- Rate limiting via `slowapi` on login, OTP verify, register:
  `/api/auth/login` + `/api/customer/auth/login` = 10/min per IP,
  `/api/auth/verify-otp` = 5/min, `/api/auth/register` + `/api/customer/auth/register` = 3/hour.
  Honours `X-Forwarded-For` for nginx/Cloudflare deployments.
- Production startup guard: backend refuses to start when `APP_ENV=production` and `JWT_SECRET` is unset or shorter than 32 chars.
- `/api/auth/register` now returns 404 unless `ALLOW_SELF_REGISTRATION=true` (default off). Customer self-registration (`/api/customer/auth/register`) unchanged — it is the intended mobile signup path.
- Operator JWT expiry shortened **8h → 2h** to reduce the blast radius of a stolen token.

### 2026-04-20 — `18c4de1`  Per-valve water sessions (V1/V2 independent)
- Water sessions now carry the numeric valve id (1 for V1, 2 for V2) instead of sharing `socket_id=NULL`. V1 and V2 can run concurrent sessions and are billed separately.
- Firmware retries on lost ACKs no longer create duplicate sessions: a partial UNIQUE index on `(pedestal_id, socket_id, type) WHERE status IN ('pending','active')` enforces one active row per outlet; `session_service.create_pending` catches the IntegrityError and returns the existing row.

### 2026-04-20 — `791c980`  DB integrity
- `_backfill_session_totals` now clamps at 1 000 kWh / 10 000 L per session so a single corrupt firmware packet cannot become a billable total.
- `invoices.session_id` enforced UNIQUE (index + pre-dedupe); `create_invoice_for_session` is idempotent across the three completion paths (operator stop, customer stop, MQTT disconnect).
- Berth zone-detection enablement is now one-shot per berth (`zone_migration_v1_applied` marker) — admin-set `use_detection_zone=0` stops being flipped back to 1 on every restart.

### 2026-04-20 — `1d6a491`  WebSocket / API catalog drift fix
- `hardware_alarm` broadcast key corrected (`"type"` → `"event"`); the dashboard handler now actually fires on critical hardware alarms.
- `user_plugged_in` frontend handler added.
- External API catalog synced: 4 controls endpoints + 7 events that were advertised but missing (or real but not listed) are now consistent with the code.
- Two AST-walking drift guards added to the test suite so any future divergence between backend broadcasts / frontend cases / catalog fails CI.

### 2026-04-20 — `c479a5e`  Per-valve water indicators on the pedestal picture
- The two water circles on the pedestal image (`water-left`, `water-right`) are bound to V1 and V2 independently — activating V1 from Control Center no longer lights up both circles.

### 2026-04-20 — `6dc17a7`  Analytics corrections
- Session `energy_kwh` / `water_liters` now use `max(readings)` (firmware sends session-cumulative, not lifetime). Short sessions that ended before the first telemetry tick are no longer stored as zero.
- Startup backfill rewrites historical zero rows from existing sensor readings.
- "Consumption by Socket" section on the Analytics page now includes water meters alongside electricity sockets.

---

## Feature Summary

### Dashboard
- Live socket status reflects the full state machine: white (idle), **yellow (pending — plug inserted, awaiting activation)**, green (active), red (fault). Colour updates in real time via the `socket_state_changed` WebSocket event — no refresh.
- Real-time power readings (watts, kWh) via WebSocket
- Water flow meter (LPM, total litres)
- Temperature and moisture sensor alarms (SNMP trap receiver)
- Allow / Deny / Stop session controls
- Marina cabinet door state indicator
- Pending session approval cards with customer name
- **Control Center tab** (per pedestal, admin only) — see below

### Session Management
- State machine: `pending → active → completed / denied`
- Pilot mode: operator must approve before power is enabled
- Customer-initiated sessions from mobile app
- Socket plug-in enforcement — socket must be physically connected before session can start
- Auto-timeout for stale pending sessions (configurable, default 15s)
- Session history with energy (kWh) and water (litres) totals

### Authentication
- Admin and Monitor roles (Monitor = read-only, no controls)
- Two-factor login: POST /login → OTP email → POST /verify-otp → JWT (2h)
- Customer registration / login (JWT role=customer, 30-day expiry)
- PBKDF2-HMAC-SHA256 password hashing (stdlib, no bcrypt dependency)
- Per-IP rate limiting (slowapi): login 10/min, verify-otp 5/min, register 3/hour. Enabled automatically when `APP_ENV=production` or `RATE_LIMIT_ENABLED=true`.
- Operator self-registration via `/api/auth/register` is gated by `ALLOW_SELF_REGISTRATION` (default off → returns 404 in production). Customer signup via `/api/customer/auth/register` is always open.
- Startup refuses to boot in production without a JWT_SECRET ≥ 32 chars.
- Brute-force protection: 5 failures in 5 min → security alarm (complementary to the rate limit).

### Customer App (Mobile — Expo 54 / expo-router 6)
- Customer registration, login, profile (name, ship name)
- Start / stop electricity or water session from phone
- Live session status via WebSocket
- Invoice list with mock payment
- Contract signing with signature pad
- Service orders
- Push notifications (Expo) for session allow / deny
- JWT stored in `expo-secure-store` (OS Keychain / Keystore); web builds fall back to `AsyncStorage`. One-shot migration on first launch after upgrade promotes any legacy AsyncStorage token.
- `mobile/.env` — set `EXPO_PUBLIC_API_URL` and `EXPO_PUBLIC_WS_URL` to LAN IP

### Billing & Invoices
- Configurable kWh and litre pricing
- Auto-generated invoices on session completion — idempotent across the three completion paths (operator stop, customer stop, MQTT disconnect). `invoices.session_id` is UNIQUE; concurrent callers receive the same row.
- Spending reports (per-customer, per-session breakdown)
- Admin billing dashboard with accordion session detail

### Chat
- Customer ↔ operator messaging
- Unread message badge in admin navigation
- Real-time delivery via WebSocket

### Contracts & Service Orders
- Admin creates contract templates
- Customers receive pending contract on registration
- In-app signature capture (react-native-signature-canvas)
- PDF generation (ReportLab) for contracts and invoices
- Service order workflow (customer request → admin fulfil)

### Berth Occupancy (Computer Vision)
- Per-berth analysis: canvas zone selector, reference frame, occupancy detection
- **Laplacian + histogram fallback** (default, no ML required, works on 32-bit dev)
- **OpenVINO ML inference** (opt-in via `USE_ML_MODELS=true` in `.env`):
  - YOLOv8n — boat detection (COCO class 8), INT8/FP32 OpenVINO IR
  - MobileNetV2 Re-ID — 128-dim L2-normalised ship identity embeddings
  - Logs `inference_ms` on every call to measure latency on target hardware
- On-demand RTSP snapshot via ffmpeg (no continuous stream)
- Operator training data loop: save crop → confirm / reject
- Training storage monitor: WebSocket alarm at 80% capacity
- Berth count auto-synced to pedestal count
- **Sector management** (v3.1):
  - **+ Add Sector** button in Berth Occupancy table — create new berths directly without going to Settings
  - Each sector has a user-assigned **berth number** (e.g. #1, #2) shown as a badge in the table
  - Creating a sector immediately opens the zone config + sample image upload in one flow
  - Berth number editable inside ⚙ Sectors modal alongside detection zone config
  - Sample ship image upload per sector for Re-ID Match procedure

### Pedestal Settings — Camera Configuration (v3.1)
- **Stream URL auto-build**: entering FQDN + username + password and clicking *"Build URL from FQDN + credentials"* constructs the full `rtsp://user:pass@host/path` URL
- **Credential injection on save**: when username / password are saved, the backend automatically embeds them into the stored `camera_stream_url` (URL-encoded) so the camera worker always has a complete, authenticated URL — no manual URL editing needed
- Credentials are always masked (`***`) in API responses

### SNMP Trap Receiver
- Listens on UDP :1620 (configurable)
- Decodes BER-encoded SNMP v1/v2c traps (pure Python, no external library)
- Maps OIDs to pedestal sensors; triggers temperature alarm >50°C / moisture >90%
- Configurable per-OID mapping in Settings

### Pedestal Control Center (v3.2)

Accessible via the **Control Center** tab when a pedestal is open in the Dashboard. Requires admin role.

**Live monitoring (real-time from MQTT via WebSocket):**
- Cabinet Status: cabinet ID, heartbeat sequence, uptime, OPTA connected indicator
- Door state: open / closed with visual alarm
- Sockets Q1–Q4: state badge (`idle / pending / active / fault`) — `pending` (yellow) = plug inserted, waiting for operator/customer activation. Shows tooltip "Plug inserted — awaiting activation".
- Water Valves V1–V2: state badge, `hw_status`, total litres, session litres (V1 and V2 are independent sessions since v3.3).
- Event Log: rolling last 30 entries from `opta/events` (expandable)
- Command ACK Log: rolling last 30 entries from `opta/acks` with status (expandable)

**Commands (admin only — publish directly to OPTA via MQTT):**
- Sockets Q1–Q4: `Activate` / `Stop` → `opta/cmd/socket/Q{n}` with `{"action":"activate|stop"}`. **Activate is gated on plug-in state** — the backend returns `409 "Socket has no plug inserted"` and publishes nothing if `SocketState.connected=False`. In the UI the Activate button is disabled (tooltip "No plug inserted") unless the socket is `pending`; when a session is running it is replaced by a Stop button.
- Water Valves V1–V2: `Activate` / `Stop` → `opta/cmd/water/V{n}` with `{"action":"activate|stop"}`
- LED Control: color picker (`green / red / blue / yellow / off`) + state (`on / off / blink`) → `opta/cmd/led`
- Reset Device: double-click confirmation → `opta/cmd/reset` (interrupts all active sessions)
- Time Sync: auto-published to `opta/cmd/time` on Opta restart (seq:0) and every 60 minutes

**Session workflow (no manual approval needed):**
- `UserPluggedIn` (firmware) → socket state `pending` (yellow)
- `UserPluggedOut` (firmware) → socket state `idle`; if a session was active, backend first publishes `{"action":"stop"}` and completes the DB session
- Operator activates from Control Center → Opta responds with `OutletActivated` → session auto-created → `active` (green)
- Customer activates from mobile app → same flow
- Operator stops from Control Center → session auto-completed; socket returns to `pending` if plug still inserted, else `idle`
- No approve/reject flow for Opta sockets — sessions managed entirely via Control Center or mobile app

**New backend endpoints:**
| Method | Path | Description |
|---|---|---|
| POST | `/api/controls/pedestal/{id}/socket/{Q1..Q4}/cmd` | Direct socket command |
| POST | `/api/controls/pedestal/{id}/water/{V1..V2}/cmd` | Direct water valve command |
| POST | `/api/controls/pedestal/{id}/led` | LED color/state command |
| POST | `/api/controls/pedestal/{id}/reset` | Pedestal reset command |

**New WebSocket events (backend → frontend):**
| Event | When fired |
|---|---|
| `opta_socket_status` | `opta/sockets/Q*/status` received — full state, hw_status, session |
| `opta_water_status` | `opta/water/V*/status` received — state, hw_status, total_l, session_l |
| `opta_status` | Heartbeat — cabinet ID, seq, uptime_ms, door |
| `marina_ack` | Command ACK from OPTA — now includes `pedestal_id` |
| `user_plugged_in` | Physical plug detected (legacy informational) |
| `socket_state_changed` | Unified socket state (`idle / pending / active / fault`) — fired on UserPluggedIn/Out, OutletActivated, SessionEnded. This is the canonical signal for dashboard colour changes. |

### External API Gateway
- 14 documented endpoints + 11 webhook events (static catalog)
- API key with 10-year JWT (role=external\_api)
- Webhook delivery on any WebSocket broadcast event
- 30s config cache with invalidation on change
- Admin UI: catalog browser, config, verify, activate, copy key

### System Health (Admin)
- Error log dashboard: filter by category (system/hw), level, time window
- 7-day log retention with hourly auto-purge
- Active alarm summary breakdown
- Security event counts (brute-force, unauthorised access)
- Real-time error badge in navigation

### Hardware Monitoring (NUC, admin only)
- `GET /api/system/hardware-stats` — all hardware parameters in one call (<500ms)
- Refreshes every 10s in dashboard; no background collection threads
- Gauges with 60% (warning) and 80% (critical) threshold markers
- **Alarm 1 (warning)**: yellow banner in System Health + pulsing dot in nav
- **Alarm 2 (critical)**: red banner + WebSocket `hardware_alarm` push to all clients
- **Auto-downgrade on Alarm 2**:
  - CPU ≥80%: `nice(10)` on highest cloud_iot process (protected list enforced)
  - Memory ≥80%: `gc.collect()`
  - Temperature ≥72°C: RTSP frame grab suspended 60s (thermal protection)
  - Disk ≥80%: display-only, no automatic action
- Protected processes never adjusted: `uvicorn nginx cloudflared tailscaled mosquitto sshd`
- Automatic actions log (newest-first, max 100 entries) visible in System Health
- Network interfaces panel: link status, IP, speed, bytes sent/recv
- Thresholds configurable in `.env` (`hw_cpu_warning`, `hw_cpu_critical`, etc.)
- psutil required on NUC: `/opt/cloud-iot/backend/.venv/bin/pip install psutil`

---

## Monitored Parameters

| Parameter | Warning | Critical | Auto-action |
|---|---|---|---|
| CPU usage | 60% | 80% | nice() on top cloud_iot process |
| Memory usage | 60% | 80% | gc.collect() |
| Disk usage | 60% | 80% | display-only |
| CPU temperature | 54°C (60% of 90) | 72°C (80% of 90) | Suspend RTSP grab 60s |

---

## Quick Start (Development)

### Prerequisites
- Docker & Docker Compose
- Python 3.12+ (64-bit for OpenVINO; 32-bit dev works with Laplacian fallback)
- Node.js 18+

### 1. Start MQTT broker
```bash
docker compose up -d
```

### 2. Start backend
```bash
cd backend
python -m venv .venv
source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env         # set JWT_SECRET and DEFAULT_ADMIN_PASSWORD
uvicorn app.main:app --reload
```

### 3. Start frontend
```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173

Default admin: set `DEFAULT_ADMIN_EMAIL` / `DEFAULT_ADMIN_PASSWORD` in `backend/.env`.
OTP prints to the backend console (SMTP not configured by default).

---

## Git Workflow — Pushing Code

**Branch strategy:** `develop` = daily work, `main` = releases only.

### Step-by-step: commit → push → deploy

```bash
# 1. Switch to develop and commit
git checkout develop
git add <files>
git commit -m "type(scope): description"
#    Pre-commit hook runs: 212 pytest + bandit + semgrep + gap checks
#    Commit fails if any check fails — fix and retry

# 2. Push develop
git push origin develop

# 3. Merge develop into main
git checkout main
git merge develop

# 4. Push main (release)
CLOUD_IOT_RELEASE=1 git push origin main
#    Pre-push hook runs: full test suite again + Playwright (if backend running)
#    Requires CLOUD_IOT_RELEASE=1 env var (no interactive terminal in Claude Code)
#    From an interactive terminal, you can type "release" when prompted instead

# 5. Deploy to NUC
ssh cloud_iot@marina-iot
sudo bash ~/Cloud_IOT/nuc_image/upgrade.sh
```

### Git hooks summary

| Hook | When | What it does |
|---|---|---|
| **pre-commit** | Every `git commit` | pytest (212 tests) + bandit + semgrep + eslint + GAP-1..4 checks |
| **pre-push to main** | `git push origin main` | Verifies develop is merged, runs full test suite + Playwright, requires release confirmation |
| **pre-push to develop** | `git push origin develop` | No extra checks (pre-commit already ran) |

### Important rules

- **Never commit directly to main** — always go through develop first
- **Never skip hooks** (`--no-verify`) — if a test fails, fix it
- **`CLOUD_IOT_RELEASE=1`** is required when pushing main from non-interactive terminals (Claude Code, CI). From a regular terminal, the hook prompts you to type "release"
- If pre-commit fails, the commit did NOT happen — fix the issue and commit again (do NOT amend)
- **Every merge to `main` must update the Changelog section at the top of this README** with the commit hash and a short operator-readable summary. The hook does not enforce this — reviewers do. An undocumented release is not a release.

---

## NUC Deployment

The production system runs at `/opt/cloud-iot/` on Ubuntu 24.04.

> **IMPORTANT — Two directories exist on the NUC. Never confuse them:**
>
> | Path | Purpose | Managed by |
> |---|---|---|
> | `/opt/cloud-iot/` | **Production app** — what is actually running | systemd + Docker |
> | `~/Cloud_IOT/` | Git repo — source of truth for updates | git |
>
> The git repo is NOT the running app. Do NOT run uvicorn from `~/Cloud_IOT/`.
> Do NOT install packages into `~/Cloud_IOT/backend/.venv-nuc` for production purposes.

### NUC Services

| Service | Type | What it runs | Check status |
|---|---|---|---|
| `cloud-iot-backend` | systemd | Uvicorn (FastAPI) on :8000 | `systemctl status cloud-iot-backend` |
| `cloud-iot-compose` | systemd (starts Docker) | Docker Compose for MQTT broker | `systemctl status cloud-iot-compose` |
| `pedestal-mqtt-broker` | Docker container | Eclipse Mosquitto 2.0 on :1883 | `docker ps \| grep mosquitto` |
| `nginx` | systemd | Reverse proxy + static frontend | `systemctl status nginx` |
| `cloudflared` | systemd | Cloudflare Tunnel | `systemctl status cloudflared` |
| `tailscaled` | systemd | Tailscale VPN | `systemctl status tailscaled` |

> **Mosquitto runs in Docker, NOT as a systemd service.** The `cloud-iot-compose` systemd unit
> starts Docker Compose which in turn starts the `pedestal-mqtt-broker` container.
> `systemctl status mosquitto` will show "not found" — this is expected.
> To check MQTT broker status, use `docker ps | grep mosquitto`.

---

### ⚠ WARNING — NUC Troubleshooting Rules (Do NOT Repeat These Mistakes)

**When the site is down:**
1. Check if the NUC is physically alive first: `tailscale status` from Windows
2. If NUC shows offline in Tailscale → hardware issue, physical access required
3. If NUC shows online → check services: `sudo cloud-iot status`
4. **Never run uvicorn manually** — `cloud-iot-backend.service` uses `Restart=always`. Running uvicorn manually will conflict on port 8000 and cause confusion.
5. **Never install packages into `~/Cloud_IOT/backend/.venv-nuc`** — production venv is `/opt/cloud-iot/backend/.venv`
6. **Never create a new systemd service** — `cloud-iot-backend`, `cloud-iot-compose`, `nginx`, `cloudflared`, `tailscaled` are all already configured and enabled on boot

**All services auto-start on reboot.** If the NUC reboots cleanly, wait 30–60s and the site will come back on its own. Do not intervene unless a service has `failed` status.

**Quick status check:**
```bash
sudo cloud-iot status        # shows all service states
sudo cloud-iot logs backend  # live backend logs
```

---

### First-time setup (ISO install)

The NUC is provisioned from a pre-built ISO (`nuc_image/cloud-iot-nuc-v2.0.iso`).
The install script handles everything: Python venv, systemd services, nginx, Docker/MQTT.
Do NOT run setup steps manually on an already-provisioned NUC.

> **⚠ Before running ANY first-time install — report the Ubuntu version.**
> Python and apt-package availability change between releases, so each
> Ubuntu version has its own tested installer. Run these on the NUC first:
> ```bash
> cat /etc/os-release | grep -E '^(VERSION_ID|VERSION_CODENAME)='
> python3 --version
> ```
> Then pick the matching script:
>
> | Ubuntu version | Default Python | Install script |
> |---|---|---|
> | 24.04 LTS (noble) | 3.12 | `nuc_image/ubuntu-install.sh` |
> | 26.04 LTS (resolute) | 3.14 | `nuc_image/ubuntu-install-26.04.sh` |
>
> If your release is not in the table, **stop** and report the
> `VERSION_ID` + `python3 --version` output before running anything.
> Pinned dependencies will fail to source-build on untested Python
> versions and leave the NUC half-configured.

```bash
# Optional: Enable ML inference (Laplacian fallback works without it)
echo "USE_ML_MODELS=true" | sudo tee -a /opt/cloud-iot/backend/.env

# Export OpenVINO models (once, takes 5-10 min)
cd /opt/cloud-iot/backend
.venv/bin/python3 ~/Cloud_IOT/backend/setup_openvino_models.py
```

---

### Updating the NUC — Correct Procedure

**The ONLY correct way to update production code on the NUC:**

```bash
# SSH into the NUC (via Tailscale or Cloudflare)
ssh cloud_iot@marina-iot

# Run the upgrade script
sudo bash ~/Cloud_IOT/nuc_image/upgrade.sh
```

**What the script does (step by step):**
1. Shows current version (`git rev-parse --short HEAD` in `~/Cloud_IOT`)
2. `git fetch origin main` — checks GitHub for new commits
3. If already up to date → exits
4. Shows list of commits to apply + which areas changed (backend / frontend)
5. Asks for confirmation (`Apply upgrade? [y/N]`)
6. `git pull origin main` — pulls latest code into `~/Cloud_IOT`
7. **Venv health check** — if `/opt/cloud-iot/backend/.venv/bin/pip` is missing, recreates the entire venv and installs all packages
8. If frontend changed → `npm install` + `npm run build` → copies `dist/` to `/opt/cloud-iot/frontend/dist/` → reloads nginx
9. If `requirements.txt` changed → `pip install -r requirements.txt`
10. Copies `~/Cloud_IOT/backend/app/` → `/opt/cloud-iot/backend/app/`
11. `systemctl restart cloud-iot-backend` → waits up to 15s for it to come up
12. Shows summary: previous version, new version, service status
13. Logs everything to `/var/log/cloud-iot/upgrade.log`

**What it preserves (never touched):**
- `/opt/cloud-iot/backend/.env` — all configuration
- `/opt/cloud-iot/backend/pedestal.db` — IoT data
- `/opt/cloud-iot/backend/data/users.db` — auth/customers
- Docker MQTT broker — not restarted unless Docker config changes

**Never do this instead:**
```bash
# WRONG — do not git pull manually before running upgrade.sh
cd ~/Cloud_IOT && git pull origin main
```
If you `git pull` manually first, `upgrade.sh` will see "already up to date" and skip copying files to `/opt/cloud-iot/`. The production code will remain outdated.

**If you accidentally git-pulled already**, run the copy steps manually:
```bash
sudo cp -r ~/Cloud_IOT/backend/app /opt/cloud-iot/backend/
sudo chown -R cloud_iot:cloud_iot /opt/cloud-iot/backend/app
sudo /opt/cloud-iot/backend/.venv/bin/pip install -r ~/Cloud_IOT/backend/requirements.txt -q
sudo systemctl restart cloud-iot-backend
```

---

### Remote Access to NUC

The NUC has no static IP (behind 5G router). Access is only via:

| Method | When to use |
|---|---|
| Tailscale SSH: `ssh cloud_iot@marina-iot` | Primary remote access |
| Cloudflare Tunnel: `marina.lika.solutions` | Web UI access |
| Physical keyboard/monitor | Last resort — NUC is unreachable remotely |

If both Tailscale and Cloudflare are down → **the NUC is physically offline** (power loss or hardware crash). Do not attempt to reconfigure services remotely. Get physical access.

> **Known fix (applied 2026-04-10):** Tailscale was configured to start before DHCP completed (`network-pre.target`). Fixed via systemd override to `network-online.target`. Also fixed `systemd-networkd-wait-online` with `--any` flag so it doesn't hang waiting for offline interfaces (`enp1s0`, `wlp4s0`). Both fixes are now in `install-cloud-iot.sh` for future ISO builds.

Check NUC connectivity from Windows:
```powershell
tailscale status   # shows if marina-iot is online/offline and last seen time
```

---

### Check logs
```bash
sudo cloud-iot logs backend   # live backend logs
sudo cloud-iot logs nginx     # nginx errors
sudo cloud-iot logs mqtt      # MQTT broker
sudo journalctl -u cloud-iot-backend -n 50 --no-pager  # last 50 lines
```

---

## MQTT Topic Map

### Legacy schema (`pedestal/{id}/...`)
| Topic | Direction | Payload |
|---|---|---|
| `pedestal/{id}/socket/{1-4}/status` | Device → Backend | `"connected"` \| `"disconnected"` |
| `pedestal/{id}/socket/{1-4}/power` | Device → Backend | `{"watts": float, "kwh_total": float}` |
| `pedestal/{id}/socket/{1-4}/control` | Backend → Device | `"allow"` \| `"deny"` \| `"stop"` |
| `pedestal/{id}/water/flow` | Device → Backend | `{"lpm": float, "total_liters": float}` |
| `pedestal/{id}/heartbeat` | Device → Backend | `{"timestamp": str, "online": bool}` |
| `pedestal/{id}/register` | Device → Backend | `{"client_id": str}` |
| `pedestal/{id}/sensors/temperature` | Device → Backend | `{"value": float}` |
| `pedestal/{id}/sensors/moisture` | Device → Backend | `{"value": float}` |

### Marina cabinet schema (`marina/cabinet/{id}/...`)
| Topic | Direction | Payload |
|---|---|---|
| `marina/cabinet/{id}/status` | Device → Backend | `{"cabinetId":"...","seq":N,"uptime_ms":N,"door":"closed"}` |
| `marina/cabinet/{id}/sockets/{n}/state` | Device → Backend | `{"id":"PWR-1","state":"idle\|active","hw_status":"on\|off","ts":N}` |
| `marina/cabinet/{id}/water/{n}/state` | Device → Backend | `{"id":"WTR-1","state":"idle","total_l":N,"session_l":N,"ts":N}` |
| `marina/cabinet/{id}/door/state` | Device → Backend | `{"door":"open\|closed","ts":"..."}` |
| `marina/cabinet/{id}/events` | Device → Backend | `{"eventId":"...","eventType":"TelemetryUpdate\|AlarmRaised\|SessionEnded"}` |
| `marina/cabinet/{id}/acks` | Device → Backend | `{"cmd_topic":"...","status":"ok\|err","ts":N}` |
| `marina/cabinet/{id}/cmd/socket/{n}` | Backend → Device | `{"cmd":"enable\|disable"}` |
| `marina/cabinet/{id}/outlet/PWR-{n}/cmd/stop` | Backend → Device | `{"cmd":"stop"}` |

### OPTA schema (`opta/...`) — cabinetId resolution
> **Important:** Only `opta/status` and `opta/door/status` carry `cabinetId` at the top level.
> Socket, water, power, event, and ack payloads do **NOT** include `cabinetId`.
> The backend caches `cabinetId` from the periodic `opta/status` heartbeat (every ~60s)
> and uses it as a fallback. Events carry `cabinetId` nested under `device.cabinetId`.
> Backend → Device commands always include `cabinetId` in the payload.

| Topic | Direction | Payload |
|---|---|---|
| `opta/status` | Device → Backend | `{"cabinetId":"...","seq":N,"uptime_ms":N,"door":"closed"}` |
| `opta/sockets/Q{1-4}/status` | Device → Backend | `{"id":"Q1","state":"idle\|active\|fault\|blocked","hw_status":"on\|off","session":{...},"ts":N}` *(no cabinetId)* |
| `opta/sockets/Q{1-4}/power` | Device → Backend | `{"id":"Q1","watts":N,"kwh_total":N,"ts":N}` *(no cabinetId)* |
| `opta/water/V{1-2}/status` | Device → Backend | `{"id":"V1","state":"idle\|active","hw_status":"on\|off","total_l":N,"session_l":N,"ts":N}` *(no cabinetId)* |
| `opta/door/status` | Device → Backend | `{"cabinetId":"...","door":"open\|closed","ts":"..."}` |
| `opta/events` | Device → Backend | `{"eventId":"...","eventType":"...","device":{"cabinetId":"...","outletId":"Q2",...},...}` *(cabinetId nested in device)* |
| `opta/acks` | Device → Backend | `{"cmd_topic":"...","status":"ok\|err","ts":N}` *(no cabinetId)* |
| `opta/cmd/socket/Q{1-4}` | Backend → Device | `{"msgId":"...","cabinetId":"...","action":"activate\|stop"}` |
| `opta/cmd/water/V{1-2}` | Backend → Device | `{"msgId":"...","cabinetId":"...","action":"activate\|stop"}` |
| `opta/cmd/led` | Backend → Device | `{"cabinetId":"...","color":"green\|red\|blue\|yellow\|off","state":"on\|off\|blink"}` |
| `opta/cmd/reset` | Backend → Device | `{"cabinetId":"...","cmd":"reset"}` |
| `opta/cmd/time` | Backend → Device | `{"msgId":"timesync-...","action":"sync","epoch":N,"iso":"..."}` *(auto: on seq:0 + every 60min)* |
| `opta/cmd/diagnostic` | Backend → Device | `{"cabinetId":"...","request":"all"}` |
| `opta/diagnostic` | Device → Backend | `{"cabinetId":"...","power":[...],"water":[...],"time":"...","door":"..."}` |

---

## WebSocket Events (Backend → Client)

| Event type | When fired |
|---|---|
| `session_created` | New pending or active session |
| `session_updated` | Status change (allow/deny/stop) |
| `session_completed` | Session ended (stop or device disconnect) |
| `power_reading` | Real-time socket power data |
| `water_reading` | Real-time water flow |
| `temperature_reading` | Temperature sensor update |
| `moisture_reading` | Moisture sensor update |
| `heartbeat` | Pedestal online/offline |
| `socket_pending` | Device plugged in — operator approval needed |
| `socket_rejected` | Operator rejected socket connection |
| `socket_state_changed` | Unified socket state (`idle / pending / active / fault`) — canonical feed for UI circle colour |
| `user_plugged_in` | Physical plug detected (legacy informational) |
| `invoice_created` | Invoice written after session completion |
| `session_telemetry` | **Mobile only** — per-session live metrics sent to the scanning customer |
| `session_ended` | **Mobile only** — session completed; server closes the subscriber socket after sending |
| `pedestal_registered` | Cabinet auto-discovered (`is_new=true`) or reconnected (`is_new=false`, throttled 60 s/pedestal) |
| `error_logged` | New entry in error log |
| `pedestal_health_updated` | Camera or OPTA reachability change |
| `pedestal_reset_sent` | Reset command dispatched |
| `berth_occupancy_updated` | Berth analysis result |
| `hardware_alarm` | CPU/memory/disk/temperature Alarm 2 |
| `marina_door` | Cabinet door open/close |
| `marina_event` | Generic event from cabinet firmware |
| `marina_ack` | Command ACK from cabinet (includes `pedestal_id`) |
| `direct_cmd_sent` | Direct socket/water/LED/reset command dispatched |
| `opta_socket_status` | `opta/sockets/Q*/status` — state, hw_status, session |
| `opta_water_status` | `opta/water/V*/status` — state, hw_status, total_l, session_l |
| `opta_status` | `opta/status` — cabinet ID, seq, uptime_ms, door |

---

## Environment Variables (backend/.env)

| Variable | Default | Description |
|---|---|---|
| `APP_ENV` | `dev` | Set to `production` on the NUC. Activates strict startup guards (JWT_SECRET length, rate limiting). |
| `JWT_SECRET` | (random in dev) | **Required and ≥ 32 chars in production** — startup fails if missing. |
| `JWT_EXPIRE_MINUTES` | `120` | Operator JWT lifetime. Default 2h; customer JWTs use a separate 30-day lifetime. |
| `ALLOW_SELF_REGISTRATION` | `false` | When false, `/api/auth/register` returns 404. Flip to `true` only for dev or admin-invite flows. Customer `/api/customer/auth/register` is unaffected. |
| `RATE_LIMIT_ENABLED` | (auto) | Force-enable slowapi limits. Auto-on when `APP_ENV=production`. |
| `DEFAULT_ADMIN_EMAIL` | `admin@iot-dashboard.local` | Seeded on first run |
| `DEFAULT_ADMIN_PASSWORD` | — | Required for first-run seed |
| `MQTT_BROKER_HOST` | `localhost` | Mosquitto host |
| `MQTT_BROKER_PORT` | `1883` | Mosquitto port |
| `USE_ML_MODELS` | `false` | Enable OpenVINO inference for Berth Occupancy |
| `HW_CPU_WARNING` | `60.0` | CPU % → Alarm 1 |
| `HW_CPU_CRITICAL` | `80.0` | CPU % → Alarm 2 + auto nice() |
| `HW_MEM_WARNING` | `60.0` | Memory % → Alarm 1 |
| `HW_MEM_CRITICAL` | `80.0` | Memory % → Alarm 2 + gc.collect() |
| `HW_DISK_WARNING` | `60.0` | Disk % → Alarm 1 |
| `HW_DISK_CRITICAL` | `80.0` | Disk % → Alarm 2 (display only) |
| `HW_TEMP_MAX` | `90.0` | Maximum safe CPU temperature (°C) |
| `HW_TEMP_WARNING_PCT` | `60.0` | 60% of max → Alarm 1 (54°C) |
| `HW_TEMP_CRITICAL_PCT` | `80.0` | 80% of max → Alarm 2 (72°C) + RTSP suspend |
| `SMTP_HOST` | — | Leave empty to print OTP to console |
| `PENDING_TIMEOUT_SECONDS` | `15` | Auto-deny stale pending sessions |

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.12, FastAPI, Uvicorn, SQLAlchemy 2.0 |
| Database | SQLite (pedestal.db + data/users.db) |
| MQTT | paho-mqtt 2.x, Eclipse Mosquitto 2.0 (Docker) |
| Auth | PyJWT, PBKDF2-HMAC-SHA256, smtplib OTP, slowapi (rate limiting) |
| Computer Vision | OpenVINO 2026, YOLOv8n, MobileNetV2, Pillow, psutil |
| PDF | ReportLab |
| Frontend | React 18, TypeScript, Vite, Zustand, Recharts, Tailwind CSS |
| Mobile | Expo 54, expo-router 6, React Native, expo-secure-store (JWT keychain) |
| Push Notifications | Expo Push API (httpx fire-and-forget) |
| Hardware | Intel Atom x7425E NUC, Ubuntu 24.04 |

---

## Test Suite

```bash
cd Cloud_IOT
backend/.venv/Scripts/python -m pytest tests/backend/ -q
```

**275 tests** covering:
- Session lifecycle and MQTT integration
- Operator approval flow and timeouts
- Customer auth and billing
- Chat, contracts, service orders
- Berth occupancy / computer vision
- Hardware stats endpoint and all alarm thresholds
- Downgrade actions (CPU nice, memory GC, temperature suspension, disk display-only)
- Protected process list enforcement
- External API gateway
- Security (brute-force, SQL injection patterns)
- SNMP BER decoder
- **Direct device controls** (socket Q1–Q4, water V1–V2, LED, reset, auth enforcement)
- **MQTT Control Center broadcasts** (`opta_socket_status`, `opta_water_status`, `opta_status`, `marina_ack` pedestal_id)
- **Socket plug state machine** (UserPluggedIn/Out, socket_state_changed transitions, activate-when-no-plug → HTTP 409)
- **Auth hardening** (rate limiting on login/otp/register, `ALLOW_SELF_REGISTRATION` flag, production JWT_SECRET guard)
- **DB integrity** (bounded backfill, invoice idempotency, partial unique index on active sessions, per-valve water session split)
- **Contract drift guards** (AST walk — backend broadcasts vs. frontend cases, route vs. ENDPOINT_CATALOG)
- **Mobile QR claim + session telemetry** (auth, 404 branches, 4 claim paths, owner_claimed_at persistence, websocket_token validity, per-session WS fan-out, admin-only QR PNG)
- **Pedestal + socket auto-discovery + QR bundle** (name-pretty first-creation, operator-rename survival, SocketConfig auto-create, QR cache idempotency, `/qr/all` ZIP + `/qr/regenerate`, `pedestal_registered` throttle)

Pre-commit and pre-push hooks run the full suite automatically. Pushes to `main` require `CLOUD_IOT_RELEASE=1` and a merged `develop` branch.
