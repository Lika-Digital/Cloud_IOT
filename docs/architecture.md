# Cloud_IOT — how the system actually works

**Status:** current as of 2026-10-01 (v3.43). **Supersedes** any statement elsewhere about
topics, billing figures or the ERP contract that contradicts it.

Written after two weeks of foundation work during which several things the codebase asserted
about itself turned out to be false. Where a claim here contradicts an older document, this
one is right **and the older one is named**, because the failure mode worth preventing is
someone finding the stale version and believing it.

Every claim about hardware in this document is traceable to a capture. Claims not traceable to
a capture are marked **UNVERIFIED** and should be treated as what we hope, not what is.

---

## 0. THE FINDING THAT MATTERS MOST — three topic families, one real

> **Read this before writing any code that touches MQTT.**

The backend subscribes to **three** topic families. **One** is published by real hardware.

| Family | Status | Evidence |
|---|---|---|
| **`opta/*`** | **REAL.** Everything new targets this. | Full MQTT capture, MAR_KRK_ORM_01, firmware 3.1.0, 2026-09-29 |
| `marina/cabinet/*` | **ASPIRATIONAL.** Nothing publishes it. Nothing bridges the prefixes. Every `MARINA_*` handler fires **only from tests**. | Absence from the same capture |
| `pedestal/*` | **LEGACY.** The manual test tool speaks this. The simulator that also spoke it was deleted 2026-03-15 (`be0df4f`). No firmware has ever used it. | — |

Subscribing to all three is cheap and harmless. **Believing all three is what cost us.**

### What it actually cost

1. **A whole family of handlers maintained against nothing.** Six `MARINA_*` regexes with
   handlers behind them, exercised only by tests written from the same assumption. A green
   suite proving that our code agrees with our own fiction.

2. **Seven command publishes that nobody received.** `controls.py` published allow / deny /
   stop to `marina/cabinet/{id}/cmd/socket/E{n}` while the Opta listens on `opta/cmd/*`.
   **No test asserted them**, which is its own signal — nobody had ever checked that the most
   important outbound message in the system arrived. Removed in v3.43.

   > A publish nobody receives is worse than no publish, because it reads as working.

3. **`WTR-1` in a production allowlist for months.** The water-outlet name allowlist was
   seeded from a **docstring** describing the aspirational payload. Real traffic has only ever
   said `V1`/`V2`. The docstring had become a source of truth about hardware it had never been
   checked against.

4. **Two source comments that said the opposite of the truth.** Both
   `mqtt_handlers.py` and `mqtt_client.py` labelled `marina/cabinet/*` *"(real hardware)"*.
   Corrected 2026-09-30 and 2026-10-01 respectively — the second was found only because this
   document was being written, which is the argument for writing it.

### The rule

- **UI v2, and all new code, is written against `opta/*`.**
- The `MARINA_*` handlers **stay** (no capture exists for other firmware builds, so deleting
  them discards information) but are **not to be extended**, and no new code may assume them.
- If firmware ever moves to that prefix it will be a **deliberate migration with a capture to
  prove it**, not a drift discovered later.

### What the real cabinet publishes

From the capture. Retain flags matter: a retained topic replays to every new subscriber, which
is why **liveness can never be inferred from one** (§7).

```
opta/status                     retained   cabinet heartbeat, 15 s
opta/config/hardware            NO         one shot: enumerates sockets AND valves
opta/sockets/Q{1..4}/status     NO         per-socket state + session info
opta/sockets/Q{n}/power         NO         power metrics
opta/water/V{1..2}/status       NO         state, hw_status, total_l, session_l
opta/meters/Q{1..4}/telemetry   NO         live electrical telemetry, 5 s
opta/breakers/Q{1..4}/status    retained   breaker state
opta/door/status                retained   door open/closed
opta/events                     NO         UserPluggedIn, OutletActivated, SessionEnded, …
opta/acks                       NO         command acknowledgements
opta/diagnostic                 NO         diagnostic response

opta/cmd/socket/Q{n}            →  activate / stop        (the ONLY command path that works)
opta/cmd/water/V{n}             →  activate / stop
opta/cmd/{reset,led,time,diagnostic}
opta/cmd/breaker/Q{n}
```

---

## 1. The cabinet is not four identical sockets

`opta/config/hardware` enumerates the cabinet. On MAR_KRK_ORM_01:

| Outlet | Meter | Phases | Rating | Modbus |
|---|---|---|---|---|
| **Q1** | ABB D13 15-M 65 | **3** | 32 A | 1 |
| Q2 | ABB D11 15-M 40 | 1 | 32 A | 2 |
| Q3 | ABB D11 15-M 40 | 1 | **16 A** | 3 |
| Q4 | ABB D11 15-M 40 | 1 | **16 A** | 4 |
| **V1, V2** | — | — | 20 L/min each | — |

Three consequences that are not cosmetic:

1. **The telemetry payload shape differs by socket.** Three-phase Q1 sends
   `currentAmpsL1..L3` / `powerKwTotal`; Q2–Q4 send `currentAmps` / `powerKw`. A parser or a
   component that assumes one shape is a real defect, not a styling detail.

2. **Ratings differ.** Any load display or limit must come from the cabinet, never a constant.
   "This berth is on a 16 A socket and the customer wants 32 A" is a question staff ask.

3. **The message does not fit in one publish.** The firmware truncates it at **~502 bytes**,
   severing the trailing `valves` array. `_recover_truncated_hwconfig` reconstructs the
   sockets; the valves are lost. So **absent and empty must be distinguished**: a missing
   `valves` key means "no news", never "this cabinet has no valves", or one truncated publish
   erases the cabinet's water provisioning *and looks like a successful update* because the
   sockets did apply.

---

## 2. Six NFC tags, and attribution by scanned tag

A cabinet with 4 sockets and 2 water outlets carries **six** NFC tags, one per outlet.
**Water works exactly like electricity.** The customer scans the tag on the outlet they are
about to use, and the session belongs to whoever scanned.

> **Attribution is by scanned tag. Never by berth.** The dashboard is organised by berth for
> **monitoring**; billing has never followed that axis. Conflating the two is a mistake already
> made and corrected once in this project.
>
> **Monitoring axis ≠ billing axis.** A shared valve is therefore a *scheduling* constraint,
> not an attribution problem, and "(shared with berth N)" is a monitoring clarification rather
> than a billing caveat.

### The type is stored, not derived

`nfc_tags.outlet_type` is `"socket"` or `"valve"`, **stored**. This is not a style preference:
both inbound name vocabularies accept bare digits, so `"1"` cannot distinguish socket 1 from
valve 1. There is no function that could recover it later.

A **mismatch is refused, not corrected** — `V1` declared as a socket is a 400. Either the name
or the type is wrong and nothing on the server knows which; picking one writes a mapping
nobody asked for, and this mapping decides which outlet a customer's tap energises.

### The numeric collision is load-bearing

A water session on V1 and an electricity session on Q1 are **both `socket_id = 1`**, separated
only by `Session.type`. Everything that looks up a session, a config or a state by outlet must
filter on the type. Three places did not, and each produced a *plausible wrong answer*:

| Where | What it did |
|---|---|
| `/api/nfc/scan` availability check | told a customer at V1 that "this socket is already in use" because Q1 was busy |
| `build_session_payload` | reported a water session to ERP as outlet `"Q1"` with socket 1's cumulative **electricity** register as its `energy_kwh`, priced at the kWh tariff |
| mobile session adoption | `outletNum` was `null` for `V1`, and the adoption check treats null as "matches anything" — a water scan adopted the next electricity session under that user id |

### Water tags are gated on the app version

A valve tag cannot be provisioned while the site is in direct-client mode (no ERP) and
`MOBILE_APP_SUPPORTS_WATER_NFC` is false. Enforced **at the write site** (`provision_tag`), so
the single endpoint, the bulk pre-pass, a script, or anything added later are all covered.
Mode 1 is checked **first** and exempt: there the ERP resolves the tag itself, so no app
version is in the path.

---

## 3. Consumption is forwarded, never computed

> **The meter's own cumulative register is the figure. We forward it. We do not derive it.**

A session's electricity and water figures are `end − start` of the meter's own monotonic
register, captured at activation and at completion, and **both endpoints are stored** so a
disputed charge can show what the meter read at each end.

### Why: the previous method was not trustworthy

The old figure integrated `powerKw` over time. The capture shows why that fails:

- **Q2 reported 0.181 kW for six minutes while its register never moved.**
- **Q4 reported 2.347 kW at 0.19 A and 230.7 V** — not physically consistent.

`powerKw` survives for **live display only**. The sanity clamp stays, but it now **raises an
alarm** (`meter_power_implausible`) rather than silently correcting — a value quietly fixed is a
value nobody investigates.

### `consumption_source` is part of the contract

Every session records how its figure was derived:

| Value | Meaning |
|---|---|
| `register` | the meter's own arithmetic. Normal. |
| `integrated_legacy` | an estimate from the old method. **Closed-ended** — only sessions already running when v3.43 deployed. An **assertion at the write site** refuses it for anything started later, so the rule cannot become false rather than merely being true when someone last ran the tests. |
| `unknown` | not derivable. **Never `0.0`.** |

A figure shown without its provenance is how the old workaround survived three months
unnoticed. Any UI showing a number that is not `register` must say so in plain words.

### Zero and unknown are different rows

A register that **did not move** is a measured zero and gets a ledger row. A register that
**could not be read** produces **no row**, and the session total containing it is `unknown`.
One unreadable interval makes the whole session's figure unknown — deliberately: the sum of a
partial set is not the total, and reporting it as one is a silent under-report that favours the
customer least.

### The ledger agrees with itself

Each `energy_intervals` row is a register delta over its window, so **the sum of a session's
rows equals its reported figure by construction** (`TC-EIV-10`). "What does this customer owe"
is answered from the ledger; the session field is a *summary of* the ledger, not a second
source. Any history or analytics view aggregates interval rows.

This holds for **water as well as electricity**. `valve_configs.meter_total_l` is the water
counterpart of `socket_configs.meter_energy_kwh`, and `sessions.water_liters` is a register
delta exactly as `energy_kwh` is.

---

## 4. Valve state exists — and is narrower than a socket's

**Corrected 2026-09-30.** An earlier report said the firmware publishes no valve state, that
report was accepted, and a UI workaround shipped on it. It was wrong.

`opta/water/V{n}/status` has always carried:

```json
{"id":"V1","state":"idle","hw_status":"off","ts":118475996,
 "total_l":0.000,"session_l":0,"session":null}
```

The handler **broadcast both fields over the websocket and stored neither**. So any reader not
listening at that instant fell back to `socket_states` — which is keyed by outlet **number
alone** — and answered a question about V1 with socket 1's plug-in signal: *"cable detected"*
on a tap, or *"idle"* while water ran. Not a missing answer; a plausible wrong one.

v3.43 persists `last_state`, `last_hw_status` and `state_updated_at` on `valve_configs`, and
reports **`unknown`** when the value is missing or older than **60 s** — a stored state is only
as good as its age.

### What a valve genuinely lacks

| Socket has | Valve | Consequence |
|---|---|---|
| **Plug-in detection** (`UserPluggedIn`, `socket_states.connected`) so "physically connected, awaiting activation" is a real state | none | **a valve has no `pending` state.** Four states, not five. |
| **Fault in the status topic**, visible by polling | `STATE_FAULT` exists but is reported **reactively only** — an attempt to open a faulted valve answers on `opta/acks` with `{"status":"error","reason":"outlet_fault"}` | **`/api/nfc/scan` cannot pre-check a valve for faults** the way it pre-checks a socket, because it runs before any open command. The fault surfaces where it can: the ACK handler, on activation. |

Both are recorded as open firmware questions (`docs/firmware_requirements.md`). Neither is
worked around with an invented value — a check that always passes is indistinguishable from a
check that works.

---

## 5. Two topologies, and what changes between them

| | **MODE 1 — with ERP** | **MODE 2 — direct client** |
|---|---|---|
| Flag | `NFC_DIRECT_CLIENT_MODE=false` (default) | `=true` |
| Path | app → ERP → pedestal | app → pedestal |
| **Who bills** | **the ERP** | **the pedestal** |
| Our session rows are | measurement + reconciliation data | **the financial record itself** |
| NFC session endpoints accept | the ERP machine key (the caller really is a server) | **a per-customer token, required** |
| Water tag gate | exempt (ERP resolves the outlet) | enforced until the app ships |

Marina-wide rather than per-pedestal **on purpose**: it describes whether an ERP exists at this
site, which is a property of the deployment. A marina running both at once would mean two
billing authorities for neighbouring berths — not a state anyone should reach by accident.

In MODE 2 a shared machine key cannot express "this customer, this session", and in that mode
the distinction is the difference between a financial record and a suggestion.

---

## 6. Authentication is not authorisation

> **Authentication answers "who is this". It never answers "may this caller touch this
> record".**

Until v3.43 the NFC endpoints checked only that the `X-API-Key` was valid, then acted on
whatever record id or `user_id` the request named. Two audiences share those routes — the ERP
server-to-server, and the mobile app — so a valid key proved nothing about entitlement to a
particular session.

Object-level checks now sit on every record-naming route. Two deliberate details:

- **404, not 403, for someone else's session.** A distinct "forbidden" confirms the record
  exists, which is all an enumeration of sequential ids needs.
- **Ownership is checked before the already-ended check**, or a 409 tells a stranger the
  session exists and what state it is in.

### Installation acts are admin-only

Writing, re-assigning or deleting an NFC tag, and switching a cabinet's provisioning mode, are
**installation acts**: after one, a customer's tap energises a different socket. They are
`require_admin`. Until v3.43 the docstring said `require_admin` while the code used
`require_control` — three places read as admin-only while behaving otherwise, which is how it
stayed invisible. Reads stay open to any operator: answering "why did my tap not work?" is
operations, not configuration.

Smart mode is likewise admin-only. The marina must not be able to disable NUC control.

> **Enforcement is in the backend, never by hiding a button.** A hidden control that a known
> URL can still reach is not access control.

Every NFC mapping is attributable: `provisioned_by` **raises** rather than defaulting to
`"(unknown)"`, and `removed_at` / `removed_by` close the trail on the one destructive act in a
tag's life.

---

## 7. Liveness, and why a retained message can never prove it

> **A predicate a retained replay can satisfy is not a liveness check.**

An MQTT broker replays the last **retained** message on a topic to *every* new subscriber. So
after a backend restart, a cabinet that has been dead for three weeks delivers a perfectly
healthy-looking `opta/status` — and anything that treats "I received a status message" as "the
cabinet is alive" marks it up.

This resurrected dead cabinets in v3.40. Consequences now baked in:

- **Liveness comes from in-memory heartbeat tracking**, not from the database and not from the
  arrival of a retained message.
- A stored `last_heartbeat` and `opta_connected=1` are **not** evidence of life. `TC-NFCE-06`
  gives a cabinet a perfectly healthy-looking DB row while the in-memory heartbeat is stale and
  requires the scan to fail anyway.
- To prove a cabinet is really offline, consult `$SYS/broker/clients/connected`.
- The same reasoning applies to a **last will**: MQTT delivers a live LWT with `RETAIN=0`, so
  an `UNAVAILABLE` message never counts as proof of life.
- And to **stored valve state** (§4), which is why it expires at 60 s.

### The cabinet also stops talking on its own

A signed `int32` `millis()` rollover takes the cabinet silent at **24.85 days** of uptime
(confirmed 2026-09-20, firmware 3.0.0). **It does not self-recover** — it needs a power cycle.
`ts` in every payload is that same uptime counter, not a wall clock, which is a second reason
a replay cannot be recognised from the payload alone.

---

## 8. Smart mode is the master gate

**OFF** = monitor and alarms only. No shutdown, no session adoption, no auto-activation;
controls answer 409 and are greyed. **ON** = full control.

`/api/nfc/scan` checks **liveness first, then smart mode**. Both were previously unchecked, and
the result was the most user-visible defect in the access-control audit: a customer was told
*"pending — please plug in your charger"* when the NUC could not act. They plug in, wait,
nothing happens, and blame the system rather than retrying. This cabinet was silent for 19 days
in September.

---

## 9. Where things live

| | |
|---|---|
| **`backend/pedestal.db`** | IoT data: pedestals, sessions, sensor_readings, socket_configs, valve_configs, nfc_tags, energy_intervals, external_api_config |
| **`backend/data/users.db`** | auth + commercial: users, customers, billing_config, invoices, chat_messages, contracts, service_orders |
| Migrations | `_migrate_schema()` in `database.py` — additive, idempotent, runs on every startup |
| Topic handlers | `backend/app/services/mqtt_handlers.py` — **source of truth** for every subscribed topic |
| MQTT ↔ asyncio | `asyncio.run_coroutine_threadsafe()`; MQTT callbacks run on paho's thread |

Sessions are a state machine: **pending → active → completed / denied**. Every transition
broadcasts over the websocket to all connected clients.

### Known limitations, stated rather than filed

- **No retention policy** except on `error_logs`. No disk-full guard.
- **Static JWT secret**, anonymous MQTT, unauthenticated camera stream.
- **OTP is brute-forceable** (no attempt limit).
- The **ERP API key is a 10-year token and must be treated as known until rotated**
  (`docs/erp_key_rotation.md` — the procedure exists; the precondition is that no shipped
  client depends on it).
- The **comm-loss watchdog misses cabinets already offline at backend restart**, and stale
  sessions from that window need manual cleanup.
- Nothing enforces that the **git hooks are installed** (`core.hooksPath` can simply be unset).
  Accepted knowingly.

---

## 10. The rules that cost us something

Full versions with incidents in **`docs/engineering_notes.md`**. Summarised here because this
document is what someone reads first:

1. A predicate a **retained replay** can satisfy is not a liveness check.
2. **Authentication** answers "who is this", never "may this caller touch this record".
3. Never pipe a failure you need to see **through something that discards it**.
4. A test that **skips** has not verified the claim.
5. **Fail on unrecognised input** rather than extracting whatever you recognise.
6. Only a **capture** is evidence of what hardware sends.
7. While a commit gate is in flight, the **working tree is frozen**.
8. **Zero and unknown** are different values, and must stay different rows.
9. A broad **`git add`** is not a shortcut, it is an unreviewed commit.
10. An **error count nobody acts on** hides the next error.
11. A claim the **owner approved is not thereby true** — and is harder to dislodge.

---

## 11. Dormant, not removed

Listed so nobody revives one believing it is current.

| | |
|---|---|
| **QR codes** | **Dormant from 2026-09-30.** NFC is the supported provisioning and customer-entry path. The `/api/mobile/qr/*` router, the landing screen and `test_mobile_qr_claim.py` remain in the tree; the suite is skipped in full with the reason `"QR is not a supported path, decision of 2026-09-30"`. Not maintained, not extended, no UI v2 surface. The v3.43 six-outlet parity work on it is finished and stays. |
| **`marina/cabinet/*` handlers** | Aspirational (§0). Kept, not extended. |
| **`pedestal/*` topics** | Legacy. Manual test tool only. |
| **The simulator** | Deleted 2026-03-15 (`be0df4f`). Scheduled for rewrite against today's contract before UI v2 implementation. |
