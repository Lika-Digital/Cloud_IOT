# Firmware ↔ Backend Contract (Arduino Opta)

This document captures the non-code contract between the Arduino Opta firmware
and the NUC-side Cloud_IOT backend. It lives here — not in the README changelog
— because firmware and backend teams iterate on different schedules and the
rules below must survive either side's refactors.

Entries are newest-first. Each rule lists the WHY so a reader can decide
whether an exception is safe.

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
