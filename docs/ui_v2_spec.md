# UI v2 — Monitoring & Control profile, specification

**Date:** 2026-09-28 · **Status:** for approval. **No UI code written.**
**Reads with:** `docs/ui_v2_audit.md` (what exists today, with evidence).

The audit found that three of the brief's eight rules cannot be satisfied in the frontend at
all — they need data and decisions that do not exist yet. This document says what to build,
in what order, and marks every point where the brief needs a **[DECIDE]** from you rather
than a guess from me.

I have not hedged with options where I have a recommendation. Where I recommend something
that differs from the brief, it is flagged as a refinement and the reasoning is given.

---

## 1. What has to exist before any screen can be built

### 1.1 The berth → socket → valve mapping  **[DECIDE 1]**

Rule 1's row is unbuildable without it (audit §1 Rule 1). Proposal:

```
berth_assignments        (pedestal.db — same DB as sockets, valves and billing)
  id
  berth_id         int   -- Berth.id from users.db; plain int, no FK (cross-DB, as today)
  pedestal_id      int   FK pedestals.id
  socket_id        int   NULL  -- 1..4, the electricity socket serving this berth
  valve_id         int   NULL  -- 1..2, the water valve serving this berth
  assigned_at      datetime
  assigned_by      str
  UNIQUE (pedestal_id, socket_id)   -- a socket serves at most one berth
  UNIQUE (berth_id)                 -- a berth has at most one assignment
```

Four deliberate choices:

- **It lives in `pedestal.db`, not `users.db`.** Sockets, valves and `energy_intervals` are
  all there, so the joins the dashboard needs stay inside one database. `berth_id` crosses
  the boundary as a plain int, which is exactly the compromise `Berth.pedestal_id` already
  makes (`berth_models.py:14-15`) — this adds no new kind of problem.
- **`socket_id` and `valve_id` are nullable.** A berth with power but no water is real, and
  the UI must render it rather than refuse to.
- **`UNIQUE (pedestal_id, socket_id)` but *not* `UNIQUE (pedestal_id, valve_id)`.** Two
  berths legitimately share one valve — there are 4 sockets and 2 valves per cabinet
  (`models/session.py:12`, `models/valve_config.py:24`). Forcing valve uniqueness would make
  a correct installation unrepresentable.
- **`assigned_at` / `assigned_by`.** Re-pointing a berth to a different socket is an
  installation act with billing consequences, so it is recorded. Same reasoning as the NFC
  audit-trail gap.

**[DECIDE 1]** — approve this shape, and in particular the shared-valve asymmetry.

### 1.2 Which "berth" is authoritative  **[DECIDE 2]**

Three representations exist today (audit §1 Rule 1). Recommendation:

**`Berth.berth_number` becomes what the marina sees; `PedestalConfig.berth_ref` becomes a
display-only installation label; `energy_intervals.berth_ref` is left exactly as it is.**

Reasoning: `Berth` is the only one that can express four berths on one cabinet, and it
already carries the reference photo and match state the L1 row needs. `energy_intervals` is
historical billing data — rewriting it would change past invoices, which is never worth it
for a UI change. New billing rows should additionally carry `berth_id`, so future invoices
join properly while old ones keep working.

**[DECIDE 2]** — approve, and confirm no invoice may be retroactively re-keyed.

### 1.3 One authoritative status reduction  **[DECIDE 3]**

Rules 2 and 4 and the "Needs attention" filter all sit on this. It must be computed
**server-side, once**, so the web UI and the mobile app cannot disagree about whether a
berth is fine.

`GET /api/marina/berths` returns per berth:

```json
{
  "berth_id": 12, "berth_number": 3, "dock": "A",
  "status": "ok" | "attention" | "unknown",
  "status_reason": "Water leak detected",      // plain sentence; null when ok
  "occupied": true, "occupied_known": true,
  "vessel_matches": true, "vessel_match_configured": true,
  "power": { "on": true, "watts": 1240, "available": true },
  "water": { "on": false, "litres_per_min": 0, "available": true, "shared_with": [4] },
  "light": { "on": true, "scope": "pedestal", "shared_with": [1, 2, 4] },
  "guard": { "state": "on" | "off" | "paused" | "unavailable",
             "detail": "Too dark to see", "scope": "pedestal" },
  "alarm_count": 0
}
```

**The UNKNOWN rule is the important part.** Grey means data is genuinely missing, and this
system has a specific way of producing missing data that *looks* present: a cabinet silent
for 19 days whose retained MQTT state still reads normally. So:

> A berth is **UNKNOWN** when its cabinet's last heartbeat is older than the comm-loss
> threshold, when a value has never been reported, or when smart mode is off and the NUC
> therefore does not know what the cabinet is doing. **Stale is UNKNOWN, never OK.**

This is the v3.40 lesson applied to the dashboard, and it is the one rule I would refuse to
soften: a grey row that means "we cannot see berth 3" is useful, and a green row that means
the same thing is worse than no dashboard.

**Precedence when several things are true at once** — highest wins, so the reason shown is
always the most serious:

| Order | Condition | Status | Sentence shown |
|---|---|---|---|
| 1 | cabinet not heard from | unknown | "No contact with this pedestal" |
| 2 | smart mode off | unknown | "This pedestal is running on its own" |
| 3 | water leak / moisture alarm | attention | "Water leak detected" |
| 4 | overheating | attention | "Pedestal too hot" |
| 5 | power cut off automatically | attention | "Power switched off automatically — too much load" |
| 6 | breaker tripped | attention | "Power tripped — needs resetting" |
| 7 | guard alarm unreviewed | attention | "Someone was seen — needs checking" |
| 8 | vessel does not match photo | attention | "Vessel does not match the photo" |
| 9 | everything else | ok | — |

**[DECIDE 3]** — approve the precedence order and the sentences. These become the only
marina-facing strings for these conditions; §2 explains why that matters.

### 1.4 Smart mode tightened to admin

`backend/app/routers/pedestal_config.py:340`: `require_control` → `require_admin`. Backend
enforcement, per the brief. No UI change can substitute for it.

This belongs in the **same consolidated access-control change** as the NFC Rule 1 fix, not
in the UI work: it is the identical defect shape (a control-tier dependency on what is
really an installation act), and the role tests should be rewritten once to encode both new
rules rather than twice.

---

## 2. The rules made structural

The audit's finding on Rule 3 was that the compliant cases were compliant by accident. So
each rule gets a mechanism, not a review note.

| Rule | Mechanism |
|---|---|
| 3 — colour + icon + word | One `<Status>` component whose props make all three **required**. No raw colour class in any marina-profile file; a lint rule denies `text-red-*` / `text-green-*` / `bg-*-900` in `pages/marina/**`. |
| 4 — plain language | The only strings allowed are §1.3's table, kept in one module. Any condition without an entry cannot be rendered — it becomes UNKNOWN with "Something needs checking", which is honest and forces the entry to be added. |
| 2 — two states | The frontend never computes status; it renders `status` from the API. Nothing to drift. |
| 5 — one number | The row renders exactly one figure per facility (watts, or litres/min) and nothing else. Temperature and moisture do not appear in this profile at all — they are cabinet health and belong to admin. |
| 6 — no greyed controls | `available: false` renders **one sentence and no control element in the DOM**. Not `disabled`, not `pointer-events-none` — absent. |
| 7 — three levels | Router-level: the marina profile has exactly three route depths and no overlay may open another overlay. |
| 8 — phone first | Every marina view is built narrow-first and must pass at 360 px with no horizontal page scroll. |

**On Rule 4 and guard specifically** — the brief allows four guard strings. The backend has
more states, so the mapping is fixed here and written once:

| Backend | Marina sees |
|---|---|
| `ARMED`, `ALARM`, `RECORDING` | **Guard on** |
| `OFF` | **Guard off** |
| `SUSPENDED_CPU`, `NO_DISK`, stalled ring | **Guard paused** + plain reason |
| `limited_visibility` flag while armed | **Guard paused — too dark to see** |
| `ARMING` | **Guard on** (with a brief "starting…") |
| `UNAVAILABLE` | **Guard unavailable** |

`UNAVAILABLE` must never render as "Guard off". Off is a decision someone made; unavailable
is a fault. The entire liveness design (LWT + heartbeat + in-memory `worker_seen_at`) exists
to keep those apart, and collapsing them in the UI would throw that away at the last step.

---

## 3. Screens

### Level 1 — Dashboard, one row per berth

Per row: berth number · dock · status word+icon · occupied · vessel matches photo (only
where configured) · power on/off + watts · water on/off + litres/min · light on/off · guard
on/off. Filters: **Needs attention** / **All**. One alarm indicator with a count. Nothing
else.

Sort order: **needs-attention first, then unknown, then by berth number.** The rows that
need someone are at the top on a phone without scrolling — which is the whole point of the
screen.

**Shared facilities — refinement, flagged per the brief.** Light is one LED per cabinet
(`models/pedestal_config.py:led_on`) and guard is one camera per pedestal. Four berth rows
on one cabinet are therefore four views of one switch. Rendering four independent-looking
toggles would be a quiet lie of exactly the kind these rules exist to prevent.

Recommendation: keep the control on the row, and label the truth — `shared_with` is already
in the payload, so the row reads **"Light (also berths 1, 2, 4)"** and, on tap, confirms
*"This light covers berths 1, 2, 3 and 4. Turn it off for all of them?"* One confirm, plain
words, no hidden surprise. When a cabinet serves one berth, `shared_with` is empty and none
of this renders. **[DECIDE 4]** — approve, or say you would rather these move to berth
detail and off the L1 row.

### Level 2 — Berth detail

Pedestal image with colour-coded status as today, consumption history, alarm history, the
reference photo, the current camera view, and the guard event list for this berth. Per guard
event: time, annotated frame, recording, and the **correct / false alarm** control —
`require_any_role`, so it is available to whoever is actually looking
(`docs/guard_b1_design.md §13`).

One honest label needed here: guard events are per **camera**, i.e. per pedestal, so on a
multi-berth cabinet the list is the cabinet's events, not that berth's. It says so.

### Level 2 — Alarms

Flat list, newest first, filterable by pedestal and by berth. Plain sentences from §1.3 —
never error codes. What happened, where, when, still active or not.

**This needs a backend change, not just a page.** `ActiveAlarmsPanel` renders only inside
`SystemHealth`, which is `adminOnly` (`App.tsx:76-83`), so the marina cannot see a
cross-berth alarm list today. A marina-scoped endpoint is required — and it should be
marina-scoped rather than the admin one re-gated, so that admin diagnostics detail does not
leak into this profile by default.

### Level 3 — Analytics

Reached only from a berth or from a consumption figure. **Removed from the nav**
(`Layout.tsx:42`). The existing `Analytics` page can be reused behind a berth filter; it
does not need rebuilding.

### Control Panel — 3-step wizard, run once per pedestal

1. Which dock this pedestal serves.
2. Which berth numbers it controls — **and which socket and which valve serves each.**
3. Per berth: upload the vessel reference photo, enable/disable "Berth occupancy and match".

**Step 2 is the refinement from the audit.** As the brief writes it, step 2 captures only
*which* berths; without socket and valve per berth the L1 row cannot render power or water
at all. The wizard is the natural place to capture it because it is the one moment when
someone is physically at the cabinet and can see which outlet serves which boat.

Smart mode does **not** appear in this wizard, and after §1.4 the endpoint refuses the role
regardless — enforced in the backend, not hidden in the UI.

---

## 4. Tests — the boot gate, before any component test

Per the standing instruction that a component suite passing while the app does not boot is
the same failure in a different place, the marina profile gets a boot smoke test **first**,
and it must be unskippable.

The audit found the existing gate is not: `tests/playwright_e2e.sh:41-45` exits 0 when the
backend is not on `:8000`, so on the last push that stage reported success while running
nothing.

Required, in order:

1. **`TC-UIB-01` — the app boots.** Real browser, real built bundle: load the marina
   dashboard, assert it renders berth rows and no error boundary, and assert the console
   produced no uncaught error. This must fail if the bundle does not build, if a route is
   broken, or if the API shape changed.
2. **Fix the silent skip.** The E2E stage must either start the backend itself or **fail**,
   never exit 0 having run nothing. If a fixture backend is too heavy for every push, then
   run `TC-UIB-01` against a stubbed API so that *something* always answers the boot
   question — and print the skip count either way, as `run_tests.sh` now does for pytest.
3. **`TC-UIR-01..08` — one test per non-negotiable rule**, asserting the mechanism rather
   than an instance:
   - no raw colour class in `pages/marina/**` (Rule 3);
   - every rendered condition has a string-table entry (Rule 4);
   - `available: false` renders **no** control element in the DOM (Rule 6) — asserted by
     querying for the element and expecting absence, not by checking `disabled`;
   - no page-level horizontal scroll at 360 px (Rule 8);
   - status is never computed client-side (Rule 2) — the reduction is only ever read.
4. **`TC-UIS-01` — stale is UNKNOWN.** Given a cabinet whose last heartbeat is older than
   the threshold but whose retained state reads normal, the berth renders grey. This is the
   v3.40 regression written as a UI test, and it is the one I would most expect to break
   later.

---

## 5. Build order

Each step ends somewhere real, so work can stop between steps without leaving a half-built
dashboard in front of the marina.

| # | Step | Ends with |
|---|---|---|
| 1 | `berth_assignments` + `GET /api/marina/berths` + the reduction (§1.1, §1.3) | the contract answerable with `curl`, no UI |
| 2 | Smart mode → admin (§1.4) — *in the access-control change, not here* | role tests rewritten to encode the rule |
| 3 | `TC-UIB-01` + fix the silent E2E skip (§4.1-4.2) | a gate that cannot pass vacuously |
| 4 | L1 dashboard, narrow-first, with `<Status>` and the string table | the screen the marina uses daily |
| 5 | Control Panel wizard (§3) | installation captures the mapping step 1 needs |
| 6 | L2 berth detail incl. guard events + labelling | guard gets its marina face; step 6 of Stage B discharged |
| 7 | L2 alarms + marina-scoped endpoint | alarm list visible to the marina at last |
| 8 | Analytics demoted to L3 | nav reduced |

Step 1 before step 4 matters: with the contract answerable by `curl`, the L1 screen is a
rendering job against a fixed shape. That is the same discipline that made guard's step 5
useful before it had any UI, and it is what let the operator runbook be written against
`curl` alone.

**Ordering note.** The brief's sequence is UI v2 audit and spec → access-control plan → UI
implementation → one deployment covering guard and UI. Steps 1 and 3 above are the only ones
that could start before the access-control change; step 2 belongs to it. Nothing here
touches production until that single combined deployment.

---

## 6. What I am NOT proposing

- **No rebuild of `BerthOccupancy`'s detection and matching.** The data and thresholds are
  good; only placement changes.
- **No change to the admin profile** beyond what the brief requires. Temperature, moisture,
  breakers, CPU, disk, thresholds, confidence and the detections list all stay there.
- **No new charting.** Analytics moves depth; it does not change.
- **No touching `energy_intervals`.** Historical billing stays as written.
- **No notification path.** Notifications to the marina stay off until you have watched a
  week; there is no built-and-disabled path to switch on by accident.

---

## 7. Decisions needed

| | Decision |
|---|---|
| **[DECIDE 1]** | `berth_assignments` shape (§1.1), especially the shared-valve asymmetry |
| **[DECIDE 2]** | `Berth.berth_number` authoritative; `energy_intervals` untouched (§1.2) |
| **[DECIDE 3]** | The status precedence order and its nine sentences (§1.3) |
| **[DECIDE 4]** | Shared light/guard stay on the L1 row with "also berths …" wording, or move to berth detail (§3) |

And the open questions from the audit that change what gets built:

- **How many berths does one pedestal serve at Krk in practice?** If one, [DECIDE 4] is
  moot and §1.1's asymmetry never bites. This is the single answer that would most simplify
  the work.
- **Does `Berth Occupancy` survive as a marina page** once berths are the dashboard?
- **Should `data_mode: synthetic`** (`Dashboard.tsx:54`) be visible in this profile at all?
