# UI v2 — Audit of what exists today

**Date:** 2026-09-28 · **Status:** audit only. No UI code written, no UI code changed.
**Scope:** the "Monitoring and Control" profile (marina staff) — main dashboard, control
panel, and what the ERP contract exposes. The admin profile is described only where the
brief touches it.

Read this the way the NFC audit was read: for each rule, **how it works today**, **whether
it meets the rule**, and **what must change**. The spec (`docs/ui_v2_spec.md`) comes after
it and is where proposals live; this document is findings.

Every claim below carries a `file:line`. Where I could not settle something by reading, it
is in §8 as an open question rather than stated as fact.

---

## 0. Method, and what this audit does NOT cover

I read the frontend and the backend it calls. I did **not** run the UI on a phone, and two
of the eight rules (depth-in-practice, and sunlight readability) cannot be settled by
reading — they need a device on the pier. Those are named in §8 rather than guessed at.

Counting note used throughout: there are 48 `.tsx` files and 1,919 `className=`
occurrences in `frontend/src`. Where I quote a ratio, that is the denominator.

---

## 1. Rule-by-rule findings

### Rule 1 — organised by BERTH, one row per berth

**How it works today.** The dashboard is organised by **pedestal**, not berth, and it is a
card grid rather than rows. `Dashboard.tsx:63-67` switches between `PedestalGrid` and
`PedestalView` on `selectedPedestalId`; `PedestalGrid.tsx:43-51` renders one
`PedestalCard` per pedestal. The subtitle states the model outright: *"Select a pedestal to
manage sessions"* (`Dashboard.tsx:52`).

Berths do exist, but as a **separate page** — `Berth Occupancy` is its own top-level nav
item (`Layout.tsx:47`) pointing at `BerthOccupancy.tsx` (1,154 lines), which covers vessel
detection and photo matching and nothing about power, water or light.

**Does it meet the rule.** No. This is the largest single change in UI v2: not a restyle but
a different organising axis, and the two halves of the information the brief wants on one
row currently live on two different pages that share no component.

**What must change — and the blocker underneath it.** There is **no berth → socket
mapping**, and without one a per-berth row cannot say "power on":

- `Berth` (`backend/app/auth/berth_models.py:9-53`) has `pedestal_id` — a plain int,
  deliberately no FK, because `Berth` lives in `users.db` while `Pedestal` lives in
  `pedestal.db` (`berth_models.py:14-15`). So a berth knows its *cabinet*, not its socket.
- A pedestal has **4 electricity sockets and 2 water valves** (`models/session.py:12`,
  `models/valve_config.py:24`). A cabinet serving four berths therefore has one socket per
  berth but only one valve per *two* berths.
- So `berth → pedestal` is not enough. The row needs `berth → socket` and
  `berth → valve`, and neither exists anywhere in the schema.

The brief already anticipates this in Control Panel step 2 ("which berth numbers it
controls"), but as written step 2 captures only *which* berths, not which socket and valve
serves each. **That is a refinement the spec must make explicit rather than silently** — it
is the difference between a wizard that produces a renderable dashboard and one that does
not.

**Second blocker: "berth" currently has three representations.**

| Representation | Where | Shape |
|---|---|---|
| `Berth` row | `users.db`, `berth_models.py:9` | entity with `berth_number`, reservations, reference image, ML match state |
| `PedestalConfig.berth_ref` | `pedestal.db`, `models/pedestal_config.py:15` | **free-text string**, one per pedestal |
| `EnergyInterval.berth_ref` | `pedestal.db`, `models/energy_interval.py:39` | free-text copy, stamped per billing interval |

Two of the three are strings, one per *pedestal* — which cannot express four berths on one
cabinet. Billing already depends on the string form (`energy_interval.berth_ref`), so this
cannot simply be deleted. The spec has to say which one becomes authoritative and what
happens to the other two, because a dashboard keyed on the wrong one will disagree with
the invoices.

### Rule 2 — two states only (OK / NEEDS ATTENTION), plus UNKNOWN when data is missing

**How it works today.** Many more than two, and they are per-socket rather than per-berth.
`PedestalCard.tsx:271` distinguishes three socket states (active / pending / neither);
`PedestalControlCenter.tsx:49` has a `StateBadge` component taking an open `state: string`;
the session machine itself has pending / active / completed / denied, and
`PedestalConfig.status` adds online / offline. Sensor values are shown as raw numbers with
alarm styling (`PedestalCard.tsx:98-105`).

**Does it meet the rule.** No, and the gap is conceptual rather than cosmetic. There is
currently **no function anywhere that reduces a berth's many facts to one of two words.**
Today's UI renders each underlying fact directly, so the reduction does not exist to be
restyled — it has to be written, and it is a backend concern as much as a frontend one
(two clients must not reduce the same facts differently).

**What must change.** A single authoritative reduction, computed once. The spec must state
its inputs and, more importantly, its **UNKNOWN rule**: the brief allows grey only when
data is *genuinely missing*, and this system has a specific way of producing
missing-but-looks-present data — a cabinet silent for 19 days whose retained MQTT state
still reads normally (the v3.40 lesson). So "stale" must map to UNKNOWN, not to OK.

### Rule 3 — colour is never alone: colour + icon + word

**How it works today.** Mixed, with one clear breach.

- **Breach, colour only.** `PedestalCard.tsx:270-271`: `socketFill` returns `'#22c55e'` /
  `'#f59e0b'` / `'#374151'` and those fills are the *only* carrier of socket state on four
  SVG circles (`:285-288`). No icon, no word, no `aria-label`. A colour-blind user, or
  anyone in sunlight, cannot read this at all.
- **Partial.** `PedestalCard.tsx:305` — `className={ok ? 'text-green-400' : 'text-red-400'}`
  around a text label: colour + word, no icon.
- **Partial.** `PedestalGrid.tsx:30-32` — the fleet Pending/Active/Total figures are
  distinguished by colour plus a word, no icon.
- **Compliant.** `PedestalCard.tsx:99,104` — `🌡️ {value}°C` and `💧 {value}%` carry an
  icon, and append `⚠` on alarm.

**Does it meet the rule.** No. One outright breach on the most-looked-at element, and the
compliant cases are compliant by accident rather than by a shared component.

**What must change.** The rule needs to be structurally unbreakable, not a review note. One
status component that *cannot be constructed without* all three of colour, icon and word —
because a convention that lives in reviewers' heads is how `socketFill` got written in the
first place.

### Rule 4 — plain language only

**How it works today.** Technical vocabulary is pervasive and reaches the marina profile.
Non-exhaustive, from the operator-visible surface only:

| Where | Wording |
|---|---|
| `Dashboard.tsx:52` | "Select a pedestal to manage sessions" |
| `Dashboard.tsx:51-56` | "Mode: synthetic / real" (`data_mode`) |
| `PedestalGrid.tsx:26-27` | "Fleet Overview", "N Pedestals monitored" |
| `PedestalCard.tsx:214-215` | "QR Codes", cabinet id in `font-mono` |
| `PedestalCard.tsx:167` | "remotely reset the circuit breaker on socket Q{n}" |
| `Layout.tsx:111-112` | "Socket auto-stopped — overload alarm pending acknowledgment", "HW {level} alarm active" |
| `PedestalControlCenter.tsx:314,634` | tooltip "Standalone — Opta in control" |

"Opta", "socket Q3", "HW alarm", "synthetic mode" and "fleet" are all engineer words. The
last one is notable: the nav badge tooltip is the *first* thing a member of staff sees when
something is wrong, and it is currently the most technical string in the profile.

**Does it meet the rule.** No.

**What must change.** A vocabulary table in the spec — one agreed marina-facing phrase per
underlying condition — and the reduction from Rule 2 as the only thing allowed to choose
between them. Ad-hoc strings at call sites are what produced the table above.

### Rule 5 — one number per row at most, large, with its unit

**How it works today.** The fleet bar shows **three** numbers side by side
(`PedestalGrid.tsx:30-32`). A pedestal card shows temperature in °C and moisture in %
(`PedestalCard.tsx:99,104`) plus per-socket counts (`:326-333`). So the current top level
shows on the order of five numbers before a berth is even opened — and none of them is a
berth's consumption or flow, which are the two the brief actually asks for.

**Does it meet the rule.** No, twice over: too many numbers, and the wrong ones.

**What must change.** The numbers the brief wants (consumption per berth, flow per berth)
are per-socket and per-valve in the data, so they are reachable — but only through the
berth→socket / berth→valve mapping from Rule 1. Temperature and moisture are cabinet
health, not berth state, and belong in the admin profile.

### Rule 6 — smart mode off: controls NOT rendered, one plain sentence instead. Never a disabled greyed-out control

**How it works today.** Precisely the forbidden pattern, in two places:

```
PedestalControlCenter.tsx:280   <div className={!smartMode ? 'opacity-50 pointer-events-none select-none' : undefined}>
PedestalControlCenter.tsx:606   <div className={!smartMode ? 'opacity-50 pointer-events-none select-none' : undefined}>
```

plus `disabled={… || !smartMode}` on each individual control
(`:295, :311, :320, :621, :631, :639`) and a tooltip explaining the greyness
(`:314, :634`).

**Does it meet the rule.** No. This is the rule the current code contradicts most directly:
greyed-out, pointer-events-none, with a technical tooltip.

**What must change.** Render nothing, and say one sentence. Worth noting *why* the rule is
right here and not merely tidier: `pointer-events-none` is a styling opinion, so the
control is still in the DOM and still focusable by keyboard in some browsers. "Hidden" and
"cannot be actuated" are different properties, and the brief's version is the one that is
actually true.

### Rule 6b — the marina must NOT be able to enable or disable smart mode; enforce in the BACKEND

**This is a backend defect, and it is the same shape as the NFC Rule 1 defect.**

```
backend/app/routers/pedestal_config.py:335   @router.post("/api/pedestals/{cabinet_id}/smartmode")
backend/app/routers/pedestal_config.py:340       _user = Depends(require_control),
```

`require_control` admits `_CONTROL_ROLES = {admin, monitor_control, monitor_control_api}`.
So **a `monitor_control` operator — marina staff — can turn smart mode on or off today.**
The brief requires this to be impossible and enforced in the backend.

Three consequences, the third narrower than I first assumed:

1. It is not hypothetical. Smart mode OFF makes the cabinet ignore the NUC entirely
   (`models/pedestal_config.py:85-88`), so this endpoint is the single most consequential
   write in the marina profile, and it is currently the same tier as switching a socket.
2. Rule 6 and Rule 6b interact badly right now. With smart mode off, today's UI greys the
   controls out — and the control that *turns smart mode back on* is reachable by the same
   role. So marina staff can put a cabinet into a state where the dashboard appears broken,
   and the brief's intent is that they cannot get there at all.
3. **ERP cannot reach this endpoint through the gateway.** I checked:
   `smartmode` does not appear in `backend/app/services/api_catalog.py`, and the gateway
   only proxies catalogued endpoints, so it is not on the enabled-endpoint allowlist and
   cannot be put on it without a catalog entry. The NFC concern does **not** transfer here.
   What remains is narrower but real: `monitor_control_api` is in `_CONTROL_ROLES`, so an
   account holding that role and calling `/api/pedestals/{id}/smartmode` **directly** — not
   via the gateway — would be admitted today. Tightening to `require_admin` closes both the
   marina path and that one.

### Rule 7 — maximum three levels of depth, back always visible, no modal inside a modal

**How it works today.** There are **14 components containing a `fixed inset-0` overlay**
across `frontend/src`. Back is visible at level 2 (`Dashboard.tsx:37-44`).

On modal-inside-modal I have to be precise, because the obvious reading of the file list is
wrong. I checked the one case that looked like a breach — `SocketBreakerPanel` renders
`BreakerHistoryModal` (`SocketBreakerPanel.tsx:192-198`) and also contains an overlay of
its own (`:162-190`) — and they are **siblings inside a fragment**, not nested. So I am
**not** reporting a confirmed modal-in-modal.

What I can report is the depth chain: Dashboard grid → `PedestalView` → (control center
rendered *inline* at `PedestalView.tsx:182`, so a long scroll rather than a level) → a
socket history or operational-alarms overlay opened from a card inside it. Counted
generously that is 3; counted as the user experiences it, the overlay is a fourth thing to
dismiss. There is also a QR overlay reachable directly from a level-1 card
(`PedestalCard.tsx:214-227`), and a *second, separate* QR modal implementation inside the
control center (`PedestalControlCenter.tsx:375-480`) — two implementations of the same
thing.

**Does it meet the rule.** Undetermined by reading; see §8. The duplicate QR modal is a
finding regardless.

### Rule 8 — phone and tablet first

**How it works today.** Desktop-first, and the measurement is not close:

- **25 responsive utilities** (`sm:` / `md:` / `lg:` / `xl:`) against **1,919**
  `className=` occurrences — 1.3 %.
- **8 of 48 `.tsx` files** contain any responsive class at all.
- **9 `overflow-x-auto`** containers — content that does not fit a narrow screen and
  scrolls sideways instead.
- There *is* a mobile drawer (`Layout.tsx:166`, `aria-label="Open menu"`) and the pedestal
  grid does reflow (`PedestalGrid.tsx:43`). So the shell is responsive; the content is not.

**Does it meet the rule.** No. The shell was built responsive and then 40 files of content
were written without it.

**What must change.** Stated as a build rule in the spec, not an aspiration — and it
follows from Rule 1 anyway: a berth *row* is a much better fit for a narrow screen than
today's dense card, so the two changes reinforce each other.

---

## 2. Screen map — brief versus today

| Brief | Today | Gap |
|---|---|---|
| L1 main dashboard, one row per berth | pedestal card grid (`PedestalGrid.tsx`) | different axis; needs berth→socket mapping |
| L1: power on/off + consumption | per socket, inside L2 control center | reachable, needs mapping + surfacing |
| L1: water on/off + flow | per valve (2 per cabinet), inside L2 | reachable, needs mapping; 2 valves ≠ 4 berths |
| L1: light on/off, **always available** | `LedControl` (`PedestalControlCenter.tsx:747`), **one LED per cabinet** | granularity mismatch — see below |
| L1: guard on/off | **nothing in the frontend** | build; API exists from Stage B |
| L1: vessel matches photo | exists, on a separate page (`BerthOccupancy.tsx`) | move onto the row |
| L1: filters "Needs attention" / "All" | none | build; depends on Rule 2 reduction |
| L1: one alarm indicator with a count | nav badges only, technical wording (`Layout.tsx:111-112`) | build |
| L2 berth detail | `PedestalView` — pedestal detail, not berth | re-key to berth |
| L2 alarms, flat list, plain sentences | `ActiveAlarmsPanel` — **admin-only**, see below | build for marina |
| L3 analytics, reached only from a berth | **top-level nav item** (`Layout.tsx:42`) | demote |
| Control panel, 3-step wizard | does not exist; `Settings` is `adminOnly` (`App.tsx:64-69`) | build |

**Light and guard are per-cabinet, not per-berth.** One white LED per cabinet
(`models/pedestal_config.py:led_on`) and one camera per pedestal (guard's `camera_id` is
the pedestal id). So "light on/off" and "guard on/off" on four berth rows of the same
cabinet are **four views of one switch**. The brief's Rule 1 lists them per row; the spec
must say honestly what happens when a member of staff turns the light off on berth 3 and it
also goes off on berths 1, 2 and 4. Rendering four independent-looking toggles over one
device would be the kind of quiet lie the rest of these rules exist to prevent.

**The marina cannot see the alarm list today.** `ActiveAlarmsPanel` is rendered in exactly
one place — `SystemHealth.tsx:269` — and `/system-health` is `adminOnly`
(`App.tsx:76-83`), with the nav item itself gated (`Layout.tsx:48-50`). Marina staff can
reach *per-socket* operational alarms through a modal inside the pedestal view, but there is
no cross-berth list. So the L1 indicator and L2 alarms screen are not a restyling job: the
data is currently behind an admin gate.

---

## 3. Guard in this UI

Confirmed: **no guard UI exists.** The two frontend files matching "guard" are false
positives (the English word). This is expected — step 6 was cancelled and merged here — and
it means guard's marina-facing face is a clean build against the step-5 contract, with
nothing to unpick.

The contract is complete for what the brief asks: state, per-alarm annotated frame,
recording, and correct/false-alarm marking, plus the detections list and config PATCH that
stay in the admin profile. Two points the spec must carry:

- The brief allows four strings only: "Guard on" / "Guard off" / "Guard paused — too dark
  to see" / "Guard unavailable". The backend has more states than that
  (`ARMING`, `ALARM`, `RECORDING`, `SUSPENDED_CPU`, `NO_DISK`, stalled-ring flags), so the
  mapping is many-to-four and must be written down once. In particular `UNAVAILABLE` must
  never render as "Guard off" — off is a decision someone made, unavailable is a fault, and
  the whole liveness design exists to keep them apart.
- Labelling is `require_any_role` by deliberate decision
  (`docs/guard_b1_design.md §13`), so the correct/false control belongs in this profile.
  Arming is `require_control`, so the on/off toggle does not appear for a plain `monitor`.

---

## 4. Backend changes this audit implies

The brief says UI v2 is documents-then-frontend, but three of its rules cannot be satisfied
in the frontend at all:

1. **`berth → socket` and `berth → valve` mapping** — new, nothing equivalent exists. Rule 1
   is unbuildable without it.
2. **Smart mode tightened to admin** (`pedestal_config.py:340`) — currently
   `require_control`. Backend enforcement, per the brief.
3. **One authoritative OK / NEEDS ATTENTION / UNKNOWN reduction**, computed server-side so
   the web UI and the mobile app cannot disagree about whether a berth is fine.

And one that is a decision rather than code: **which of the three "berth" representations
is authoritative**, given billing already writes `energy_interval.berth_ref`.

---

## 5. A structural risk this audit should name

The last review point applies directly here: *a component test suite that passes while the
app does not boot would be the same failure in a different place.*

Today's frontend has four Playwright specs (`frontend/e2e/`: auth, dashboard, sessions,
breaker), and the pre-push gate runs them — but `tests/playwright_e2e.sh:41-45` **skips
silently with exit 0** when the backend is not reachable on `:8000`. On this dev box the
backend was not running during the last push, so that stage contributed nothing while
reporting success. That is the same shape as the guard gap: a green gate over an unanswered
question.

This belongs in the spec as a requirement, not a note.

---

## 6. What is already right and should not be rebuilt

Worth stating so the spec does not throw away working parts:

- the responsive **shell** — drawer, theme toggle, nav (`Layout.tsx`);
- WebSocket live updates and the event-catalog drift guard, which already prevents a
  backend event from existing without a frontend handler;
- vessel detection and photo matching, including reference images and thresholds
  (`BerthOccupancy.tsx`, `routers/berths.py`) — the *data* for "vessel matches photo" is
  there and good, only its placement changes;
- per-socket consumption and per-valve flow already exist and are already persisted for
  billing;
- role plumbing (`ProtectedRoute`, `require_*`) is sound as a mechanism — Rule 6b is one
  endpoint using the wrong tier, not a broken system.

---

## 7. Severity, ordered

| # | Finding | Why it ranks here |
|---|---|---|
| 1 | No `berth → socket` / `berth → valve` mapping | Rule 1 is unbuildable; every other L1 rule depends on it |
| 2 | Smart mode is `require_control` (`pedestal_config.py:340`) | live authorisation defect: marina staff can disable NUC control today (not reachable via the ERP gateway — see Rule 6b) |
| 3 | No OK / NEEDS ATTENTION reduction exists | Rules 2, 4 and the "Needs attention" filter all sit on it |
| 4 | Three conflicting "berth" representations | a dashboard on the wrong one disagrees with invoices |
| 5 | Marina cannot see a cross-berth alarm list | brief's L1 indicator + L2 screen are behind an admin gate |
| 6 | Colour-only socket state (`PedestalCard.tsx:271`) | unreadable for colour-blind users and in sunlight |
| 7 | Greyed-out controls when smart mode off (`:280, :606`) | direct contradiction of Rule 6 |
| 8 | Content is desktop-first (1.3 % responsive) | staff use this walking the pier |
| 9 | Analytics is top-level (`Layout.tsx:42`) | small, one-line fix |
| 10 | E2E gate skips silently when backend is down | a green gate that answers nothing |

---

## 8. Open questions — things I did not settle by reading

Stated as questions rather than assumed, because guessing at them is how a spec acquires
wrong requirements.

1. **Depth in practice (Rule 7).** Needs a walkthrough on a device. I found no confirmed
   modal-inside-modal, but the control center being rendered inline makes "levels" genuinely
   ambiguous. Which do you count as a level?
2. **Sunlight readability (Rule 3).** Cannot be assessed by reading. The current UI is
   dark-themed by default; a dark theme in direct sun on a pontoon may be the wrong choice
   regardless of contrast ratios.
3. **How many berths does one pedestal actually serve at Krk?** If it is one berth per
   cabinet in practice, the light/guard granularity problem in §2 largely disappears and
   the mapping is simpler. If it is four, the shared-facility wording matters a lot.
4. **`data_mode: synthetic`** (`Dashboard.tsx:54`) — is the simulator something marina staff
   ever see? If yes it needs marina wording; if no it should not render in this profile.
5. **Berth Occupancy as a page** — once berths are the dashboard, does that page still exist
   for the marina, or does it fold entirely into berth detail?

(The question I expected to ask here — whether `smartmode` is on the ERP allowlist — I was
able to answer by reading, so it is a finding in Rule 6b instead: it is not catalogued, so
ERP cannot reach it through the gateway.)

---

## 9. Answer to the brief's framing

The brief said "refine, do not silently change" the screen map. The refinements I am
proposing, all surfaced above rather than buried in the spec:

1. Control Panel step 2 must capture **which socket and which valve serve each berth**, not
   only which berth numbers the pedestal controls. Without it the L1 row cannot render.
2. Light and guard are **per-cabinet facilities**, so their L1 controls need shared-facility
   wording rather than four independent-looking toggles.
3. The L2 alarms screen needs a **backend change** (or a new marina-scoped endpoint), not
   just a new page, because the list is admin-gated today.

Nothing else in the screen map needs changing that I can see. The rest is buildable as
written, once the mapping exists.
