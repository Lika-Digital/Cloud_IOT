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
| 8 | Live values by websocket | 15 s polling | **WS — but only AFTER part B** (role filtering, §14). *Part B built 2026-10-12, so this no longer blocks; the switch is block 4 work.* The broadcast carries `customer_id`; switching `/marina` to WS before filtering would put customer identity on the page. Polling stays until then | §7 |
| 9 | New `energy_intervals` rows carry `berth_id` | Only `berth_ref` | **SPEC.** Built 2026-10-12 (block 2): NULL = not known; old rows stay NULL — see the measured reason in §6 | §6, §13.9 20a, §13.10 27. `/scan` returns it too (BREAKING for the ERP, §13.7 13a); the admin export has it as the last column |

## 0.2 Status of the main items (2026-10-12)

BUILT+PROVEN = code + a test that can fail, green. BUILT-UNPROVEN = code, nothing proves it.
Evidence is a test, a commit or a path, never a claim.

| Item | State | Evidence |
|---|---|---|
| CORE `/api/marina/berths`, berth detail, status sentences and precedence | BUILT+PROVEN | `test_marina_core.py` TC-MC-01..14, `test_marina_core_shape.py` |
| `outlet_silent` (rank 2.5) | BUILT+PROVEN on dev, cabinet fact pending | block 3, 2026-10-12: a socket is silent when the fresher of its meter telemetry (`meter_load_updated_at`, every 5 s) and its status message (`socket_states.updated_at`) is missing or older than 60 s; the power state is then `unknown`, not `idle`. `test_outlet_silent.py` TC-OS-01..05 (02/03 failed on the code before). That idle sockets really report every 5 s is checked on the cabinet: §13.6b 11i |
| Guard on `/marina` | BUILT+PROVEN on dev; **owner's decision pending** | block 3, 2026-10-12: `services/guard_state.py` reads `guard.service.effective_state` per pedestal (worst camera wins; desired ARMED + silent worker stays UNAVAILABLE). `test_marina_guard_state.py` TC-MGS-01..06 (01/02/04/05 failed on the code before — every pedestal said "unavailable"). **Open:** a pedestal with NO guard configured (cabinet 1 today) still reads "Guard unavailable" — a fault sentence for something not installed. Whether it should say "No guard on this pedestal" is the owner's call |
| Row controls (power, water, light) | NOT BUILT | no page passes `onAction`; TC-UIR-03 therefore passes vacuously |
| TC-UIR-01 (no raw colour classes) | BUILT+PROVEN, with exemptions | `test_ui_rule_colours.py` (block 3, 2026-10-12): no status hue (red/green/amber/yellow/orange/emerald/lime/rose on a colour utility) in `pages/marina/**`, `components/marina/**` outside `Status.tsx`, whose exported `TONE` is the only palette. Measured with that pattern: 29 lines, 2 of them in `Status.tsx` (the earlier "32" used a pattern that was not recorded). Fixed now: MarinaGuard, MarinaAlarms, MarinaWater. Exempt per file until block 4: MarinaDashboard, BerthDetail, MarinaSetup — the gate fails when block 4 is marked DONE below while any is still exempt |
| Block 4 — UI v2 remainder | NOT DONE | Row controls, L3 history, nav of 4 (Analytics already out — see the "Block 4 (part)" row below; do not redo), `<PhaseBlock>`, wizard step 3, §9 splits, `/marina` on the websocket. **This row is the deadline of TC-UIR-01's exemptions** — `test_ui_rule_colours.py` reads it; setting it to DONE with exemptions left fails the gate |
| L3 history, `<PhaseBlock>`, nav of 4, Card 5 (water toggle) | NOT BUILT | no history route in `App.tsx`; `Layout.tsx:40-57` has 8 items |
| Setup wizard | PARTIAL, UNPROVEN | `MarinaSetup.tsx` (`4eb381e`); step 3 missing; route not `adminOnly`; no UI test |
| §9 size limits | FAILS | 377 / 302 lines; 1 890 total |
| `match_ok_bit` "never analysed" | BUILT+PROVEN | block 3, 2026-10-12: `vessel_matches` is `false` only for a measured mismatch (`state_code` 2), `true` only for `match_ok_bit` 1, otherwise `null` = not known — never analysed, analysis failed, berth empty, no reference to compare. UI says "not known" for null. `test_vessel_match_truth.py` TC-VMT-01 (the four not-known cases failed on the code before) |
| D2 paired redaction test (HTTP) | BUILT+PROVEN | `test_identity_redaction.py` TC-IDR-03: monitor gets none of the identity keys, admin gets them (failed on the code before, 2026-10-12) |
| Block 4 (part) — Analytics out of the nav (L3); `ui_v2_audit.md` §7 #9, **NOT the owner's finding 9** (`retention_service.py:24-27`, untouched) | BUILT+PROVEN 2026-10-14 | `Layout.tsx`: no Analytics item for any role; berth detail → "This month" → "Pedestal consumption history ›" opens `/analytics?pedestal=<id>` with that pedestal preselected (`Analytics.tsx` reads `?pedestal=`). The route itself is unchanged. `marina.spec.ts` TC-UIN-01 failed on the code before (nav link count 1; no berth link). Nav is now 7 items for admin's shared part, not yet the 4 of block 4. `BerthDetail.tsx` is 253 lines, 3 over the §9 limit it already had on block 4's list |
| Plan item 4 — the reports: new format, staff file, legacy headers | BUILT+PROVEN on dev 2026-10-14; cabinet steps §13.9a | **Owner's decision 2026-10-14:** staff get a SEPARATE file, generated on its own with no customer column (`…staff.txt`, `/usage/staff-reports`, every operator); the admin file stays locked. Figures from the session row with provenance and both register readings (§4.4 says why, and when it returns to the ledger); unknown prints `—`; a total with any unmeasured session prints NO figure ("PARTIAL — N of M not measured"); a month not over or with open sessions is PROVISIONAL and regenerated — it used to be cached forever. `test_usage_report_truth.py` TC-REP-01..08, all eight failed on the code before; TC-REP-02 also caught two deliberate mutants (sum + note on the total line; sum on its own line). The five files on the cabinet are history: `scripts/mark_legacy_reports.py` prepends a header that states, per file, PARTIAL / INCOMPLETE from the database, and keeps the body bytes and the mtime (TC-LEG-01..04). **Open, needs the cabinet:** why 2026-05 and 2026-07 are empty (459 B) — the old filter was only `status='completed'` + `started_at` in the month, so either no session completed in those months or they were still open at generation; the script's INCOMPLETE line answers it per file (§13.9a R.2) |
| Guard point 8 — instance identity (1a) | BUILT+PROVEN on dev | `9107f90`, 2026-10-13: every guard message carries `instance`; the backend drops any other, the worker acts on and acks only its own. TC-GINT-09 (real mosquitto, a real second worker) failed on the code before in each of its three parts, shown separately. An identifier, not a credential — broker authentication is R4 |
| Guard point 8 — unit + install step (1b) | BUILT+PROVEN on dev, cabinet checks §13.6c | `nuc_image/cloud-iot-guard.service`, `nuc_image/install-guard.sh` (install only, never start; exit 3 = model missing, not a success); `test_guard_install.py` TC-GINS-01..09, four deliberate defects each caught; the real script and unit on a real systemd (WSL, systemd 255, Docker 29.1.3): the worker connected under the filter with docker-proxy AND with `userland-proxy=false` (the latter only with `172.18.0.0/16`, measured); ffmpeg stderr scrubbed of the camera password (TC-GCAP-08b, failed before) |

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
| **Auth** | `require_admin`, matching the rest of the page (D14, built 2026-10-14 — `require_api_config` no longer exists). |

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
(`TC-EIV-10`). **Any history or analytics view aggregates interval rows**, never session fields —
**with one exception in force, decided by the owner on 2026-10-14:**

**The monthly report (`usage_report_service`) reads the SESSION ROW**, not the ledger: each figure
is the session's `energy_kwh` / `water_liters`, labelled by its `consumption_source`, with BOTH
register readings (`meter_*_start` / `meter_*_end`) printed beside it so it can be recomputed by
hand. **Why:** on cabinet 1 `energy_intervals` has written no row since 2026-10-10 16:12:59 UTC,
and every row it holds is an integral estimate (`models/energy_interval.py`). A report from the
ledger would say "not measured" where the meter measured. The session row carries the register
delta itself, and where the ledger writes, the two agree by construction (TC-EIV-10).

**The condition for returning the report to the ledger** — a condition, not an intention: the
report goes back to aggregating interval rows when, on the cabinet, **(a)** the ledger has written
rows for every completed electricity session of one whole calendar month, and **(b)** for each of
those sessions the sum of its interval rows equals its `energy_kwh` (the check is §13.10, 27a, run
monthly until both hold). Until then this exception stands and the report says, in its own legend,
where its figures come from. Water has no ledger; water figures stay on the session row.

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

**BUILT 2026-10-12 (block 2)** — `test_energy_interval_berth_id.py` TC-EIB-01..04, failing on the code before; cabinet checks §13.9 20a and §13.10 27. So `energy_intervals.berth_id INTEGER NULL`, filled at write time from `berth_assignments` by
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
(`MarinaDashboard.tsx:66`). Part B was built 2026-10-12 and proven on dev (§14); the switch to
the websocket is block 4 work, and the cabinet proof is §13.6b.

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
| D14 | **BUILT+PROVEN 2026-10-14** | every `/api/admin/ext-api` route is `require_admin`; `require_api_config` and `_API_CONFIG_ROLES` deleted; route `adminOnly`, nav item in the admin group. `test_roles.py` TC-ROLE-06b reads the routes from the app (7) and failed on the code before (`monitor_control_api got 200`). Checked first: the ERP service account (`api_client`) never could reach these — it is not an operator role. `monitor_control_api` now acts as `monitor_control`; kept for existing accounts, no longer offered for new ones. **Cabinet fact not checked:** whether any account there holds `monitor_control_api` and used the page |
| D15 | **FIXED 2026-10-14 — by removal** | The call is gone, not built: a per-pedestal detections route would have had nothing real to return (synthetic mode plays a demo video; person detection is the guard's). `CameraModal.tsx` plays the video with no overlay and says no detection runs; `getCameraDetections` and its types deleted; the `KNOWN_DEAD_CALLS` entry deleted, so the allowlist is empty and TC-FEBE-01 now fails on ANY dead call |
| D16 | NOT BUILT — only skipped | `test.skip(true, …D16…)` at line 23 of four specs |
| D17 | NOT BUILT — not reproduced off the cabinet | §13 check 17 measures it |
| D18 | NOT BUILT — cabinet configuration | `external_api_admin.py` default `[]` |
| D19 | **BUILT+PROVEN 2026-10-14** | The only live display was `PedestalView.tsx:508` ("Power … W"); removed — the meter's `current_amps` is shown in the same block. `SocketCard.tsx` and `ActiveSessions.tsx` also rendered it but were imported nowhere: deleted. `test_ui_no_powerkw_watts.py` TC-UIR-04: no `.tsx` reads `.watts`; failed on the code before with all three. The backend still computes and stores `power_watts` (`mqtt_handlers.py`) — nothing renders it |

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

## 13.6b Staff do not see customer data (part B, block 1, 2026-10-12)

Needs a **non-admin operator account** (role `monitor` or `monitor_control`). If the cabinet has
none, create one in Users for this check — and say so in the outcome. Its token: log in as that
user in a browser, then DevTools → Application → Local Storage → `auth-store` → `token`. Put it
in the shell as `TOK=...` and nowhere else; it is never written into this list or a log.

| # | Check | Command / step | Expected | If it fails | Outcome |
|---|---|---|---|---|---|
| 11d | Sessions without identity | `curl -s -H "Authorization: Bearer $TOK" 'https://marina2.lika.solutions/api/sessions?limit=50' \| grep -oE '"(customer_id\|customer_name\|nfc_user_id\|erp_ref)"' \| sort \| uniq -c` | No output at all (before: every row carried the keys) | RECORD — staff see customer identity; fix before R1 | ☐ |
| 11e | Billing and export are admin only | `for u in /api/billing/customers /api/billing/spending /api/admin/export/usage; do echo "$u $(curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $TOK" https://marina2.lika.solutions$u)"; done` | Every line `403` (was `200`) | RECORD | ☐ |
| 11f | The broadcast without identity | Logged in as that user: DevTools → Network → WS → `/ws` → Messages. Wait for a `session_*` or `water_reading` frame (or plug in on an NFC socket), then search the frames for `customer_id`, `nfc_user_id`, `erp_ref` | Frames arrive; none of the three strings in them. **No session frame in the window = unproven, RECORD it as such — not a pass** | RECORD | ☐ |
| 11h | Customers, Contracts, report files, reviews, service orders and the berth calendar are admin only | `for u in /api/chat/unread-count /api/contracts/templates /api/admin/contracts /api/pedestals/1/usage/reports /api/admin/reviews/ /api/admin/service-orders/ /api/admin/berths/calendar/1; do echo "$u $(curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $TOK" https://marina2.lika.solutions$u)"; done`; and in the UI as that user: no Billing, Customers or Contracts in the menu, no "Download report" in a socket's usage history | Every line `403` (was `200`); the three menu items and the button absent | RECORD | ☐ |
| 11i | Idle sockets keep reporting, so `outlet_silent` does not fire on a healthy cabinet (block 3) | With nothing plugged in: `sudo -u cloud-iot /opt/cloud-iot/backend/.venv/bin/python3 -c "import sqlite3;c=sqlite3.connect('/opt/cloud-iot/backend/pedestal.db');print(c.execute('SELECT socket_id,meter_load_updated_at FROM socket_configs WHERE pedestal_id=1 ORDER BY 1').fetchall())"`, wait 15 s, run it again; then open `/marina` | Every socket's timestamp moved forward between the two runs (telemetry every 5 s, idle included); no berth row says "This outlet has not reported recently" | RECORD — if an idle socket's timestamp does NOT move, every idle berth will show that sentence: tell the owner before R1; the rule's input, not the rule, is wrong for this firmware | ☐ |
| 11j | The guard line says what the guard service says (block 3) | `sudo -u cloud-iot /opt/cloud-iot/backend/.venv/bin/python3 -c "import sqlite3;c=sqlite3.connect('/opt/cloud-iot/backend/pedestal.db');print(c.execute('SELECT camera_id,pedestal_id,desired_state FROM guard_config').fetchall())"`; then `/marina` | No rows (guard not deployed on cabinet 1): the line reads "Guard unavailable", as before — pending the owner's decision on wording. With rows: the line matches `/api/guard/status` for that pedestal (worst camera) | RECORD | ☐ |
| 11g | Admin still sees them | The same `curl` as 11d with an admin's token | The keys are listed — redaction is by role, not a loss of data. **This is 11d's control:** if the admin also gets no keys, the last 50 sessions carried no identity and 11d proved nothing — RECORD 11d as unproven | RECORD | ☐ |

## 13.6c Guard — install, then first start (section 1, 2026-10-13)

Guard is independent of everything else here: a failure in this section stops **guard only**.
It never rolls back the cabinet. Nothing in it prints the camera URL — it carries the camera's
password — and no check below puts the password on a command line.

**Install.** `nuc_image/install-guard.sh` — installs, never enables or starts. Proven on dev:
`test_guard_install.py` TC-GINS-01..09, and the real script on a real systemd (WSL Ubuntu
24.04, systemd 255), first run exit 3 without a model, second run all "unchanged".

| # | Check | Command / step | Expected | If it fails | Outcome |
|---|---|---|---|---|---|
| G.1 | Install | `sudo bash ~/Cloud_IOT/nuc_image/install-guard.sh; echo "exit=$?"` | `exit=3` and `MODEL MISSING` if the IR is not copied yet; `exit=0` and `GUARD INSTALLED — not enabled, not started` if it is. **Never** "INSTALLED" with a missing model | `exit=1`: RECORD the `[x]` line and STOP guard. `pip install … FAILED` most likely means no openvino/numpy wheel for this Python (3.14) — `/var/log/cloud-iot/guard-install.log` says which | ☐ |
| G.2 | Install is not start | `systemctl is-enabled cloud-iot-guard; systemctl is-active cloud-iot-guard` | `disabled`, `inactive` | STOP guard | ☐ |
| G.3 | Idempotent | Run G.1 again | Every line `[=] … unchanged`, no `[+]`; same exit code | RECORD | ☐ |
| G.4 | The backend venv is clean | `/opt/cloud-iot/backend/.venv/bin/pip list 2>/dev/null \| grep -ci openvino` | `0` (the script also refuses to finish otherwise) | STOP guard — openvino must never be in the production venv | ☐ |
| G.5 | One instance id on both sides | `sudo grep -h '^GUARD_INSTANCE_ID=' /opt/cloud-iot/guard/guard.env /opt/cloud-iot/backend/.env \| sort -u \| wc -l`; if G.1 printed `added GUARD_INSTANCE_ID to the backend .env`: `sudo systemctl restart cloud-iot-backend` and repeat §13.5 check 7 | `1`. The backend reads the id at start: without the restart it hears no worker and guard reads "unavailable" | STOP guard | ☐ |
| G.6 | The model | Copy the exported IR (`scripts/guard_export_model.sh`) to `/opt/cloud-iot/guard/models/yolov8n_openvino/` (`.xml` and `.bin`), then G.1 again | `exit=0`, `model: present` | STOP guard — record what the export produced | ☐ |
| G.7 | The egress filter's assumptions hold on THIS cabinet | `docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' pedestal-mqtt-broker`; `pgrep -c docker-proxy`; `cat /etc/docker/daemon.json 2>/dev/null \|\| echo none`; `docker version --format '{{.Server.Version}}'` | The broker inside `172.18.0.0/16` (measured `172.18.0.2`). RECORD the proxy mode: `docker-proxy` running = the worker reaches the broker via loopback; `"userland-proxy": false` = via the kernel's DNAT to the container, which is why `172.18.0.0/16` is in the unit (both measured 2026-10-13, Docker 29.1.3) | Broker outside 172.18.0.0/16: STOP guard — the unit's allow list is wrong for this cabinet; tell the owner | ☐ |

**First start — a separate step, after the install passed.**

| # | Check | Command / step | Expected | If it fails | Outcome |
|---|---|---|---|---|---|
| F.1 | Camera settings, without printing them | `sudo -e /opt/cloud-iot/guard/guard.env` — set `GUARD_STREAM_URL`, `GUARD_CAMERA_ID`, `GUARD_PEDESTAL_ID`; then `sudo grep -c '^GUARD_STREAM_URL=rtsp://' /opt/cloud-iot/guard/guard.env` | `1` (a count, never the value) | STOP guard | ☐ |
| F.2 | The filter as installed | `systemctl show cloud-iot-guard -p IPAddressAllow -p IPAddressDeny` | Allow `127.0.0.0/8 ::1/128 172.18.0.0/16 192.168.1.0/24` (any order), Deny `0.0.0.0/0 ::/0` | STOP guard | ☐ |
| F.3 | **Blockade or fault?** — the camera and the broker from OUTSIDE the filter, then from INSIDE it | Outside: `timeout 5 bash -c '</dev/tcp/192.168.1.191/554' && echo camera-open`; `timeout 5 bash -c '</dev/tcp/127.0.0.1/1883' && echo broker-open`. Inside the same filter: `sudo systemd-run --wait --pipe -q -p IPAddressDeny=any -p 'IPAddressAllow=127.0.0.0/8 ::1/128 172.18.0.0/16 192.168.1.0/24' bash -c "timeout 5 bash -c '</dev/tcp/192.168.1.191/554' && echo camera-open; timeout 5 bash -c '</dev/tcp/127.0.0.1/1883' && echo broker-open"` (`systemd-run -p` does not take the word `localhost` — measured — hence the prefixes) | Both lines both times | Open outside, closed inside = **the filter**, not the device: do not touch the camera, tell the owner. Closed outside too = the device or the broker — the filter is not the cause | ☐ |
| F.4 | Start | `sudo systemctl enable --now cloud-iot-guard`; wait 15 s; `systemctl is-active cloud-iot-guard`; `journalctl -u cloud-iot-guard -n 20 --no-pager -o cat \| grep -c 'MQTT connected'` | `active`, `1` or more | Exit 2 = no camera URL (F.1); exit 4 = no instance id (G.5); `cannot reach the MQTT broker` = run F.3 before anything else | ☐ |
| F.5 | The backend hears ITS worker | Logged in as admin: `/api/guard/status` | The camera's `worker_alive: true`, `state` `OFF` (it starts OFF and waits) | `worker_alive: false` while F.4 passed: the instance ids differ, or the backend was not restarted after G.5 | ☐ |
| F.6 | The camera password is in no log | `sudo journalctl -u cloud-iot-guard --no-pager \| grep -cF -f <(sudo sed -n 's\|^GUARD_STREAM_URL=rtsp://[^:/@]*:\([^@]*\)@.*\|\1\|p' /opt/cloud-iot/guard/guard.env)` — the password is read into a pipe, never an argument; then the same with `/var/log/cloud-iot/guard-install.log` as the input | `0` both times | STOP guard — record WHERE it appeared, not the value | ☐ |

## 13.7 Water and D6.1

| # | Check | Command / step | Expected | If it fails | Outcome |
|---|---|---|---|---|---|
| P.1 | Precondition — NFC mode BEFORE smart mode | In the UI, switch the pedestal to NFC mode FIRST, then turn smart mode on. Check: `sudo -u cloud-iot /opt/cloud-iot/backend/.venv/bin/python3 -c "import sqlite3;print(sqlite3.connect('/opt/cloud-iot/backend/pedestal.db').execute('SELECT socket_id,auto_activate FROM socket_configs').fetchall())"` | Every socket `0`. **The order matters:** smart mode on with a socket still at `auto_activate=1` energises it on plug-in without a scan — a silent pass that proves nothing | STOP — turn smart mode off again | ☐ |
| 12 | A valve never opens itself | Trigger diagnostics: UI → pedestal → Config → Diagnostics (it calls `POST /api/pedestals/1/diagnostics/run`). Then `journalctl -u cloud-iot-backend --since "10 min ago" --no-pager \| grep ValveAutoOpen` | One `SKIPPED: ERP mode` line per valve, and no valve opened. **No `ValveAutoOpen` line at all means the diagnostic response never arrived: that is NOT a pass — RECORD it as unproven** | STOP — water is open to nobody; turn smart mode off | ☐ |
| 13 | The new `/scan` works | `read -s ERP_KEY`, then `curl -s -X POST http://localhost/api/nfc/scan -H "X-API-Key: $ERP_KEY" -H 'Content-Type: application/json' -d '{"cabinet_id":"MAR_KRK_ORM_01","outlet":"Q2","erp_ref":"CHECK-SCAN"}'`, on an outlet with NOTHING plugged in; let it expire after 5 min | `"status":"pending"` | RECORD | ☐ |
| 13a | `/scan` names the berth, not the label (ERP item 2, BREAKING) | In the reply of 13: `berth_id` and `cabinet_label` | `berth_id` is an integer equal to `SELECT berth_id FROM berth_assignments WHERE pedestal_id=1 AND socket_id=2`, or `null` if Q2 is not assigned; `cabinet_label` is the cabinet's label; **no** `berth_ref` key. A string in `berth_id` = the old code is running | RECORD — and tell the owner before the ERP goes live on it | ☐ |
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
| 20a | `energy_intervals.berth_id` exists, every old row NULL (decision 9) | `sudo -u cloud-iot /opt/cloud-iot/backend/.venv/bin/python3 -c "import sqlite3;c=sqlite3.connect('/opt/cloud-iot/backend/pedestal.db');print('berth_id' in [r[1] for r in c.execute('PRAGMA table_info(energy_intervals)')]);print(c.execute('SELECT COUNT(*),COUNT(berth_id) FROM energy_intervals').fetchone())"` | `True`, then `(N, 0)` — N the existing rows (8675 when measured), and **0** carrying a berth: NULL means not known, the old rows are never back-filled | RECORD — the column is missing: the migration did not run; investigate before R1 | ☐ |

## 13.9a Reports — the five legacy files, and the monthly job (2026-10-14)

`D` is the reports directory: `D=$(sudo grep -oP '^REPORTS_DIR=\K.*' /opt/cloud-iot/backend/.env || echo /opt/cloud-iot/backend/reports)`.
R.1 runs BEFORE anything writes to those files — it is the proof of what they were.

| # | Check | Command / step | Expected | If it fails | Outcome |
|---|---|---|---|---|---|
| R.1 | **SHA256 of the five files, before the header** — we change a historical record, so the change must be provable | `sudo sha256sum "$D"/pedestal-1_2026-0[5-9].txt \| sudo tee /root/reports.sha256.pre-header && sudo cp -a "$D" /root/reports.pre-header` | Five lines (05, 06, 07, 08, 09); the copy exists | STOP — no header without the record | ☐ |
| R.2 | Dry run | `sudo -u cloud-iot /opt/cloud-iot/backend/.venv/bin/python3 ~/Cloud_IOT/scripts/mark_legacy_reports.py --reports-dir "$D" --db /opt/cloud-iot/backend/pedestal.db` | Five `legacy` lines; each `sha256=` equals R.1's line for that file; 2026-08 says `PARTIAL: generated 2026-08-24`. **Record what 2026-05 and 2026-07 say:** an `INCOMPLETE … holds N … shows 0` line means those months HAD completed sessions the report never showed — a defect of the old code, not "the old method" | STOP — a SHA that differs from R.1 means the file changed between the two steps | ☐ |
| R.3 | Apply | The same with `--apply` | Every file: `body unchanged: yes; mtime kept: yes` | Restore from `/root/reports.pre-header` (`sudo cp -a /root/reports.pre-header/. "$D"/`) and report | ☐ |
| R.4 | The change is exactly the header | `for f in "$D"/pedestal-1_2026-0[5-9].txt; do sudo grep -c '^#### LEGACY REPORT' "$f"; done; sudo sha256sum -c /root/reports.sha256.pre-header` | `1` five times; `sha256sum -c` reports all five as FAILED — they changed, by the header, which R.3 proved is the only change | RECORD | ☐ |
| R.5 | **The monthly job runs, and what it writes** — on or after 2026-11-01 06:00 (it ticks every 6 h) | `journalctl -u cloud-iot-backend --since 2026-11-01 -o cat \| grep "monthly reports:" \| head -3; ls -l "$D"/pedestal-1_2026-10*.txt; sudo head -6 "$D"/pedestal-1_2026-10.txt` | A line `monthly reports: 2 file(s) written for 2026-10`; both `.txt` and `.staff.txt` exist; `Status: FINAL` (or PROVISIONAL naming the open sessions — then it is rewritten on the next pass). Its session rows equal `SELECT COUNT(*) FROM sessions WHERE pedestal_id=1 AND status='completed' AND substr(started_at,1,7)='2026-10'` | No `monthly reports:` line at all = the job does not run: report it. An October file with fewer rows than that count, or empty while the count is not 0 = **the fix did not work** | ☐ |

## 13.10 R1 — last, and the only check that decides Krk

| # | Check | Command / step | Expected | If it fails | Outcome |
|---|---|---|---|---|---|
| 21 | Still ready | P.1 still holds: the same `socket_configs` query, and smart mode on | Every socket `0`; smart mode on | STOP | ☐ |
| 22 | Physical meter before | Read Q1's physical meter | Reading noted | — | ☐ |
| 23 | Scan | `/scan` as in 13 with `"outlet":"Q1","erp_ref":"R1-TEST-1"` | `pending` | STOP | ☐ |
| 24 | Plug in within 5 minutes | Plug into Q1; `curl -s "http://localhost/api/nfc/sessions?erp_ref=R1-TEST-1" -H "X-API-Key: $ERP_KEY"` | One `active` session carrying `erp_ref` `R1-TEST-1` | STOP — R1 fails | ☐ |
| 25 | Draw, then stop | Draw well above the meter's resolution; stop with `curl -s -X POST http://localhost/api/nfc/session/<id>/stop -H "X-API-Key: $ERP_KEY"` | Session `ended` | STOP — R1 fails | ☐ |
| 26 | The figures agree | Read Q1's physical meter again; fetch the session as in 24 | `energy_kwh` = `meter_energy_end_kwh − meter_energy_start_kwh` exactly; matches the physical meter's delta within its resolution; `consumption_source` = `register` | **R1 fails — this decides Krk** | ☐ |
| 27a | **The ledger writes again** (owner's hypothesis, 2026-10-14: it froze because no standalone session had a start register; `aa1f74f` captures it) | `sudo -u cloud-iot /opt/cloud-iot/backend/.venv/bin/python3 -c "import sqlite3;c=sqlite3.connect('file:/opt/cloud-iot/backend/pedestal.db?mode=ro',uri=True);print(c.execute('SELECT COUNT(*),ROUND(SUM(kwh),4) FROM energy_intervals WHERE session_id=<id>').fetchone());print(c.execute('SELECT energy_kwh,meter_energy_start_kwh FROM sessions WHERE id=<id>').fetchone())"` (`<id>` from 24); if the count is 0: `journalctl -u cloud-iot-backend --since "<R1 start>" -o cat \| grep EnergyInterval` | Count ≥ 1 and the sum equals `energy_kwh` (to 4 decimals); `meter_energy_start_kwh` not NULL | Count 0 WITH a start register = the hypothesis is WRONG and the ledger is a defect of its own: record the "[EnergyInterval] wrote NO row…" line, which says why. Count 0 and start NULL = the capture did not run: STOP and report. Monthly: repeat on one standalone session until §4.4's condition holds | RECORD — does not decide R1 | ☐ |
| 27 | The R1 interval rows name their berth | `sudo -u cloud-iot /opt/cloud-iot/backend/.venv/bin/python3 -c "import sqlite3;c=sqlite3.connect('/opt/cloud-iot/backend/pedestal.db');print(c.execute('SELECT berth_id FROM berth_assignments WHERE pedestal_id=1 AND socket_id=1').fetchall());print(c.execute('SELECT DISTINCT berth_id FROM energy_intervals WHERE session_id=<id>').fetchall())"` (`<id>` from 24) | At least one interval row for the session (none = the ledger did not write, RECORD as unproven). If Q1 is assigned to a berth: the same `berth_id` on every row. If it is not: `[(None,)]` — not known, which is correct, but then the berth attribution is UNPROVEN at R1: RECORD it, do not count it as a pass | RECORD — does not decide R1 | ☐ |

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

- (part B — built 2026-10-12; its checks are §13.6b.)

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
| Part B (block 1, **built 2026-10-12**) | One list of identity keys — `customer_id`, `customer_name`, `nfc_user_id`, `erp_ref`. Removed for non-admin from every websocket broadcast, and from `GET /api/sessions`, usage history and reconciliation divergence. **Billing and export routes are locked to admin, not filtered:** the cabinet does not bill — the ERP does — and those routes are legacy; filtering them would mean maintaining them as if they had a purpose. **Built:** the list is `auth/identity_redaction.py` (keys removed, not nulled; a missing role fails safe to redacted); the `/ws` connection carries the operator's role; the webhook hooks still get the full message (the ERP owns the customer). Every billing route — the reads and `PUT /api/billing/config` (was `require_control`) — and `/api/admin/export/usage` are `require_admin`, with a legacy note on the router; the Billing nav item is admin-only. Proof: `test_identity_redaction.py` TC-IDR-01..06 (and 05c, the write) — every websocket event in the backend's catalogue, paired monitor/admin REST, 16 failed on the code before. Also found and fixed: `/ws` looked users up in the real `users.db`, not through `get_user_db` (TC-WSA-08, failing before). Cabinet check: §13.6b. **Follow-up, same day (owner's decision):** the Customers and Contracts pages are admin only — every operator route they call (`/api/chat/*` operator side, `/api/contracts/templates`, `/api/admin/contracts*`), reads and writes, plus the menu and the page routes. The monthly report FILES (list, download, delete) are admin only, **temporarily** — see §0.2, plan item 4. Proof: TC-IDR-07/08 (19 failed on the code before). Report delete was `require_control` under a docstring saying "ADMIN ONLY" — one more claim that was not a control. **Test isolation, found the same day:** the app's own engines were not the test databases — app code that opens `SessionLocal()` / `UserSessionLocal()` by hand reached the real `users.db` (5 tests) and a stray `./pedestal.db` (223 tests). Conftest now points the app's engines at the per-run files; `test_test_isolation.py` TC-ISO-01/02 (failed before). Cabinet check: §13.6b, 11h. **Systematic scan, same day (owner asked: "is this the last one?"):** every non-admin operator route (130 method×path), two signals — the declared `response_model` walked recursively, and a GET as a monitor over seeded data carrying identity. Result: three more routes (`/api/admin/reviews/` with name and e-mail, `/api/admin/service-orders/`, `/api/admin/berths/calendar/{id}` with `customer_id`) — locked to admin; the Calendar button is admin-only. ONE family left, **awaiting the owner:** the action replies of `POST /api/controls/{id}/allow|deny|stop` and `/sockets/{p}/{s}/approve` return the full `SessionResponse` (`customer_id`, `nfc_user_id`, `erp_ref`) to `monitor_control`. The scan is now a test, `test_identity_route_scan.py` TC-IDR-09: a new route that gives staff a key fails the gate unless listed with a reason. Not covered, and said in the test: non-JSON bodies, and GETs that cannot answer 200 in tests (camera files, untrained model) — static signal only. |
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
