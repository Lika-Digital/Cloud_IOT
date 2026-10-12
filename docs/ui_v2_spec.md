# UI v2 — Marina Monitoring & Control profile: specification

**Date:** 2026-10-01 · **Version:** 2 (supersedes the 2026-09-28 draft) · **Status:** approved
2026-10-01; **PARTLY BUILT** since (`4eb381e` onwards). *Corrected 2026-10-12: this line said
"No UI code written", which stopped being true on 2026-10-03.* Where this text and the code
differ, the status review of 2026-10-12 lists each difference; each awaits the owner's decision
on which side is right, and until then this document is NOT updated to match the code.
**§0 records the owner's decisions of 2026-10-12 on where this text and the code differed,
and the status of every main item. §13 is the list of checks that can be run only on the
cabinet. §14 is the security model; §15 the consequences of D6.1 for the UI.**

**The ERP contract is not in this document.** It lives in ONE place,
`docs/erp_session_payload_contract.md`, and is only referenced here — two copies of a contract
drift apart.

**Reads with:** `docs/architecture.md` (how the system works), `docs/ui_v2_audit.md` (what
exists today, with evidence), `docs/ui_v2_spec_inputs.md` (the foundation deltas, now folded
into §4 here).

**QR is absent from this document by decision of 2026-09-30.** No screens, no wizard steps, no
CORE fields. NFC is the only provisioning and customer-entry path.

Everything below is **DECIDED** unless it is in §1. Each decision states what changes if it is
overruled, so a correction costs one line from you rather than a conversation.

---


# 0. Decisions of 2026-10-12, and status

## 0.1 Spec against code — the owner decided which side is right

| # | This spec said | The code does | Right | Where updated |
|---|---|---|---|---|
| 1 | Water per berth (`berths[].water`) | Water at pedestal level (`pedestals[].water_outlets`) | **CODE.** Water is not piped to berths | §2.1, §5.1 |
| 2 | Watts | Amps | **CODE.** Amps are measured; `powerKw` was up to 100× too high | §2.1, §9 |
| 3 | `valve_id` in `berth_assignments` | No `valve_id` | **CODE.** A berth → valve relationship does not exist | §6 |
| 4 | Light and guard per berth, `shared_with_berths` | On a pedestal strip | **CODE.** One physical device serves all berths | §2.1, §5.1 |
| 5 | Row controls, L3 history, nav of 4, `<PhaseBlock>`, wizard step 3, TC-UIR-01, `outlet_silent` | Missing | **SPEC.** To be built — block 4 | unchanged |
| 6 | — | `/marina/water` exists | **CODE.** It enters the spec | §5 |
| 7 | No marina component over 250 lines; profile under 1 200 | 377 / 302 lines; 1 890 total | **SPEC.** The limits stay. Files are split inside block 4, because they are being rewritten anyway — no separate refactor | §9 |
| 8 | Live values by websocket | 15 s polling | **WS — but only AFTER part B** (role filtering, §14). The broadcast carries `customer_id`; switching `/marina` to WS before filtering would put customer identity on the page. Polling stays until then | §7 |
| 9 | New `energy_intervals` rows carry `berth_id` | Only `berth_ref` | **SPEC.** Built — see the measured reason in §6 | §6 |

## 0.2 Status of the main items (2026-10-12)

BUILT+PROVEN = code + a test that can fail, green. BUILT-UNPROVEN = code, nothing proves it.
Evidence is a test, a commit or a path, never a claim.

| Item | State | Evidence |
|---|---|---|
| CORE `/api/marina/berths`, berth detail, status sentences and precedence | BUILT+PROVEN | `test_marina_core.py` TC-MC-01..14, `test_marina_core_shape.py` |
| `outlet_silent` (rank 2.5) | PARTIAL | `routers/marina.py:247` hard-codes `False`; never emitted |
| Guard on `/marina` | PARTIAL | `services/guard_state` does not exist (`marina.py:208`), so it always reads unavailable |
| Row controls (power, water, light) | NOT BUILT | no page passes `onAction`; TC-UIR-03 therefore passes vacuously |
| TC-UIR-01 (no raw colour classes) | NOT BUILT | claimed only in a comment, `Status.tsx:12`; 32 raw colour lines exist |
| L3 history, `<PhaseBlock>`, nav of 4, Card 5 (water toggle) | NOT BUILT | no history route in `App.tsx`; `Layout.tsx:40-57` has 8 items |
| Setup wizard | PARTIAL, UNPROVEN | `MarinaSetup.tsx` (`4eb381e`); step 3 missing; route not `adminOnly`; no UI test |
| §9 size limits | FAILS | 377 / 302 lines; 1 890 total |
| `match_ok_bit` "never analysed" | NOT BUILT | `berth_models.py:42 default=0` → `vessel_matches: false` for unknown |
| D2 paired redaction test (HTTP) | NOT BUILT | `test_history_endpoint_readable_by_monitor` asserts only `!= 403` |

Status of D14–D19 is in §11.

# 1. BLOCKING — two decisions, both awaiting facts only you have

**Resolved 2026-10-01:** the original BLOCK-1 (water to the ERP) and BLOCK-2 (unmeasurable
invoices) are answered and recorded in §1.3 and §1.4. The two below are renumbered and
neither blocks the build — they block the first wizard run, and one field in CORE.

### BLOCK-1 · Which berths share which valve at Krk, and how many berths per pedestal

You have decided the model: **1–4 berths configurable, a berth maps to exactly one socket, a
valve may be shared.** I am building for that and this does not block the spec.

What I need is **the actual Krk installation** — how many berths per pedestal, and which berths
the two valves serve — because it is the first wizard run and the first thing the simulator must
reproduce. If it turns out one berth per pedestal, the shared-valve label never renders and the
L1 row loses a line of text.

**If I am wrong about the shape:** I built for the shared case because it is the one that
constrains; the single-berth case is a strict subset and renders correctly with no change.

### BLOCK-2 · May marina staff see the customer's name on the dashboard?

A marina `monitor` can already read `/api/pedestals/{id}/usage/history`, which returns
`customer_name` and `nfc_user_id` (`usage_report_service.py:128-140`) — so the answer today is
effectively yes, but by accident rather than decision, and that endpoint's own docstring claims
admin-only while the code is `require_any_role`.

The L1 row **does not need a name** to work. "Berth 3 needs attention" is complete.

**DECIDED (overrule me if wrong): no customer name anywhere in the marina profile.** Berth
number and vessel photo identify the boat; staff standing on the pontoon can see it. A name on
a wall-mounted dashboard is a privacy exposure with no operational payoff.

**If I am wrong:** add `customer_name` to CORE and one line on the berth detail header. Trivial
either way — but it must be a decision, not a leak, and the `usage/history` docstring gets
corrected to match whichever you choose.

---

## 1.3 DECIDED (by you, 2026-10-01) — water reporting is a toggle on the API configuration page

Both myMarina and MarinaMaster can receive water sessions, so the guard removal stands and
water is reported by default. **The on/off control is a UI setting, not an `.env` flag.**

**WHY it belongs there rather than in config:** whoever integrates a site is sitting in front
of the API configuration screen when they discover whether that ERP wants water events. An
`.env` setting means a shell session, a service restart, and a decision recorded nowhere a
later integrator will look. The screen already holds exactly this class of per-deployment
choice — which endpoints are allowed, which events are pushed.

**Spec — a fifth card on `/api-gateway`:**

```
┌──────────────────────────────────────────────────────────┐
│  Card 5 — What this ERP receives                         │
│                                                          │
│  Electricity sessions      [●━━] on    (always on)       │
│  Water sessions            [●━━] on                      │
│                                                          │
│  Water outlets report litres drawn against the tag the    │
│  customer scanned, exactly as sockets report kWh. Turn    │
│  this off only if this ERP cannot accept water sessions.  │
│                                                          │
│  Last water session sent:  2026-10-01 14:22               │
└──────────────────────────────────────────────────────────┘
```

| | |
|---|---|
| **Storage** | `external_api_config.report_water_sessions INTEGER DEFAULT 1` — single-row table, ID always 1, same as every other setting on that screen. Default **1**, since both ERPs support it. |
| **Endpoint** | the existing `PUT /api/admin/ext-api/config`. No new route. |
| **Enforced at** | the three `erp_webhook` call sites in `mqtt_handlers.py`, via one predicate in `erp_webhook.py` so there is one place to read rather than three to keep in step. |
| **Auth** | `require_api_config`, matching the rest of the page. |

**One correction to the instruction, stated rather than silently applied:** you said "admin
only, like everything else on that screen". **The screen is not admin-only today** — it is
`require_api_config`, which admits `admin` **and** `monitor_control_api`
(`auth/dependencies.py:18-22`). I have specified the toggle to match the page as it is, because
one control on a screen with a different rule from its neighbours is how the next person
misreads the whole screen. **If you meant the page should be admin-only**, say so and it
becomes one change to `require_api_config`'s role set — which tightens five existing
endpoints, not just this toggle, and is therefore your call rather than a detail of this card.

**Electricity is shown but not switchable.** Turning off electricity reporting would silently
stop the thing the integration exists for. If a site genuinely needs that, it has no ERP and
the webhook URL is simply unset.

**DECIDED — the toggle gates the webhook, not the recording.** Water sessions, registers and
ledger rows are written regardless. Switching it off stops *reporting*, never *measuring*: a
site that flips it on six months later must find the history intact, and consumption is also
how the marina answers "what did berth 3 use".
**IF I AM WRONG:** nothing else in the system would be simplified by not recording, so I would
argue this one.

**TC-SIX-16b amended:** the structural test that forbids a session-type guard on an ERP webhook
call now permits exactly this named predicate and nothing else, so the toggle cannot be
mistaken for the defect it replaces — and the defect cannot come back wearing its clothes.

## 1.4 CLOSED (by you, 2026-10-01) — we do not issue invoices

BLOCK-2 asked how to invoice a session whose consumption could not be measured. **The question
does not arise: the pedestal reports consumption and the ERP bills.** `invoice_service` is not
on a live path.

**Action taken, and deliberately no more than this:** the `or 0.0` lines carry a comment saying
they are dead code on an unused path rather than a tolerated defect, so the next person to read
them starts from the right place instead of re-deriving the question. If MODE 2 ever makes us
the biller, that comment is where the work begins.

---

# 2. The data contract — CORE and EXTENDED

> **Status and labels are computed server-side, once, in CORE, and consumed by web, mobile and
> ERP alike.** The frontend never computes status. There is nothing to drift.

Two payloads, two audiences, one source.

## 2.1 CORE — `GET /api/marina/berths`

Auth: `require_any_role`. The whole marina profile's L1 screen comes from this one call plus
websocket deltas.

```jsonc
// Updated 2026-10-12 to the shape the code returns (§0.1 decisions 1, 2, 4).
{
  "pedestals": [{
    "pedestal_id": 3,
    "cabinet_id": "MAR_KRK_ORM_01",
    "dock": "A",
    "reachable": true,              // in-memory heartbeat within 60 s — NOT a DB column
    "smart_mode": true,
    "berths": [{
      "berth_id": 12,
      "berth_number": 3,

      // ── the two-state reduction, plus UNKNOWN ──────────────────────────────
      "status": "ok" | "attention" | "unknown",
      "status_code": "water_leak",        // stable key, for tests and logs
      "status_sentence": "Water leak detected",   // the ONLY marina-facing string
      "status_rank": 3,                   // §3 precedence; for sorting, never displayed

      "occupied": true,
      "occupied_known": true,
      "vessel_matches": true,             // null when matching is not configured
      "vessel_match_configured": true,

      // ── power belongs to the berth: one socket per berth ───────────────────
      "power": {
        "outlet": "Q3",                   // real spelling, always
        "on": true,
        "state": "active",                // idle|pending|active|fault|unknown
        "amps": 5.4,                      // AMPS, measured — not watts (decision 2)
        "unit": "A",
        "available": true,                // false => render a sentence, no control
        "unavailable_reason": null        // e.g. "standalone"
      },
      "alarm_count": 0
    }],

    // ── water, light and guard belong to the PEDESTAL (decisions 1 and 4) ─────
    "water_outlets": [{
      "outlet": "V1",
      "on": false,
      "state": "idle",                    // idle|active|unknown — NO "pending" (§4.6)
      "litres_per_min": null,             // live, over the websocket
      "unit": "L/min",
      "rated_liters_per_min": 12,
      "in_use": false,
      "available": true,
      "unavailable_reason": null
    }],
    "light":  { "on": true, "scope": "pedestal", "available": true, "unavailable_reason": null },
    "guard":  { "state": "on" | "off" | "paused" | "unavailable",
                "sentence": "Guard paused — too dark to see",
                "scope": "pedestal" },
    "alarm_count": 0
  }]
}
```

**DECIDED — `power` and `water` are objects, not flat fields.**
**WHY:** `available`, `state` and `unavailable_reason` all have to travel with the facility
they describe. Flattening to `power_on` / `water_on` is how a row ends up rendering a control
the facility does not have. *(2026-10-12: water, light and guard moved to the pedestal —
`shared_with_berths` is gone with them; §0.1.)*
**IF I AM WRONG:** flattening later is a mechanical change in one serialiser.

**DECIDED — `reachable` is computed from the in-memory heartbeat, never from a stored column.**
**WHY:** `architecture.md §7`. A cabinet dead for three weeks delivers a healthy-looking
retained `opta/status` to every new subscriber, and `PedestalConfig.opta_connected` will say
`1`. `TC-NFCE-06` already pins this for the NFC path; the dashboard must not reintroduce it.
**IF I AM WRONG:** there is no version of this I would implement differently. A green row
meaning "we cannot see berth 3" is worse than no dashboard.

**DECIDED — `status_code` ships alongside `status_sentence`.**
**WHY:** tests, logs and the deferred mobile client need a stable key; humans need the sentence.
Asserting on display text makes every wording change a test failure, which is how wording stops
being improved.
**IF I AM WRONG:** drop the field; nothing renders it.

## 2.2 EXTENDED — admin only, unchanged in shape

Everything the marina profile deliberately excludes, served by the **existing** admin endpoints.
No new work.

| Lives in EXTENDED | Why not CORE |
|---|---|
| Temperature, moisture | cabinet health, not berth state. Appears in CORE only as a `status_sentence` when it crosses an alarm threshold. |
| Breaker state and history | diagnosis, not monitoring |
| Per-phase currents (Phase 1/2/3), `rated_amps`, `meter_type`, modbus address | from `opta/config/hardware`; berth detail shows per-phase and rating (§5.3), the admin profile keeps the rest |
| CPU, disk, guard thresholds, confidence, detection list | guard engineering surface |
| `consumption_source`, both meter register endpoints | dispute evidence; surfaced on berth detail as one plain line, not as four numbers |
| NFC tag ids and provisioning | installation |
| Smart mode | admin only, backend-enforced |
| `data_mode: synthetic` | **DECIDED: not in the marina profile.** A marina has no use for it and it is alarming if misread. |

---

# 3. The nine status sentences, with precedence

**Highest rank wins**, so the sentence shown is always the most serious thing true about that
berth. One table, server-side, in one module. **A condition with no entry here cannot be
rendered** — it becomes `unknown` / "Something needs checking", which is honest and forces the
entry to be added rather than letting a blank through.

| Rank | `status_code` | `status` | `status_sentence` | Source |
|---|---|---|---|---|
| 1 | `no_contact` | unknown | **"No contact with this pedestal"** | in-memory heartbeat older than 60 s |
| 2 | `standalone` | unknown | **"This pedestal is running on its own"** | `smart_mode == false` |
| 3 | `water_leak` | attention | **"Water leak detected"** | moisture alarm > 90 % |
| 4 | `too_hot` | attention | **"Pedestal too hot"** | temperature alarm > 50 °C |
| 5 | `auto_off_overload` | attention | **"Power switched off automatically — too much load"** | `socket_configs.auto_stop_pending_ack` |
| 6 | `breaker_tripped` | attention | **"Power tripped — needs resetting"** | `opta/breakers/Q{n}/status` |
| 7 | `guard_unreviewed` | attention | **"Someone was seen — needs checking"** | guard alarm not yet marked correct/false |
| 8 | `vessel_mismatch` | attention | **"Vessel does not match the photo"** | occupancy match, only where configured |
| 9 | `ok` | ok | *(no sentence)* | nothing above is true |

**Two additions to the nine, both forced by the foundation work:**

| Rank | `status_code` | `status` | `status_sentence` | Why it must exist |
|---|---|---|---|---|
| 2.5 | `outlet_silent` | unknown | **"This outlet has not reported recently"** | A valve's stored state expires at 60 s (§4.6). The cabinet can be reachable while one outlet is stale. Without this the row would show `idle` for a valve nobody has heard from — the precise defect §4.6 fixed one layer down. |
| 7.5 | `measurement_missing` | attention | **"Consumption could not be measured — needs review"** | `consumption_source == "unknown"` on a session at this berth. **Re-anchored 2026-10-01:** its original justification was the invoicing question, which is closed (§1.4) — but it stands on its own and is *more* necessary without an invoice step. We report the figure to the ERP and the ERP bills it; an `unknown` leaves the ERP with nothing to charge and nobody on our side aware. This sentence is the only thing that tells a human it happened. |

**DECIDED — rank 1 and 2 are `unknown`, not `attention`.**
**WHY:** "needs attention" means *go and do something about this berth*. A pedestal with no
contact or in standalone mode needs something done about the **pedestal**, and the berth's
actual state is genuinely not known. Marking it `attention` sends staff to the wrong place and
fills the attention filter with rows that have nothing wrong at the berth.
**IF I AM WRONG:** change two rows in the table. Nothing else moves.

**DECIDED — these are the only marina-facing strings for these conditions.**
**WHY:** the audit found Rule 4 compliance was accidental. A string table makes it structural,
and `TC-UIR-02` asserts that every rendered condition has an entry.
**IF I AM WRONG:** reword freely — the `status_code` keys are what tests use, precisely so
wording stays editable.

### Guard state mapping — fixed here, written once

| Backend | Marina sees |
|---|---|
| `ARMED`, `ALARM`, `RECORDING` | **Guard on** |
| `ARMING` | **Guard on** (brief "starting…") |
| `OFF` | **Guard off** |
| `SUSPENDED_CPU`, `NO_DISK`, stalled ring | **Guard paused** + plain reason |
| `limited_visibility` while armed | **Guard paused — too dark to see** |
| `UNAVAILABLE` | **Guard unavailable** |

**`UNAVAILABLE` must never render as "Guard off".** Off is a decision someone made; unavailable
is a fault. The entire liveness design — LWT plus heartbeat plus in-memory `worker_seen_at` —
exists to keep those apart, and collapsing them in the UI throws that away at the last step.

---

# 4. Foundation deltas folded in

What changed underneath since the audit was written. Each one constrains a screen.

### 4.1 Consumption figures are meter readings, forwarded not computed
A session's figure is `end − start` of the meter's own cumulative register. **Do not present it
as live-computed.** `powerKw` survives for live display only, and the capture shows why: Q2
reported 0.181 kW for six minutes while its register never moved.

### 4.2 `energy_kwh` and `water_liters` can be `None`
Every widget that renders them must handle absence. **`None` is not `0.0`.**

### 4.3 `consumption_source` is part of the contract
`register` / `integrated_legacy` (closed-ended, assertion-enforced) / `unknown`. Where berth
detail shows a number that is not `register`, it says so in plain words — "estimated" or "not
measured". A figure shown without its provenance is how the old workaround survived three
months.

### 4.4 The ledger agrees with its own session totals
Interval rows are register deltas, so their sum equals the session figure by construction
(`TC-EIV-10`). **Any history or analytics view aggregates interval rows**, never session fields.

### 4.5 Six outlets, real spellings, attribution by scanned tag
`Q1`–`Q4` and `V1`/`V2`. Never bare digits — `"1"` is ambiguous between socket 1 and valve 1.
**The dashboard is organised by berth for monitoring; billing follows the scanned tag.** A
shared valve is a scheduling constraint, not an attribution problem, so "(also berth 4)" is a
monitoring clarification and never a billing caveat.

### 4.6 Valve state exists, and has four states not five
`opta/water/V{n}/status` carries `state` and `hw_status`; v3.43 persists them and returns
`unknown` past 60 s. **There is no `pending`** — that means "physically connected, awaiting
activation" and comes from plug-in detection, which has no valve analogue. **There is no valve
fault check** — `STATE_FAULT` is reported only reactively on `opta/acks`, so it cannot be
polled.

### 4.7 The cabinet is not four identical sockets
Q1 is three-phase 32 A; Q3/Q4 are 16 A. **The UI must render what the payload contains, not
what it expects**: three-phase Q1 sends `currentAmpsL1..L3` / `powerKwTotal`, Q2–Q4 send
`currentAmps` / `powerKw`. A component that assumes one shape is a defect.

### 4.8 `opta/*` only
`marina/cabinet/*` is aspirational and `pedestal/*` is a legacy test-tool prefix. No new code
assumes either.

### 4.9 Smart mode is admin-only and backend-enforced
It does not appear in the wizard, and the endpoint refuses the role regardless of what renders.

### 4.10 The simulator does not exist yet
Deleted 2026-03-15. Rewritten after this spec is approved and **before** implementation, so
every configuration the wizard must handle can be looked at without a trip to Krk.

---

# 5. Page map and wireframes

Three levels. **Back is always visible. No overlay opens another overlay.**

```
L1  /marina                     Dashboard — one row per berth
     │
     ├── L2  /marina/berth/:id   Berth detail
     ├── L2  /marina/water       Water outlets of the pedestal (added 2026-10-12, decision 6)
     │        └── L3  /marina/berth/:id/history    Consumption history
     │
     ├── L2  /marina/alarms      Alarm list
     │
     ├── L2  /marina/guard       Guard — per pedestal
     │
     └── L2  /marina/setup/:pid  Control-panel wizard (3 steps, admin)
```

## 5.1 L1 — Dashboard

```
┌────────────────────────────────────────────────────────┐
│  Marina A                      [ Needs attention (2) ]│
│                                [ All (8)             ]│
├────────────────────────────────────────────────────────┤
│  ▲  BERTH 3            Water leak detected            │
│     Occupied · photo matches                           │
│     Power   ON    1 240 W         [ Turn off ]         │
│     Water   OFF        0 L/min    [ Turn on  ]         │
│              (also berth 4)                            │
│     Light   ON                    [ Turn off ]         │
│              (also berths 1, 2, 4)                     │
│     Guard   on                                         │
│                                           2 alarms  ›  │
├────────────────────────────────────────────────────────┤
│  ?  BERTH 5            No contact with this pedestal   │
│     We cannot see this berth at the moment.            │
│                                                     ›  │
├────────────────────────────────────────────────────────┤
│  ✓  BERTH 1            —                               │
│     Empty                                              │
│     Power   OFF        0 W         [ Turn on ]         │
│     Water   —      no water outlet at this berth        │
│     Light   ON                     [ Turn off ]        │
│     Guard   on                                         │
│                                                     ›  │
└────────────────────────────────────────────────────────┘
```

**Sort: needs-attention first, then unknown, then by berth number.** The rows that need someone
are at the top of a phone screen without scrolling, which is the entire point.

**DECIDED — status is icon + word + colour, all three, always.**
**WHY:** the audit found the compliant cases were compliant by accident. One `<Status>`
component makes all three props required.
**The enforcement is a TEST, not a lint rule** (`TC-UIR-01`): a source scan asserting no raw
`text-red-*` / `text-green-*` / `bg-*-900` in `pages/marina/**`. The earlier draft said "a lint
rule", which assumed an eslint that **does not exist** — see D13. A mechanism that depends on a
stage which has never run is not a mechanism.
**IF I AM WRONG:** nothing to change — this is the brief.

**SUPERSEDED 2026-10-12 (decision 4): light and guard sit on a PEDESTAL STRIP above the berth
rows, not on each row — one physical device serves every berth. The text below is the
original decision, kept for the record.**

**DECIDED — shared light and guard stay on the row, labelled in plain words.**
**WHY:** your decision, and it is right: four berth rows on one cabinet are four views of one
switch, and four independent-looking toggles would be a quiet lie. On tap: *"This light covers
berths 1, 2, 3 and 4. Turn it off for all of them?"* One confirm, no hidden surprise. When a
cabinet serves one berth, `shared_with_berths` is empty and none of it renders.
**IF I AM WRONG:** move both to berth detail; the row loses two lines.

**SUPERSEDED IN PART 2026-10-12 (decision 1): water is not a berth facility at all — it is
listed per pedestal (`water_outlets`). The absence rule below still holds for every control.**

**DECIDED — a berth with no valve renders "no water outlet at this berth", not a disabled
control.**
**WHY:** Rule 6, applied to absence rather than to smart mode. `available: false` renders **no
control element in the DOM** — not `disabled`, not `pointer-events-none`, absent.
**IF I AM WRONG:** this is the rule; I would not change it.

**DECIDED — one figure per facility and nothing else.** Watts, or litres per minute.
Temperature, moisture, amps, phases and kWh totals do not appear at L1 at all.

**DECIDED — per-phase values do not appear at L1.** Your decision. One number per row; "which
phase" is not a question marina staff ask.

## 5.2 L1 — smart mode off

```
┌────────────────────────────────────────────────────────┐
│  ?  BERTH 3            This pedestal is running on its │
│                        own                              │
│     Power   ON    1 240 W                               │
│     Water   OFF        0 L/min                          │
│     The marina office can start and stop outlets here   │
│     once this pedestal is reconnected.                  │
│                                                     ›  │
└────────────────────────────────────────────────────────┘
```

Readings still render — they are real, they arrived over MQTT. **Controls are absent**, with one
sentence in their place. Never a greyed-out button.

## 5.3 L2 — Berth detail

```
┌────────────────────────────────────────────────────────┐
│  ‹ Back to marina            BERTH 3   ▲ Water leak    │
├────────────────────────────────────────────────────────┤
│  [ pedestal image, status-coloured ]                   │
│                                                        │
│  This berth                                            │
│    Power    socket Q3 · 16 A · single phase            │
│    Water    outlet V1 · 20 L/min · also berth 4        │
│                                                        │
│  Now                                                   │
│    Power    ON     1 240 W         [ Turn off ]        │
│    Water    OFF        0 L/min     [ Turn on  ]        │
│                                                        │
│  This month                                            │
│    Electricity   34.812 kWh      meter reading         │
│    Water          1 203.5 L      meter reading         │
│                                        [ History › ]   │
│                                                        │
│  Vessel                                                │
│    [ reference photo ]  [ camera now ]   matches ✓     │
│                                                        │
│  Alarms at this berth                      2 active ›  │
└────────────────────────────────────────────────────────┘
```

**DECIDED — the socket's rating and phase count live here, not on the row.** Your decision.
From `opta/config/hardware`, never a constant.

**DECIDED — a three-phase socket shows "Phase 1 / 2 / 3" here**, in a sub-block, and only when
the payload actually contains per-phase values. Labelled in words, never L1/L2/L3 — "L1" means
the dashboard level in this document and a phase on the hardware, and that collision is exactly
the kind of thing that ends up on a screen.

**DECIDED — "meter reading" appears next to each figure, and the wording changes with
`consumption_source`.**

| `consumption_source` | Shown |
|---|---|
| `register` | "meter reading" |
| `integrated_legacy` | "estimated — meter unavailable" |
| `unknown` | **"not measured"**, and the figure itself renders as **—**, never `0.0` |

**WHY:** §4.3. The provenance travels with the number or the number is a claim without a source.
**IF I AM WRONG:** drop the label; the figures are unaffected.

**DECIDED — guard events on berth detail are labelled as the cabinet's, not the berth's.**
**WHY:** one camera per pedestal. On a multi-berth cabinet the event list is the cabinet's. Not
saying so would attribute a stranger walking past berth 1 to berth 3.

## 5.4 L2 — Alarms

Flat list, newest first, filterable by pedestal and by berth. Plain sentences from §3 only —
never an error code. What happened, where, when, still active or not.

**Needs a backend endpoint, not just a page.** `ActiveAlarmsPanel` renders only inside
`SystemHealth`, which is `adminOnly` (`App.tsx:76-83`), so the marina cannot see a cross-berth
alarm list today.

**DECIDED — a new marina-scoped endpoint, not the admin one re-gated.**
**WHY:** re-gating leaks admin diagnostic detail into this profile by default, and the next
field added to the admin payload appears on the marina screen without anyone deciding so.
**IF I AM WRONG:** re-gating is less code; the cost arrives later.

## 5.5 L2 — Guard

Per pedestal, not per berth. Four states from the mapping in §3, event list with annotated
frame, recording, and the **correct / false alarm** control (`require_any_role`, so it is
available to whoever is actually looking).

**DECIDED — notifications stay off.** Your standing instruction: off until you have watched a
week. **There is no built-and-disabled notification path** that could be switched on by
accident — the code is absent, not flagged off.

## 5.6 Control-panel wizard — 3 steps, admin, once per pedestal

```
Step 1 of 3   Which dock does this pedestal serve?
              Dock  [ A ▾ ]
              Pedestal label  [ MAR_KRK_ORM_01 ]  (read-only, from the cabinet)

Step 2 of 3   Which berths does it serve, and which outlet each?
              ┌──────────────────────────────────────────────┐
              │ Berth    Power socket      Water outlet       │
              │ [ 3 ]    [ Q3 ▾ ]          [ V1 ▾ ]           │
              │ [ 4 ]    [ Q4 ▾ ]          [ V1 ▾ ]  shared   │
              │ [ + add a berth ]                             │
              └──────────────────────────────────────────────┘
              Q1 · 32 A · 3-phase    Q2 · 32 A    Q3 · 16 A    Q4 · 16 A
              V1 · 20 L/min          V2 · 20 L/min
              ⚠ This cabinet has not reported its outlets yet — the list
                above is the standard set.

Step 3 of 3   Per berth: vessel reference photo, and occupancy matching on/off
              Berth 3  [ upload photo ]  [x] Berth occupancy and match
              Berth 4  [ upload photo ]  [ ] Berth occupancy and match
```

**DECIDED — step 2 captures socket AND valve per berth, not just berth numbers.**
**WHY:** without it the L1 row cannot render power or water at all. The wizard is the right
place because it is the one moment someone is physically at the cabinet and can see which outlet
serves which boat.

**DECIDED — the outlet dropdowns are driven by `GET /api/nfc/outlets/{cabinet}`**, with its
`reported` flag surfaced as the warning shown above.
**WHY:** the cabinet enumerates itself, including ratings. A hardcoded four-socket list was
wrong twice over. And "never heard from this cabinet" must not render identically to "this
cabinet has no water outlets".

**DECIDED — a socket may serve only one berth; the UI enforces it at entry.** Your decision, and
the DB enforces it too (§6). A valve may be shared, and the UI labels it "shared" as soon as a
second berth picks it — so the person entering it sees the consequence while they are deciding,
not afterwards.

**DECIDED — smart mode does not appear in this wizard at all.** Backend-enforced regardless.

**DECIDED — the wizard is re-runnable and shows the current mapping pre-filled.**
**WHY:** re-pointing a berth is an installation act that will happen (a socket fails, a boat
moves). A one-shot wizard means the second change is made in the database by hand.
**IF I AM WRONG:** make it one-shot plus an edit screen; same work, two entry points.

---

# 6. `berth_assignments`

```sql
berth_assignments                   -- pedestal.db, beside sockets, valves, energy_intervals
  id            INTEGER PRIMARY KEY
  berth_id      INTEGER NOT NULL    -- Berth.id from users.db; plain int, no FK (cross-DB)
  pedestal_id   INTEGER NOT NULL REFERENCES pedestals(id)
  socket_id     INTEGER             -- 1..4, NULL if this berth has no power
  -- valve_id    REMOVED 2026-10-12 (decision 3): a berth -> valve relationship does not exist
  assigned_at   DATETIME NOT NULL
  assigned_by   TEXT NOT NULL       -- admin email; REQUIRED, never defaulted
  UNIQUE (pedestal_id, socket_id)   -- a socket serves at most one berth
  UNIQUE (berth_id)                 -- a berth has at most one assignment
```

**DECIDED — it lives in `pedestal.db`.**
**WHY:** sockets, valves and `energy_intervals` are all there, so every join the dashboard needs
stays in one database. `berth_id` crosses as a plain int, which is the compromise
`Berth.pedestal_id` already makes — no new kind of problem.

**DECIDED — `socket_id` is nullable.** *(`valve_id` removed 2026-10-12, decision 3.)*
**WHY:** a berth with power but no water is a real installation and the UI must render it rather
than refuse to.

**DECIDED — `UNIQUE (pedestal_id, socket_id)`.** *(The valve clause went with `valve_id`.)*

**DECIDED — `assigned_by` is required and raises rather than defaulting.**
**WHY:** same reasoning as `provisioned_by` on NFC tags. Re-pointing a berth changes which
customer's consumption lands where. A caller with no actor has a bug; a default hides it.

**DECIDED — `Berth.berth_number` is the authoritative identity the marina sees.**
`PedestalConfig.berth_ref` becomes a display-only installation label.
**WHY:** `Berth` is the only representation that can express four berths on one cabinet, and it
already carries the reference photo and match state the L1 row needs.

**DECIDED — `energy_intervals.berth_ref` is left exactly as it is, and no invoice is ever
re-keyed.**
**WHY:** historical billing. Rewriting it changes past invoices, which is never worth it for a
UI change. New rows additionally carry `berth_id` so future invoices join properly while old
ones keep working.
**IF I AM WRONG:** this is the one I would push back on twice.

**MEASURED 2026-10-12 — why `berth_id` is needed (decision 9).** `berth_ref` is not a berth
identifier at all. It is `pedestal_configs.berth_ref` (`models/pedestal_config.py:15`): ONE
free-text string per PEDESTAL, nullable, not unique, editable by PATCH
(`routers/pedestal_config.py:35`), copied verbatim onto every interval row at write time
(`energy_interval_service.py:71-75, 190`). All four berths of a pedestal get the same value, so
an interval has never been attributable to a berth — not a renaming risk, attribution never
existed. The stable identifier is `berths.id`, mapped per socket by `berth_assignments`
(unique per socket and per berth).

So `energy_intervals.berth_id INTEGER NULL`, filled at write time from `berth_assignments` by
`(pedestal_id, socket_id)`. **NULL means "not known"** — the row predates the column, or the
socket is not assigned to a berth — and must never be read as zero or as a berth. That goes in
the column comment and in the model. The 8675 existing rows stay NULL. The ledger writes a row
only for a session with a readable meter register, and none has run since 2026-10-10, so the
first rows carrying `berth_id` will be written at R1.

---

# 7. Component list and data flow

Every widget, its source, and what it does when the source is absent.

| Component | Reads | Source | When absent |
|---|---|---|---|
| `<MarinaDashboard>` | `pedestals[].berths[]` | `GET /api/marina/berths` + WS deltas | full-page "Cannot reach the server" |
| `<BerthRow>` | one `berths[]` entry | — | n/a |
| `<Status>` | `status`, `status_sentence` | CORE | `unknown` + "Something needs checking" |
| `<FacilityLine>` power | `power{}` | CORE; live from WS `power_reading` | `available:false` → sentence, **no control in DOM** |
| `<FacilityLine>` water | `water{}` | CORE; live from WS `water_reading` | as above |
| `<SharedNote>` | `shared_with_berths` | CORE | renders nothing when `[]` |
| `<LightToggle>` | `light{}` | CORE; `POST /api/controls/pedestal/{id}/led` | sentence, no control |
| `<GuardBadge>` | `guard{}` | CORE, mapped per §3 | **"Guard unavailable"**, never "off" |
| `<AttentionFilter>` | `status`, `status_rank` | client-side over CORE | — |
| `<BerthDetail>` | one berth + EXTENDED | `GET /api/marina/berths/{id}` | back to L1 with a sentence |
| `<OutletSpec>` | `rated_amps`, `phases`, `rated_liters_per_min` | `GET /api/nfc/outlets/{cabinet}` | "Not reported by this cabinet yet" |
| `<PhaseBlock>` | `currentAmpsL1..L3` | WS `meter_telemetry` | **absent** when the payload has no per-phase keys (§4.7) |
| `<ConsumptionFigure>` | `energy_kwh` / `water_liters` + `consumption_source` | CORE | **—** with "not measured"; never `0.0` |
| `<ConsumptionHistory>` | interval rows | `GET /api/pedestals/{id}/usage/history` | "No readings yet" |
| `<VesselMatch>` | `vessel_matches`, photos | existing occupancy endpoints | hidden unless `vessel_match_configured` |
| `<AlarmList>` | marina-scoped alarms | **new** `GET /api/marina/alarms` | "No alarms" |
| `<GuardEvents>` | guard events + review control | existing guard endpoints | "No events" |
| `<SetupWizard>` | outlets + current mapping | `GET /api/nfc/outlets/{cabinet}`, `GET/PUT /api/marina/berth-assignments` | step 2 falls back to the canonical six, with the warning |

**DECIDED — live values arrive by websocket; structure arrives by REST.**
**WHY:** the WS already carries `power_reading`, `water_reading`, `session_*` and
`socket_state_changed`. Re-fetching CORE on every telemetry tick would make the dashboard
refetch 12 times a minute per cabinet.
**IF I AM WRONG:** poll CORE on a timer; strictly worse, but one hook.

**DEPENDENCY, 2026-10-12 (decision 8) — do not skip it.** `/marina` moves to the websocket ONLY
AFTER part B (§14: the broadcast filtered by role). Today the broadcast carries `customer_id`
(e.g. `water_reading`), so switching first would put customer identity on the marina page.
Until part B is built and proven, `/marina` keeps polling CORE every 15 s
(`MarinaDashboard.tsx:66`).

**DECIDED — one new backend endpoint for the reduction, two for the rest.**
`GET /api/marina/berths`, `GET /api/marina/berths/{id}`, `GET /api/marina/alarms`, and
`GET/PUT /api/marina/berth-assignments`. Nothing else is new; everything else reuses what
exists.

---

# 8. Migration — what is removed, merged, kept

| Today | UI v2 | Why |
|---|---|---|
| `/dashboard` (pedestal grid) | **kept as the ADMIN dashboard** | engineering view; still the right one for admin |
| — | **new `/marina`** | the profile this spec is about |
| `/analytics` in nav | **demoted to L3**, reached from a berth or a figure | the audit's nav-reduction finding |
| `/history` | **merged** into berth detail → History | history without a berth is a report, not a screen |
| `/berths` (`BerthOccupancy`) | **merged** into L1 + berth detail | berths *are* the dashboard now |
| `/billing`, `/users`, `/contracts` | **kept, admin** | commercial, not marina monitoring |
| `/system-health` | **kept, admin** | plus the alarm list gets a marina-scoped sibling |
| `/api-gateway` | **kept**, plus one new card: "What this ERP receives" (§1.3) | the water-reporting toggle is a per-deployment integration choice, which is what this screen is for |
| `/settings` | **kept, admin** | configuration |
| `SocketQrGrid`, QR endpoints, QR landing | **not in UI v2. Dormant, not removed.** | decision of 2026-09-30 |
| `PedestalControlCenter` (1 468 lines, 27 `useState`) | **not reused.** Stays for admin; the marina profile does not touch it | the audit's structural risk. Reusing it would import the whole admin surface into the simple profile |

**DECIDED — the admin profile is untouched** beyond the one new marina alarm endpoint.
**WHY:** your constraint is that the NUC keeps running. Rewriting the admin dashboard alongside
a new marina profile doubles the blast radius of one deployment.

---

# 9. The simplicity acceptance test

Measured on the current tree (2026-10-01), so "simpler" is a number rather than an opinion.

All counts below were read from the tree, not estimated. Two figures I first wrote from memory
were wrong and are corrected here — the nav count (I said 9; a marina `monitor` sees 7, because
three items are admin-gated) and the per-card figure count (I said 11; the card itself renders
5 numbers — the 4x2 socket figures live one level deeper).

| | Today | UI v2 target | Measured how |
|---|---|---|---|
| Nav items visible to a marina `monitor` | **7** | **4** (Marina, Alarms, Guard, Setup) | `Layout.tsx:40-57` — 7 unconditional; `system-health` and `settings` are `isAdmin`, `api-gateway` is `canApi` |
| Routes defined | **16** | **+6** marina, admin routes untouched | `App.tsx`, `grep -c '<Route'` |
| Pages | **12** | 12 kept for admin, **+1** marina root | `ls pages/` |
| Numbers on one dashboard tile | **5** (temp °C, moisture %, heartbeat age, pending count, active count) | **2** on an L1 row (amps, litres/min) — *amps since 2026-10-12, decision 2* | `PedestalCard.tsx:93-135` |
| Distinct indicators on one dashboard tile | **10** (5 numbers + `data_mode` / `initialized` / `ALARM` badges + OPTA and Cam dots) | **4** (status, power, water, guard) | same |
| Largest single component | **1 468 lines, 27 `useState`** (`PedestalControlCenter`) | **no marina component over 250 lines** — *2026-10-12: the limit STAYS; today 377 / 302 lines, split inside block 4* | `wc -l`, `grep -c useState` |
| Total lines across `components/pedestal/**` | **5 075** across 16 files | marina profile adds **under 1 200**, reuses none of it — *the limit STAYS; today 1 890* | `wc -l` |
| Status representations | colour-only in places | **always colour + icon + word** | `TC-UIR-01` |
| Marina-facing strings for a status | ad hoc per component | **one table, 11 entries** | §3 |

**One count I could not take statically, and will not invent:** taps from login to turning a
socket off. The chain is `/dashboard` → tile CTA → `PedestalView` → `PedestalControlCenter` →
socket control, which reads as four, but the tile CTA renders conditionally and
`PedestalControlCenter` has collapsible sections whose default state decides whether it is four
or five. **It gets counted in the device walkthrough** alongside the modal-in-modal and sunlight
questions you have already said not to guess at. The UI v2 target is **2** — marina root, then
the control on the row — and that one is countable from the wireframe.

**Acceptance:** all nine measured rows met, the tap count measured in the walkthrough and at
most 2, plus `TC-UIB-01` (the app boots) and `TC-UIR-01..08` green.
**A failure on any row is a failure of the profile, not a note for later.**

### Tests, in build order — the boot gate first

The standing rule: a component suite passing while the app does not boot is the same failure in
a different place. **The existing E2E gate is not trustworthy** — `tests/playwright_e2e.sh:41-45`
exits 0 when the backend is not on `:8000`, and it did exactly that on the last push.

1. **`TC-UIB-01` — the app boots.** Real browser, real built bundle. Loads `/marina`, asserts
   berth rows render, no error boundary, no uncaught console error. Must fail if the bundle does
   not build, a route is broken, or the CORE shape changed.
2. **Fix the silent skip.** The E2E stage must start the backend or **fail** — never exit 0
   having run nothing. If a real backend is too heavy per-push, run `TC-UIB-01` against a
   stubbed CORE so something always answers the boot question, and print the skip count either
   way.
3. **`TC-UIR-01..08`** — one per rule, asserting the **mechanism**: no raw colour class in
   `pages/marina/**`; every rendered condition has a string-table entry; `available:false`
   renders **no** control element (queried for absence, not for `disabled`); no page-level
   horizontal scroll at 360 px; status is never computed client-side.
4. **`TC-UIS-01` — stale is UNKNOWN.** A cabinet whose last heartbeat is older than the
   threshold but whose retained state reads normal renders **grey**. The v3.40 regression as a UI
   test, and the one I most expect to break later.
5. **`TC-UIS-02` — a stale valve is UNKNOWN**, distinct from `idle`. The §4.6 rule at the UI
   layer.

---

# 10. Build order

| # | Step | Ends with |
|---|---|---|
| 1 | `berth_assignments` + `GET /api/marina/berths` + the reduction | the contract answerable with `curl`, no UI |
| 2 | `TC-UIB-01` + fix the silent E2E skip | a gate that cannot pass vacuously |
| 3 | **Simulator**, rewritten against today's contract | 1–4 berths, 6 outlets, shared valve, three-phase Q1, valve state — all renderable without a trip to Krk |
| 4 | L1 dashboard, narrow-first, `<Status>` + string table | the screen the marina uses daily |
| 5 | Setup wizard | installation captures what step 1 needs |
| 6 | L2 berth detail incl. per-phase and provenance | the investigation screen |
| 7 | L2 alarms + marina-scoped endpoint | alarm list visible to the marina at last |
| 8 | L2 guard screen | guard gets its marina face |
| 9 | Analytics demoted to L3, nav reduced to 4 | the simplicity counts met |
| 9b | **Water-reporting toggle** — `report_water_sessions` column, one predicate in `erp_webhook`, Card 5 on `/api-gateway`, `TC-SIX-16b` amended to permit that named predicate and nothing else | per-site control over what the ERP receives, out of `.env` and onto a screen. Independent of the marina profile; can land at any point |
| 10 | **One deployment runbook: guard + UI together**, acceptance measured on the NUC | numbers before the merge to `main`, not after |

Step 1 before step 4 matters: with CORE answerable by `curl`, L1 is a rendering job against a
fixed shape. Same discipline that made guard's measurement stage useful before it had any UI.

---

# 11. Deferred — not required for the UI to work

Found during the foundation work. **Yours to prioritise; none of it is in the build above.**

**Status 2026-10-12, D14–D19 — none built:**

| | State | Evidence |
|---|---|---|
| D14 | NOT BUILT | `auth/dependencies.py:22` still admits `monitor_control_api` |
| D15 | NOT BUILT — allowlisted and guarded | `test_fe_be_contract.py:112-120`; TC-FEBE-01/05/06 |
| D16 | NOT BUILT — only skipped | `test.skip(true, …D16…)` at line 23 of four specs |
| D17 | NOT BUILT — not reproduced off the cabinet | §13 check 17 measures it |
| D18 | NOT BUILT — cabinet configuration | `external_api_admin.py` default `[]` |
| D19 | NOT BUILT | `SocketCard.tsx:49`, `mqtt_handlers.py:2094` |

| | Item | Why deferred |
|---|---|---|
| D1 | **ERP key rotation.** A 10-year `external_api` JWT, and the ERP `X-API-Key` is compiled into the mobile bundle (`EXPO_PUBLIC_ERP_API_KEY`) so it must be assumed known. Procedure written (`docs/erp_key_rotation.md`); precondition is that no shipped client depends on it. | sequenced behind ERP taking over `/scan` |
| D2 | **`usage/history` docstring says admin-only; the code is `require_any_role`** and it returns `customer_name` and `nfc_user_id`. Doc/code drift of the same shape as the `require_control` finding. | resolved by **BLOCK-2** (§1, customer names) either way |
| D3 | **The gateway self-proxy mints a real admin JWT** (5 min, first active admin's id and email) and `X-Ext-Api-Caller` is a provenance hint, not a boundary. Documented as such; worth a synthetic principal instead of a real user's identity. | works correctly; the objection is to the blast radius if the secret leaks |
| D4 | **NFC is absent from the API catalog entirely**, so `/api/ext/nfc/...` always 403s. The ERP reaches NFC only on the direct `X-API-Key` channel. Intentional, undocumented. | now documented here; no change needed |
| D5 | **`_make_internal_admin_jwt` is duplicated** byte-for-byte in `external_api_gateway.py` and `external_api_admin.py` | two copies of a token minter is one too many |
| D6 | **No retention policy** except `error_logs`; no disk-full guard | pre-existing, unchanged |
| D7 | **Static JWT secret, anonymous MQTT, unauthenticated camera stream, brute-forceable OTP** | from the 2026-06-10 audit; nothing applied |
| D8 | **Comm-loss watchdog misses cabinets already offline at backend restart**; stale sessions from that window need manual SQL | known since v3.39 |
| D9 | **Nothing enforces that the git hooks are installed** (`core.hooksPath` can be unset) | accepted knowingly |
| D10 | **Open firmware questions**: packet timestamping (the `millis()` rollover that silences a cabinet at 24.85 days), per-valve fault in the status topic, `config/hardware` fitting in one publish | a list for when a firmware conversation opens, not a request |
| D11 | **Mobile app release** carrying the water-NFC fixes. Mode 2 is blocked on it; mode 1 is not | sequenced with the water toggle (§1.3) |
| D12 | **`PedestalControlCenter` is 1 468 lines with 27 `useState`** | the admin profile keeps it; the marina profile does not touch it |
| **D13** | **The gate's eslint stage has never run, and could never have run.** eslint is not a devDependency of `frontend/` — it appears in the `lint` npm script and nowhere else — and there is no eslint config file. The stage took its "not found" branch on every invocation since it was written, silently until 2026-09-30, while the gate banner advertised eslint as part of the full gate. **Found 2026-10-01**; the gate now states the truth and the banner no longer claims it. Adopting it means installing eslint plus the TypeScript plugins, writing a config, and fixing whatever it finds on a codebase that has never been linted — **volume unknown and deliberately not measured**, because a count taken now would set an expectation before you have decided whether to adopt it. The colour-class rule that §5.1 and §9 depend on is specified as a **test** (`TC-UIR-01`, a source scan), not a lint rule, precisely so it does not inherit this. |
| **D14** | **Make `/api-gateway` admin-only.** An ERP integration screen is installation work, not operations — the same reasoning that made NFC provisioning admin-only. Five endpoints, done once. Decided by the owner 2026-10-01 and deliberately NOT inside UI v2. | owner's decision, scheduled separately |
| **D15** | **`GET /api/camera/{id}/detections` has never existed.** The backend serves `/camera/{id}/snapshot` and `/stream`, and guard serves `/api/guard/detections`, but there has never been a per-pedestal detections route. `CameraModal.tsx` calls it in synthetic mode and sits on "Loading YOLO detections…" for ever. Admin profile only; not used by the marina profile. Allowlisted in `test_fe_be_contract.py` with its reason, printed on every run, and the allowlist self-cleans in both directions. | found 2026-10-02 by the first run of the FE/BE contract test |
| **D16** | **23 pre-existing Playwright specs fail.** They had never run: the e2e runner exited 0 whenever nothing answered on `:8000` — and every spec mocks its own API with `page.route`, so a live backend was never needed in the first place. The runner no longer skips silently, which is why these are suddenly visible. Unrelated to the marina profile, whose 8 specs pass. | found 2026-10-02 |
| **D17** | **The whole `/api/ext/` family returns 401** — `pedestals/{id}/status`, `pedestals/{id}/water`, `marinas/{id}/load/alarms`, `marinas/{id}/breaker/alarms`. Those are exactly the routes the ERP uses; only the older `/api/...` routes passed. From the stored `verification_results` on the live `external_api_config` row, dated 2026-08-21. **Blocks acceptance area 5.** Does not block the v3.45 deploy — nothing is pushed out of the cabinet today (no `webhook_url`). | measured on the cabinet 2026-10-10 |
| **D18** | **`allowed_events` contains no session events.** The live row holds `["heartbeat", "temperature_reading"]`; the ERP integration document describes session lifecycle events, none of which are enabled. So even with a webhook URL configured, `session_activated` / `telemetry` / `session_ended` would not be dispatched by the gateway path. **Blocks acceptance area 5.** | measured on the cabinet 2026-10-10 |
| **D19** | **The admin profile still displays watts from `powerKw`.** `PedestalView` and `SocketCard` read the websocket `watts`, which `mqtt_handlers._handle_event_telemetry_update` computes as `powerKw * 1000` straight from the `opta/events` payload — a message carrying no voltage or current, so it cannot be converted to amps without a cross-topic lookup. `SocketLoadMeterPanel` reads `meter_power_kw`, which is now None on an impossible reading, so it shows blank rather than an inflated figure. The marina profile shows amps and is unaffected. | v3.45 scope: the marina profile only |


---

# 12. What I am not proposing

- **No rebuild of occupancy detection or matching.** The data and thresholds are good; only
  placement changes.
- **No change to the admin profile** beyond the one new marina alarm endpoint.
- **No new charting.** Analytics changes depth, not content.
- **No touching `energy_intervals`.** Historical billing stays as written.
- **No notification path**, not even disabled.
- **No QR.**
- **No multi-tenant keying.** One NUC per marina; the ext-API key is per-marina by deployment.


---

# 13. Checks after the upgrade — cabinet-only

**Added 2026-10-12.** Every check here can be performed ONLY on the cabinet. Run it top to
bottom, tick each line as it is done, and do not skip ahead: access comes first, because if
access fails nothing below it matters.

## 13.0 The decision this list exists for

**One upgrade, at the end, deliberately.** Everything accumulates on `develop`, each push
through the full gate. `main` is what the cabinet pulls (`upgrade.sh` deploys `origin/main`), so
it is touched ONCE, immediately before that one upgrade — an unplanned upgrade (for example
during a cabinet recovery) must never deploy an unchecked batch. `main` stays at `e80a4c1`
until then. The NFC scan and R1 are the end-to-end test and come LAST, when everything else
exists.

**Accepted risk, named, not overlooked.** Until that upgrade, cabinet 1 runs the old code, and
everything only the cabinet can reveal stays unrevealed. Concretely, until then:

- `/ws` is open to anyone, via Cloudflare, with the whole telemetry stream;
- REST routes without any login are reachable the same way, among them `GET /api/sessions`
  with `customer_id` / `customer_name` / `nfc_user_id` / `erp_ref`;
- `POST /api/predictions/train` runs without login. **That one is not a leak but CPU
  consumption** — the NUC is an Atom without a GPU — and must not be read as the same kind of
  finding as `/ws`.

The customer fields are `null` today because there are no NFC sessions. **The first real NFC
session before the upgrade changes this assessment.**

**A recorded reservation (Claude, 2026-10-12), not a change of plan.** The one upgrade grows
with every block, and R1 at the end means a break in the chain is discovered last. If block 4
exceeds its 3–4 day estimate, this is reported and the owner decides again. Mitigation that
IS in the plan: a rehearsal of R1 on dev with the simulator, in block 5, before the release.

**The rule from now on:** whoever finishes anything that can be proven only on the cabinet adds
its check to this list IN THE SAME COMMIT. The list grows with the work and is never
reconstructed from memory.

Each check states what to do if it fails:

- **ROLLBACK** — stop and roll back now (§13.11).
- **RECORD** — write down the outcome and continue; nothing that worked before is broken.
- **STOP** — do not run the steps that depend on it.

Secrets are never typed on a command line: read them with `read -s` and pass them in a header.

## 13.1 Before the upgrade (step 0)

| # | Check | Command / step | Expected | If it fails | Outcome |
|---|---|---|---|---|---|
| 0.1 | A second session is open, through BOTH ways in | Open one session via `ssh2.lika.solutions` and one via Tailscale; keep both open until 13.3 passes | Both live | STOP — do not start | ☐ |
| 0.2 | The current commit is recorded | `git -C ~/Cloud_IOT rev-parse HEAD \| sudo tee /root/pre-release.commit` | A hash | STOP | ☐ |
| 0.3 | The backend unit is saved | `U=$(systemctl show -p FragmentPath --value cloud-iot-backend.service); sudo cp -a "$U" /root/cloud-iot-backend.service.pre-release` | File exists | STOP | ☐ |
| 0.4 | The venv is saved | `sudo cp -a /opt/cloud-iot/backend/.venv /opt/cloud-iot/backend/.venv.pre-release` | Copy exists | STOP | ☐ |
| 0.5 | Both databases are saved — ONLINE, never with `cp` | **Not `cp`:** the databases run in WAL mode, and copying a live one can produce an inconsistent copy without the `-wal` contents. Use SQLite's backup API, which is consistent while the backend runs: `sudo python3 -c "import sqlite3;[sqlite3.connect(s).backup(sqlite3.connect(d)) for s,d in (('/opt/cloud-iot/backend/pedestal.db','/root/pedestal.db.pre-release'),('/opt/cloud-iot/backend/data/users.db','/root/users.db.pre-release'))]"`, then check both copies: `sudo python3 -c "import sqlite3;print([sqlite3.connect(f).execute('PRAGMA integrity_check').fetchone()[0] for f in ('/root/pedestal.db.pre-release','/root/users.db.pre-release')])"`; and note the owner: `stat -c '%U:%G' /opt/cloud-iot/backend/pedestal.db \| sudo tee /root/db.owner` | `['ok', 'ok']`; an owner such as `cloud-iot:cloud-iot` | STOP | ☐ |
| 0.6 | No other unit has pending changes that our `daemon-reload` would activate | `systemctl list-unit-files 'ssh*' --no-legend` — note which of `ssh.service` / `ssh.socket` is ENABLED: on recent Ubuntu SSH is often socket-activated, and then the service can read `inactive` while SSH works, then `for u in cloudflared tailscaled docker nginx <ssh-unit>; do echo "$u $(systemctl show -p NeedDaemonReload --value $u)"; done` | Every line ends in `no` | STOP — find out who changed which unit | ☐ |
| 0.7 | Baseline of the bind | `ss -ltn 'sport = :8000'` | `0.0.0.0:8000` (the old state) | RECORD | ☐ |
| 0.8 | The ERP key is configured — without printing it | `sudo grep -c '^ERP_API_KEY=.\+' /opt/cloud-iot/backend/.env` | `1` — without it every `/scan` below answers 503 | STOP for 13.7 and 13.10 | ☐ |

## 13.2 The upgrade

| # | Check | Command / step | Expected | If it fails | Outcome |
|---|---|---|---|---|---|
| U.1 | The one upgrade | `sudo bash ~/Cloud_IOT/nuc_image/upgrade.sh` | Ends with `Upgrade complete.`; prints `Backend bound to loopback only: 127.0.0.1:8000` | ROLLBACK | ☐ |

## 13.3 Access — before anything else

| # | Check | Command / step | Expected | If it fails | Outcome |
|---|---|---|---|---|---|
| 1 | SSH through the tunnel | From the second, already-open machine: a NEW connection to `ssh2.lika.solutions` | Login prompt, login works | ROLLBACK from the session still open — never close the last live connection | ☐ |
| 2 | Tailscale | `tailscale status \| head -3` on the NUC, plus a NEW CLI connection over the tailnet from another machine | Cabinet online; connection works | ROLLBACK | ☐ |
| 3 | The web UI | Open `https://marina2.lika.solutions`, log in with 2FA | Dashboard loads | ROLLBACK | ☐ |
| 4 | Services | `systemctl is-active cloudflared tailscaled docker nginx <ssh-unit> cloud-iot-backend`, where `<ssh-unit>` is the one ENABLED in 0.6 (`ssh.socket` if SSH is socket-activated) | Every line `active` — and check 1 already proved SSH works | ROLLBACK | ☐ |

## 13.4 Bind

| # | Check | Command / step | Expected | If it fails | Outcome |
|---|---|---|---|---|---|
| 5 | Loopback only | `ss -ltn 'sport = :8000'` | Only `127.0.0.1:8000` | ROLLBACK (upgrade.sh should already have stopped) | ☐ |
| 6 | Refused from the LAN | From another machine on the cabinet LAN: `curl -m 5 -s -o /dev/null -w '%{http_code}\n' http://<NUC-LAN-IP>:8000/health` | Connection refused (`000`) | RECORD — nothing that worked is broken; investigate | ☐ |

## 13.5 Backend health and dependencies

| # | Check | Command / step | Expected | If it fails | Outcome |
|---|---|---|---|---|---|
| 7 | Starts without an import error | `journalctl -u cloud-iot-backend --since "15 min ago" --no-pager \| grep -iE "Traceback\|ImportError\|ModuleNotFoundError"`, then `curl -s http://127.0.0.1:8000/health` | No match; health answers | ROLLBACK (venv) | ☐ |
| 8 | Security series re-measured | `python3 -m venv /tmp/pa && /tmp/pa/bin/pip install -q pip-audit`; `/opt/cloud-iot/backend/.venv/bin/python -m pip freeze --exclude-editable \| grep '==' > /tmp/nuc_freeze.txt`; `/tmp/pa/bin/pip-audit -r /tmp/nuc_freeze.txt --no-deps --disable-pip` | None of PyJWT, Pillow, pydantic-settings, python-dotenv, urllib3, anyio, pyasn1 in the list; record the count | RECORD | ☐ |
| 9 | Fatal pip | **No cabinet check.** It cannot be shown on the cabinet without deliberately breaking an install. It is proven on dev: `tests/backend/test_upgrade_script_deps.py::test_pip_failure_stops_the_upgrade` and `::test_pip_missing_stops_the_upgrade`, each failing against the previous script (f591426) as a negative control. | — | — | n/a |

## 13.6 `/ws`

| # | Check | Command / step | Expected | If it fails | Outcome |
|---|---|---|---|---|---|
| 10 | Anonymous is refused | `curl -s -o /dev/null -w '%{http_code}\n' --http1.1 -H 'Connection: Upgrade' -H 'Upgrade: websocket' -H 'Sec-WebSocket-Version: 13' -H 'Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==' https://marina2.lika.solutions/ws` | `403` (was `101`) | RECORD — the hole stays open; investigate before R1 | ☐ |
| 11 | Logged-in UI still updates itself | Log in; the WebSocket dot is green; a socket state change appears without a reload | Live updates | RECORD — the data still arrives via REST | ☐ |

## 13.6a REST — identity before data (block 1, 2026-10-12)

| # | Check | Command / step | Expected | If it fails | Outcome |
|---|---|---|---|---|---|
| 11a | Anonymous REST is refused | `for u in /api/sessions /api/pedestals /api/berths /api/predictions/status /api/system/training-storage; do echo "$u $(curl -s -o /dev/null -w '%{http_code}' https://marina2.lika.solutions$u)"; done` | Every line `401` or `403` (was `200`) | RECORD — investigate before R1 | ☐ |
| 11b | Training cannot be started anonymously | `curl -s -o /dev/null -w '%{http_code}
' -X POST https://marina2.lika.solutions/api/predictions/train` | `401` or `403` | RECORD | ☐ |
| 11c | The logged-in UI still loads its data | After login: the pedestal list, sockets and valves config, LED schedule and the Berth page all render | Pages load as before | ROLLBACK if the UI is unusable; otherwise RECORD | ☐ |

## 13.7 Water and D6.1

| # | Check | Command / step | Expected | If it fails | Outcome |
|---|---|---|---|---|---|
| P.1 | Precondition — NFC mode BEFORE smart mode | In the UI, switch the pedestal to NFC mode FIRST, then turn smart mode on. Check: `sudo -u cloud-iot /opt/cloud-iot/backend/.venv/bin/python3 -c "import sqlite3;print(sqlite3.connect('/opt/cloud-iot/backend/pedestal.db').execute('SELECT socket_id,auto_activate FROM socket_configs').fetchall())"` | Every socket `0`. **The order matters:** smart mode on with a socket still at `auto_activate=1` energises it on plug-in without a scan — a silent pass that proves nothing | STOP — turn smart mode off again | ☐ |
| 12 | A valve never opens itself | Trigger diagnostics: UI → pedestal → Config → Diagnostics (it calls `POST /api/pedestals/1/diagnostics/run`). Then `journalctl -u cloud-iot-backend --since "10 min ago" --no-pager \| grep ValveAutoOpen` | One `SKIPPED: ERP mode` line per valve, and no valve opened. **No `ValveAutoOpen` line at all means the diagnostic response never arrived: that is NOT a pass — RECORD it as unproven** | STOP — water is open to nobody; turn smart mode off | ☐ |
| 13 | The new `/scan` works | `read -s ERP_KEY`, then `curl -s -X POST http://localhost/api/nfc/scan -H "X-API-Key: $ERP_KEY" -H 'Content-Type: application/json' -d '{"cabinet_id":"MAR_KRK_ORM_01","outlet":"Q2","erp_ref":"CHECK-SCAN"}'`, on an outlet with NOTHING plugged in; let it expire after 5 min | `"status":"pending"` | RECORD | ☐ |
| 14 | The old `/scan` body is refused | Same curl, with `-o /dev/null -w '%{http_code}
'` added and `-d '{"nfc_tag_id":"X","user_id":"Y"}'` | `422` | RECORD | ☐ |
| 15 | The ack endpoint answers | `curl -s -X POST http://localhost/api/nfc/sessions/ack -H "X-API-Key: $ERP_KEY" -H 'Content-Type: application/json' -d '{"session_ids":[999999999]}'` | `"unknown":[999999999]` | RECORD | ☐ |
| 16 | The session list answers | `curl -s -o /dev/null -w '%{http_code}
' "http://localhost/api/nfc/sessions" -H "X-API-Key: $ERP_KEY"` (no filter), then the same with `?erp_ref=CHECK-SCAN` | `400`, then `200` | RECORD | ☐ |

## 13.8 D17

| # | Check | Command / step | Expected | If it fails | Outcome |
|---|---|---|---|---|---|
| 17 | Reproduce the `/api/ext/*` 401 — seen so far only on the cabinet | `read -s EXT_KEY` (the gateway key), then `curl -s -w '\n%{http_code}\n' -H "Authorization: Bearer $EXT_KEY" http://localhost/api/ext/pedestals/1/status` | A MEASUREMENT, not pass/fail: record the code and the body. `401` confirms D17; `200` means it does not reproduce after the upgrade | RECORD | ☐ |

## 13.9 Migration — the four populations

| # | Check | Command / step | Expected | If it fails | Outcome |
|---|---|---|---|---|---|
| 18 | Dry run | `sudo -u cloud-iot /opt/cloud-iot/backend/.venv/bin/python3 ~/Cloud_IOT/scripts/stamp_consumption_source.py --db /opt/cloud-iot/backend/pedestal.db` | Four counts; "partition all … exactly"; exit 0. Record the counts | STOP — do not apply; record the refusal | ☐ |
| 19 | Apply | The same command with `--apply` (0.5 has saved the DB) | `APPLIED.`; "remaining with no source" equals the D count | Restore the database by the §13.11 procedure — stop, copy, REMOVE `-wal`/`-shm`, restore the owner. Never a bare `cp` | ☐ |
| 20 | Stamps on the 149 sessions | `sudo -u cloud-iot /opt/cloud-iot/backend/.venv/bin/python3 -c "import sqlite3;c=sqlite3.connect('/opt/cloud-iot/backend/pedestal.db');print(c.execute('SELECT consumption_source,COUNT(*) FROM sessions GROUP BY 1').fetchall());print(c.execute('SELECT COUNT(*) FROM sessions WHERE consumption_source IS NULL AND (energy_kwh IS NOT NULL OR water_liters IS NOT NULL)').fetchone())"` | No session with a figure and no source (second line `(0,)`); A + B add up to the sessions that had a figure | RECORD | ☐ |

## 13.10 R1 — last, and the only check that decides Krk

| # | Check | Command / step | Expected | If it fails | Outcome |
|---|---|---|---|---|---|
| 21 | Still ready | P.1 still holds: the same `socket_configs` query, and smart mode on | Every socket `0`; smart mode on | STOP | ☐ |
| 22 | Physical meter before | Read Q1's physical meter | Reading noted | — | ☐ |
| 23 | Scan | `/scan` as in 13 with `"outlet":"Q1","erp_ref":"R1-TEST-1"` | `pending` | STOP | ☐ |
| 24 | Plug in within 5 minutes | Plug into Q1; `curl -s "http://localhost/api/nfc/sessions?erp_ref=R1-TEST-1" -H "X-API-Key: $ERP_KEY"` | One `active` session carrying `erp_ref` `R1-TEST-1` | STOP — R1 fails | ☐ |
| 25 | Draw, then stop | Draw well above the meter's resolution; stop with `curl -s -X POST http://localhost/api/nfc/session/<id>/stop -H "X-API-Key: $ERP_KEY"` | Session `ended` | STOP — R1 fails | ☐ |
| 26 | The figures agree | Read Q1's physical meter again; fetch the session as in 24 | `energy_kwh` = `meter_energy_end_kwh − meter_energy_start_kwh` exactly; matches the physical meter's delta within its resolution; `consumption_source` = `register` | **R1 fails — this decides Krk** | ☐ |

## 13.11 Rollback

```bash
U=$(systemctl show -p FragmentPath --value cloud-iot-backend.service)
sudo cp -a /root/cloud-iot-backend.service.pre-release "$U"
sudo systemctl daemon-reload
sudo systemctl restart cloud-iot-backend.service
ss -ltn 'sport = :8000'                      # 0.0.0.0:8000, as before
# if the venv is at fault:
sudo systemctl stop cloud-iot-backend.service
sudo rm -rf /opt/cloud-iot/backend/.venv && sudo mv /opt/cloud-iot/backend/.venv.pre-release /opt/cloud-iot/backend/.venv
sudo systemctl start cloud-iot-backend.service
# if a database is at fault (after 19). The -wal and -shm files MUST go: a stale WAL replayed
# over the restored file corrupts it. And the copy belongs to root — give it back its owner.
sudo systemctl stop cloud-iot-backend.service
sudo cp /root/pedestal.db.pre-release /opt/cloud-iot/backend/pedestal.db
sudo rm -f /opt/cloud-iot/backend/pedestal.db-wal /opt/cloud-iot/backend/pedestal.db-shm
sudo chown "$(sudo cat /root/db.owner)" /opt/cloud-iot/backend/pedestal.db
#   same three lines for /opt/cloud-iot/backend/data/users.db from /root/users.db.pre-release, only if users.db is at fault
sudo systemctl start cloud-iot-backend.service
```

The next `upgrade.sh` binds loopback again (the step is idempotent): a rollback holds until it
is decided otherwise. Nothing in this list touches sshd, cloudflared, tailscaled or any network
or firewall configuration.

## 13.12 Not yet on this list

These are not built yet, so they have no check yet. Each gets its own check in the commit that
builds it:

- part B — role filtering of the broadcast and of `GET /api/sessions`.

---

# 14. Security model

The owner's rule: the system has users, they pass two-factor authentication, and **every access,
at every layer, requires that authenticated user.** There is no layer where data is reached
without one. Rule 13 of `docs/engineering_notes.md` states it as a rule for every future channel.

| | |
|---|---|
| Identity | One function, `auth.dependencies.operator_from_token`, for HTTP routes AND `/ws` — never a copy. A pre-2FA (`totp_pending`) token is never an operator. |
| `/ws` (part A, built, `e80a4c1`) | Operator only, proven BEFORE accept (handshake 403, no message); token in `Sec-WebSocket-Protocol`, never in a URL (URLs land in access logs); closed at token expiry. Customer and `ws_session` tokens refused. Proof: `test_ws_auth.py` TC-WSA-01..07, 6 of them failing on the code before. |
| REST without login | **Closed in block 1 (2026-10-12):** identity on every `/api` route; `/api/sessions` and `/api/predictions` on the router itself; `POST /predictions/train` needs a control role. `test_rest_auth.py` TC-RA-01 forbids a new unauthenticated `/api` route unless it is listed as public WITH a reason; TC-RA-03 refuses anonymous callers (19 failed on the code before). Still open by design: `/api/camera/{id}/stream` (R4 — an `<img>` cannot send a header). Cabinet check: §13.6a. |
| Staff and customer data — **owner's decision, binding** | **MARINA STAFF MUST NOT SEE CUSTOMER DATA.** The customer's identity lives in the ERP; the cabinet shows the session and the consumption, not the customer's name or identifier. Only admin sees more. |
| Part B (block 1, planned) | One list of identity keys — `customer_id`, `customer_name`, `nfc_user_id`, `erp_ref`. Removed for non-admin from every websocket broadcast, and from `GET /api/sessions`, usage history and reconciliation divergence. **Billing and export routes are locked to admin, not filtered:** the cabinet does not bill — the ERP does — and those routes are legacy; filtering them would mean maintaining them as if they had a purpose. |
| Not in scope now | Cloudflare Access on the hostname — owner's decision, later: it would need a service token for the ERP webhook and every automated call. No firewall, no change to sshd / cloudflared / tailscaled, ever. |

# 15. Consequences of D6.1 for the UI

D6.1 (2026-10-12): the ERP is the only owner of the NFC mapping and of the customer.

- **No tag table.** The NFC provisioning table is commented out; in its place one line says the
  ERP maps tags to outlets. The QR/NFC switch stays — it sets the sockets' auto-activate, which
  NFC mode must turn OFF.
- **Water never opens for nobody.** A valve never opens itself in ERP mode, and an `activate`
  on a valve is REFUSED (409) without a live NFC reservation — from every caller, the operator
  included. A water control on a marina screen (block 4) must therefore expect that refusal
  and say why, not offer an "open" that cannot succeed.
- **No customer on marina screens.** Sessions carry the ERP's `erp_ref`, which identifies a
  customer and is filtered for non-admin (§14).
- **The mobile app does not talk to the cabinet.** Its live view no longer connects (`/ws` is
  operator-only); the app goes through the ERP.
