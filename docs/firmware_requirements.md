# Firmware ↔ Backend Contract (Arduino Opta)

This document captures the non-code contract between the Arduino Opta firmware
and the NUC-side Cloud_IOT backend. It lives here — not in the README changelog
— because firmware and backend teams iterate on different schedules and the
rules below must survive either side's refactors.

Entries are newest-first. Each rule lists the WHY so a reader can decide
whether an exception is safe.

---

## v3.11 — Hardware config + meter telemetry topics (2026-04-28)

### New publishes the firmware MUST add

The backend in v3.11 subscribes to two new topics. Until the Arduino sketch
publishes them, the load-monitoring feature is **dormant** (same pattern as
v3.8 breakers): every SocketLoadMeterPanel will display *"Awaiting hardware
configuration from device"* and the System Health page will list zero load
alarms because no telemetry ever arrives.

#### `opta/config/hardware` — one-shot per cabinet, retained recommended

Publish on first MQTT connect AND in response to every diagnostic request.
Required keys per socket: `socketId` (Q1..Q4), `phases` (1 or 3), `ratedAmps`
(real, per-phase rating in amps). Optional but useful: `meterType`,
`modbusAddress`. The backend stores whatever fields are present and never
overwrites a previously-stored value with `null` on a later message that omits
the key. So once you have published `meterType: "ABB D11 15-M 40"` you do not
need to send it on every subsequent config message — but you may.

```json
{
  "cabinetId": "MAR_KRK_ORM_01",
  "firmwareVersion": "2.1.0",
  "sockets": [
    {"socketId": "Q1", "meterType": "ABB D11 15-M 40", "phases": 1, "ratedAmps": 16, "modbusAddress": 1},
    {"socketId": "Q2", "meterType": "ABB D11 15-M 40", "phases": 1, "ratedAmps": 32, "modbusAddress": 2},
    {"socketId": "Q3", "meterType": "ABB D11 15-M 40", "phases": 1, "ratedAmps": 32, "modbusAddress": 3},
    {"socketId": "Q4", "meterType": "ABB D13 15-M 65", "phases": 3, "ratedAmps": 65, "modbusAddress": 4}
  ],
  "valves": [
    {"valveId": "V1", "ratedLitersPerMin": 20},
    {"valveId": "V2", "ratedLitersPerMin": 20}
  ]
}
```

**Recommendation:** publish with `retain=true` so a backend restart sees the
configuration immediately, the same way `opta/status` already works. Without
retain, the dashboard shows "Awaiting hardware configuration" for ~5 minutes
after a restart.

#### `opta/meters/{socketId}/telemetry` — every 5 s while powered

The firmware decides single-phase vs three-phase **per socket**, based on
which Modbus meter is wired to that socket's RS-485 address. The payload
shape signals the phasing to the backend:

- **Single phase** — include `currentAmps`. Backend interprets this as 1Φ.
  ```json
  {
    "cabinetId": "MAR_KRK_ORM_01",
    "socketId": "Q1",
    "currentAmps": 14.7,
    "voltageV": 231.2,
    "powerKw": 3.39,
    "powerFactor": 0.98,
    "energyKwh": 1234.56,
    "frequency": 50.0,
    "ts": 12345678
  }
  ```

- **Three phase** — include `currentAmpsTotal` (and per-phase L1/L2/L3).
  Backend interprets this as 3Φ.
  ```json
  {
    "cabinetId": "MAR_KRK_ORM_01",
    "socketId": "Q4",
    "currentAmpsL1": 12.1,
    "currentAmpsL2": 11.8,
    "currentAmpsL3": 12.3,
    "currentAmpsTotal": 36.2,
    "voltageL1": 231.0,
    "voltageL2": 230.8,
    "voltageL3": 231.5,
    "powerKwTotal": 8.37,
    "powerFactor": 0.97,
    "energyKwh": 567.89,
    "frequency": 50.0,
    "ts": 12345678
  }
  ```

**Important — the backend does NOT trust phase count from the topic name or
the socket id.** It looks at the payload: `currentAmps` ⇒ 1Φ, `currentAmpsTotal`
⇒ 3Φ. So Q1..Q4 can be any mix of single- and three-phase as long as the
`opta/config/hardware` `phases` field matches what the meter actually reports.

**Load percentage formula** (informational; firmware doesn't compute this):
- 1Φ: `currentAmps / ratedAmps × 100`.
- 3Φ: `max(L1, L2, L3) / ratedAmps × 100` — bottleneck phase. The backend
  uses this even though the spec literal said total/rated; the spec was wrong
  for IEC standard 3Φ rated current (it is per-phase, not summed).

`ratedAmps` is interpreted as **per-phase rated current** for both 1Φ and 3Φ
meters, matching every IEC breaker rating you'll find on a circuit breaker.

### Recommended cadence

- `opta/config/hardware` — once at connect, plus on diagnostic. Don't churn it.
- `opta/meters/+/telemetry` — every 5 s while the cabinet is alive, regardless
  of whether the socket is in an active session. The backend handles
  before-config-arrived gracefully (stores raw values, skips load_pct), so
  starting the telemetry loop early is fine.

### Color reservation note (recap from v3.10)

Backend still ships LED schedule color set `{green, blue, red, yellow}` only.
`white` remains reserved until the firmware team confirms `handleLedCmd`
accepts it. No change in v3.11.

---

## v3.10 — LED color set + opta/cmd/led contract (2026-04-28)

### Backend ships `{green, blue, red, yellow}` only. `white` is reserved.

**Rule:** The v3.10 LED schedule API only accepts color values from the set
`{green, blue, red, yellow}`. The Arduino sketch's `handleLedCmd` is documented
to drive these four. The product spec asked for "white" but it is **not yet
firmware-validated** — calling `mqtt.publish("opta/cmd/led", {"color": "white", ...})`
on the current Lika v2.1 sketch is undefined behaviour.

**Why:** Avoid a backend-produced color that the firmware silently drops on the
floor. The dashboard would happily show "LED set to white" while the cabinet
LED stays whatever-it-was-before — exactly the kind of phantom-state bug the
backend should never enable.

**How to apply:** Two paths to add white later:
1. Confirm with the firmware team that `handleLedCmd` accepts `"color":"white"`
   (verify in `LLSketch.ino` near the existing color-string switch).
2. If yes, extend the Pydantic validator + `_LED_COLORS` set in
   `backend/app/routers/pedestal_config.py` AND the `LED_COLORS` array in
   `backend/app/routers/controls.py::LedBody` AND `frontend/src/components/pedestal/LedScheduleSection.tsx::COLORS`.

Until that confirmation, leave white out of the API.

---

## v3.9 — Backend-initiated water valve activate (2026-04-25)

### Firmware emits `OutletActivated` for every accepted activate command

**Contract:** When the backend publishes `{"action":"activate", "msgId":"..."}`
on `opta/cmd/water/V{n}` WITHOUT a `sessionContext` block, the firmware MUST
still:

1. Open the valve relay.
2. Generate an internal `ormarSessionId` (e.g. `OBE-S-0042`).
3. Publish an `OutletActivated` event on `opta/events` with
   `device.resource="WATER"` and `session.mmSessionId=""` (empty).

**Why:** The v3.9 post-diagnostic auto-open flow publishes activate commands
without a customer context. The backend needs the `OutletActivated` event to
materialise an "unattributed" `customer_id=NULL` water session so incoming
flow readings have a `session_id` to attach to. If the firmware silently drops
activate commands that lack `sessionContext.customerId`, every litre auto-flow
will land in `sensor_readings` with `session_id=NULL` and the dashboard will
never show the open valve.

**How to apply:** Confirmed in the current sketch
(`Lika - v2.1/LLSketch/LLSketch.ino`):

- `handleWaterCmd` (L1080-1120) — `mmSessionId` and `customerId` extraction is
  best-effort; `startWaterSession(idx)` is called unconditionally for any
  `action == "activate"` that survives the FAULT check.
- `startWaterSession` (L937-949) — calls `sendOutletActivated` after opening
  the relay. The `mmSessionId` field in the emitted JSON will be an empty
  string when the original command lacked session context.

**Three documented silent-skip cases** (firmware does NOT emit `OutletActivated`):

1. Valve in `STATE_FAULT` → publishes ACK
   `{"status":"error","reason":"outlet_fault"}` on `opta/acks`. Backend should
   surface this ACK to the operator.
2. Valve not in `STATE_IDLE` (already active or in maintenance) →
   `startWaterSession` returns silently. The backend's "no active session"
   guard prevents this case from being reached on the auto-open path.
3. Idempotency cache hit (same `msgId` seen recently in the firmware's
   16-entry circular cache) → publishes ACK `ok` but does NOT re-fire the
   session. Backend `_maybe_auto_open_valve` builds unique `msgId =
   int(datetime.utcnow().timestamp() * 1000)` so this only matters if the
   exact same logical event is replayed within the cache window.

**Do not change:** the firmware's `startWaterSession` logic is the contract.
Adding a `sessionContext`-required gate would break v3.9 auto-open and the
v3.6 mobile QR claim flows.

---

## v3.8 — Breaker status topic (2026-04-24)

### Publish `opta/breakers/{socket_id}/status` as **retained**

**Rule:** When the Arduino publishes to `opta/breakers/Q{n}/status` it SHOULD
set the MQTT `retain` flag to `true`.

**Why:** The backend recreates the in-memory socket state on every startup
(the `pedestals` and `socket_states` tables are cleared in the lifespan hook
and repopulated from live MQTT traffic). Without a retained message the
dashboard will show `breaker_state: "unknown"` for a full heartbeat cycle
(15 s) after a backend restart. With retain, the broker replays the last
state on reconnect and the operator sees the correct red/green dot
immediately.

**How to apply:** In the Arduino sketch wherever the breaker status is
published, pass `true` for the `retained` argument (PubSubClient):

```c
mqtt.publish(TOP_BREAKER_STATE_i, buf, true /* retained */);
```

This matches the convention already used for `opta/status` and
`opta/door/status`. `opta/sockets/+/status` is intentionally **not** retained
because outlet state changes every 15 s and retention would get stale — but
breaker state changes are rare (one event per trip / reset), so retention is
correct here.

**No behavioural fallback:** the backend will still work with non-retained
messages; the only downside is the 15 s blind window after a restart.

---

## Open questions for the firmware team — nothing asked yet (2026-09-30)

**Not requests.** A running list of things the backend would benefit from, kept here so that
if we ever open a firmware conversation we bring the whole list rather than the one item that
happened to be annoying that week. Each says what the backend does today without it, because
the workaround is the honest measure of how much the change is worth.

### 1. Packet timestamping we can trust

`opta/status` and the per-outlet topics carry `ts` as a **`millis()` uptime**, not a wall
clock. Two consequences:

* It rolled over at **24.85 days** on a signed int32 and took the cabinet silent with it
  (confirmed on MAR_KRK_ORM_01, firmware 3.0.0, 2026-09-20). The cabinet does not
  self-recover; it needs a power cycle.
* We cannot tell a **retained replay** from live traffic by the payload alone. Liveness has to
  come from elsewhere entirely (`$SYS/broker/clients/connected`, or in-memory heartbeat
  tracking) — see `docs/engineering_notes.md` rule 1, which exists because of this.

**Ask:** an unsigned monotonic counter at minimum; a wall-clock stamp set from `opta/cmd/time`
would let a replay be recognised on sight.

### 2. A per-valve status equivalent to a socket's

*Refined 2026-09-30 after checking the capture rather than the docstring.* The valve topic is
**not** missing, which an earlier version of this list implied. `opta/water/V{n}/status`
carries `state`, `hw_status`, `total_l` and `session_l`, and v3.43 persists the first two.

Two specific things a socket has and a valve does not:

| Socket has | Valve equivalent | What the backend does without it |
|---|---|---|
| **Plug-in detection** — `UserPluggedIn`, and a `connected` flag in `socket_states`, so "physically connected, awaiting activation" is a real state | none | a valve has no `pending` state. The QR landing tells a customer to open the tap rather than reporting what the outlet is waiting for. |
| **Fault in the status topic**, so a fault is visible by polling | `STATE_FAULT` exists, but is reported only **reactively** — an attempt to open a faulted valve answers on `opta/acks` with `{"status":"error","reason":"outlet_fault"}` (v3.9 section above) | `/api/nfc/scan` runs before any open command, so it cannot pre-check a valve for faults the way it does a socket. A customer can be told "open your tap" at a faulted outlet and find out by trying. |

**Ask:** surface `STATE_FAULT` in `opta/water/V{n}/status` as well as in the ACK. The ACK is
the right place for the command result; it is the wrong and only place for a condition that
persists.

A "hose connected" sensor is hardware, not firmware, and is **not** being asked for — noted
only so the absence reads as deliberate rather than overlooked.

### 3. `opta/config/hardware` fits in one MQTT publish

The firmware truncates this message at **~502 bytes**, severing the trailing `valves` array
(fw 2.4.0/2.5.0; the tolerant parser in `_recover_truncated_hwconfig` reconstructs the sockets
and loses the valves). v3.43 now persists valves from this message, so a truncated publish is
handled by treating an **absent** `valves` key as "no news" rather than "no valves" — but that
is a workaround for a payload that should simply arrive whole.

**Ask:** a larger MQTT publish buffer, and `retain` on this topic so a late subscriber does
not have to wait for a cabinet restart to learn what the cabinet has.

---

## Backward context — topics in this contract

```
opta/status                   retained  cabinet heartbeat (15 s)
opta/sockets/Q{n}/status      NO        per-socket state + session info
opta/sockets/Q{n}/power       NO        power metrics (watts, kWh)    [backend subscribes; firmware embeds in events]
opta/water/V{n}/status        NO        per-valve state
opta/door/status              retained  cabinet door open/closed
opta/events                   NO        structured JSON events (UserPluggedIn, OutletActivated, SessionEnded, AlarmRaised, BreakerTripped, DoorOpened, DoorClosed)
opta/acks                     NO        command acknowledgements
opta/diagnostic               NO        diagnostic response
opta/breakers/Q{n}/status     retained  ← v3.8, this doc

opta/cmd/socket/Q{n}          NO        activate / stop
opta/cmd/water/V{n}           NO        activate / stop
opta/cmd/reset                NO        pedestal reset
opta/cmd/led                  NO        LED indicator
opta/cmd/time                 NO        RTC sync
opta/cmd/diagnostic           NO        diagnostic trigger
opta/cmd/breaker/Q{n}         NO        ← v3.8 remote breaker reset
```

---

## Contact

Backend side: `backend/app/services/mqtt_handlers.py` is the source of truth
for every topic the server subscribes to. If you add a new topic, update
`mqtt_client.TOPICS` and the regex + handler in `mqtt_handlers.py`, then add
a note here with the retain requirement and a link to the commit.
