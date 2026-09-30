# What the foundation work changed that the UI v2 spec must reflect

A running list, kept as the work happens rather than reconstructed while writing the spec. Each
entry is a fact the spec has to start from — several of them contradict what the UI v2 audit
assumed, because the audit was written before these were known.

**Status:** live. Updated as each foundation item lands.

---

## 1. Consumption figures come from the meter register, not from a computed value

**Landed (v3.43).** A session's electricity and water figures are now `end - start` of the
meter's own cumulative register, forwarded rather than derived. The previous figure integrated
`powerKw` over time — a field a real capture shows is not trustworthy (Q2 reported 0.181 kW for
six minutes while its register never moved).

**For the spec:**
- The L1 row's consumption figure is a meter reading. Do not present it as live-computed.
- `energy_kwh` / `water_liters` can be **`None`** — see item 3. Every UI that renders them must
  handle absence, not default to 0.
- Both register endpoints are stored (`meter_energy_start_kwh` / `_end_kwh`, and the litre
  pair), so a disputed charge can show what the meter read at each end. Berth detail is the
  natural place to expose that if a dispute view is ever wanted.

## 2. `consumption_source` is part of the contract

**Landed (v3.43).** Every session says how its figure was derived:

| value | meaning |
|---|---|
| `register` | the meter's own arithmetic. Normal. |
| `integrated_legacy` | an estimate from the old power-over-time method. **Closed-ended** — only sessions that were already running when v3.43 deployed; an assertion refuses it for anything started later. |
| `unknown` | not derivable. Never `0.0`. |

**For the spec:** a figure shown without its provenance is how the old workaround survived three
months unnoticed. Where the UI shows a consumption number that is **not** `register`, it must
say so in plain words — "estimated" for the legacy case, "not measured" for unknown. This is a
CORE field, consumed by the web UI, the mobile app and ERP alike.

## 3. Zero and unknown are different, everywhere

**Landed (v3.43).** A register that did not move is a **measured zero** and gets a ledger row. A
register that could not be read produces **no row** and marks the session `unknown`. One
unreadable interval makes the whole session's figure unknown, deliberately.

**For the spec:** this is the same distinction as the audit's Rule 2 `UNKNOWN` state, and it now
has a data-level counterpart. "0.0 kWh" and "we do not know" must never render identically. The
status reduction's UNKNOWN state and a `consumption_source` of `unknown` are related but not the
same thing — a berth can be OK while one of its sessions is unmeasurable.

## 4. The ledger is the financial record, and agrees with its own session totals

**Landed (v3.43).** Each `energy_intervals` row is a register delta over its window, so the sum
of a session's rows equals its reported figure by construction (`TC-EIV-10`).

**For the spec:** "what does this customer owe" is answered from the ledger. Any consumption
history or analytics view should aggregate interval rows, not session fields — the session field
is a summary of the ledger, not a second source.

## 5. Six NFC tags per cabinet, not four

**Landed (v3.43).** A cabinet with 4 sockets and 2 water outlets has **six** tags: one per
socket, one per water outlet. Water works exactly like electricity — the customer scans the tag
on the outlet they are about to use.

What was there before, and what each cost:

| Was | Consequence |
|---|---|
| `_VALID_SOCKETS = {Q1..Q4}` on provision, bulk and delete | the two water tags were **unprovisionable** — 400 at the door |
| `/scan` hardcoded `session_type="electricity"` | a water scan would have opened an electricity session on socket N |
| `build_session_payload` assumed electricity throughout | a water session was reported to ERP as outlet `"Q1"` with socket 1's cumulative **electricity** register as its `energy_kwh`, priced at the kWh tariff |
| mobile `/^Q?(\d)$/` returned null for `V1` | and the websocket adoption check treats null as "matches anything", so the app would have adopted whatever electricity session appeared next under that user |

The last two were unreachable only because water tags could not be provisioned. Enabling the
model is what made them reachable, which is why they are fixed in the same change.

**`outlet_type` is a stored dimension, not a derived one.** Both inbound name vocabularies
accept bare digits, so `"1"` cannot distinguish socket 1 from valve 1. A mismatch (`V1`
declared a socket) is **refused**, not corrected — correcting it hides which half was wrong.

**The numeric collision is load-bearing.** A water session on V1 and an electricity session on
Q1 are both `socket_id=1`, separated only by `Session.type`. Everything that looks up a session
by outlet must filter on the type, and the mobile adoption check now matches on it too.

**For the spec:**
- **Attribution is by scanned tag, never by berth.** The dashboard is organised by berth for
  MONITORING; billing has never followed that axis. Conflating them is a mistake already made
  and corrected once in this project.
- A shared valve is therefore a **scheduling** constraint, not an attribution problem — and the
  "(shared with berth N)" label is a monitoring clarification, not a billing caveat.
- `GET /api/nfc/outlets/{cabinet}` is the outlet list. It carries `reported: false` when the
  cabinet has never published its hardware config and the server fell back to the canonical
  six. **The UI must surface that**, because "never heard from this cabinet" and "this cabinet
  has no water outlets" are different situations that six identical rows cannot tell apart.
- **Valve state exists, and now persists — but it is narrower than a socket's.**
  *Corrected 2026-09-30: an earlier version of this note said the firmware publishes no valve
  state. It does.* `opta/water/V{n}/status` carries `state` and `hw_status`; the handler
  broadcast them over the websocket and stored nothing, so anything not listening at that
  instant fell back to `socket_states` — which is keyed by outlet number alone and therefore
  answered with the **electricity** socket of the same number ("cable detected" on a tap).
  v3.43 persists both on `valve_configs` and reports **`unknown`** when the stored value is
  missing or older than 60 s.

  What a valve genuinely lacks is narrower: **no `pending`** — that state means "physically
  connected, awaiting activation" and comes from plug-in detection, which has no valve
  analogue — and **no observed fault vocabulary**, so no fault check exists for one.

  **For the spec:** a water row has four states (`idle` / `active` / `unknown` / offline), not
  the socket's five, and `unknown` must render as visibly distinct from `idle` — the same rule
  as item 3.
- The session payload now carries `session_type`, and exactly one of `energy_kwh` /
  `water_liters` — the other is **`None`, not `0.0`**. Same rule as item 3.

## 5a. The QR path is still electricity-only, and that is now a question

**Unchanged, deliberately.** `routers/mobile.py` keeps its own `_VALID_SOCKETS = {Q1..Q4}`, with
the comment "water valves are out of scope for mobile monitoring per v3.6 spec". That was a
decision, not an oversight — but it was taken before the six-tag model, and it means **a water
outlet can carry an NFC tag but cannot carry a printed QR code.**

**For the spec:** a numbered question. In QR mode a cabinet has four reachable outlets and in
NFC mode six, which is a difference staff and customers both see.

## 6. **DECIDED** — UI v2 is written against `opta/*`

**Settled 2026-09-30.** A full capture from MAR_KRK_ORM_01 (firmware 3.1.0) contains only
`opta/...` topics: `opta/status`, `opta/config/hardware`, `opta/sockets/Q1..Q4/status`,
`opta/water/V1..V2/status`, `opta/meters/Q1..Q4/telemetry`, `opta/breakers/Q1..Q4/status`.

**`marina/cabinet/*` is aspirational.** Nothing bridges the prefixes, nothing publishes those
inbound topics, and **every `MARINA_*` handler fires only from tests** — a whole family of
handlers tested against nothing real. The comment above those regexes said "(real hardware)" and
said the opposite of the truth.

**For the spec:**
- UI v2 targets `opta/*`. New code must not assume `marina/cabinet/*`.
- The existing `MARINA_*` handlers stay for now, but are **not to be extended**. If firmware
  ever moves to that prefix it will be a deliberate migration with a capture to prove it, not a
  drift discovered later.
- **The dead command publishes are removed** (v3.43): six in `controls.py`, one in
  `mqtt_handlers.py`, all sending to `marina/cabinet/.../cmd/...` while the Opta listens on
  `opta/cmd/*`. No test asserted them, which is its own signal. A publish nobody receives is
  worse than no publish, because it reads as working.

## 7. **DECIDED** — three-phase display, ratings, and shape tolerance

**Settled 2026-09-30.**

- **Per-phase values do NOT appear at L1.** One number per row, and "which phase" is not a
  question marina staff ask.
- **Berth detail shows per-phase for a three-phase socket** — that is where someone
  investigating a problem goes. Labelled **"Phase 1 / 2 / 3"**, not L1/L2/L3.
- **The socket's rating belongs on berth detail**, not on the row: "this berth is on a 16 A
  socket and the customer wants 32 A" is an answer staff need, and it comes from
  `opta/config/hardware` rather than a constant (Q1/Q2 are 32 A, Q3/Q4 are 16 A).
- **The UI must render what the payload contains, not what it expects.** Q1 sends
  `currentAmpsL1..L3` / `powerKwTotal`; Q2–Q4 send `currentAmps` / `powerKw`. A component that
  assumes one shape and fails on the other is a real defect, not a styling detail.

## 7. The cabinet enumerates itself, including per-socket differences

**Landed as a finding; not yet used.** `opta/config/hardware` reports:

- **Q1** — ABB D13 15-M 65, **3-phase**, 32 A, modbus 1
- **Q2** — ABB D11 15-M 40, 1-phase, 32 A, modbus 2
- **Q3, Q4** — ABB D11 15-M 40, 1-phase, **16 A**, modbus 3 and 4
- **V1, V2** — both rated 20 L/min

**For the spec:**
- Provisioning should read this rather than assume four identical sockets.
- **The telemetry payload shape differs by socket.** Three-phase Q1 sends
  `currentAmpsL1..L3` / `powerKwTotal`; Q2–Q4 send `currentAmps` / `powerKw`. The backend parser
  handles both; **the UI must too**, and a per-phase display on one socket and not the others is
  a real difference staff will see. Decide deliberately whether L1/L2/L3 appear at L1, at berth
  detail, or only in the admin profile.
- Ratings differ (32 A vs 16 A), so any load display or limit must come from the cabinet rather
  than a constant.

## 8. Outlet names are validated, not guessed

**Landed (v3.43).** `_socket_name_to_id` / `_water_name_to_id` raise on anything unrecognised
instead of extracting digits. Real firmware uses `Q1`..`Q4` and `V1`/`V2` exclusively; bare
digits and `E`-names exist only in the aspirational `marina/*` family.

**For the spec:** any UI that constructs an outlet identifier must use the real spellings. A
label like "1" is ambiguous between socket 1 and valve 1 by nature, which is why tags need a
type dimension rather than name inference.

## 9. The simulator does not exist

**Landed as a finding.** Deleted in March 2026 (`be0df4f`). It is scheduled to be rewritten
**after the UI v2 spec is approved and before UI implementation**, so every configuration the
wizard must handle can be rendered and looked at without a trip to Krk.

**For the spec:** the spec can be written without it, but the implementation plan should assume
it exists by then — particularly for the 4-berth shared-valve case.

## 10. Smart mode is admin-only, and the marina cannot reach it

**Landed (v3.43).** `POST /api/pedestals/{cab}/smartmode` is `require_admin`. The audit found it
was `require_control`, so marina staff could disable NUC control.

**For the spec:** Rule 6's "if smart mode is off, render one sentence and no controls" stands,
and the control panel wizard must not offer smart mode at all. The backend enforces it
regardless of what the UI renders.

---

## Still open, needed before or during the spec

1. **`opta/*` vs `marina/cabinet/*`** — item 6. Decision, not research.
2. **How many valves are physically fitted at Krk, and how the pipework runs** — outstanding
   from the field. Designing for the shared case meanwhile, since it is the one that constrains.
3. **A loaded capture** — to quantify the `powerKw` divergence at real load. Nothing waits on
   it; it becomes the acceptance test for the register change.
4. **Modal-inside-modal and sunlight readability** — both recorded as "requires a device
   walkthrough". Not to be guessed either way.
