# UI v2 — Marina Monitoring & Control profile: specification

**Date:** 2026-10-01 · **Version:** 2 (supersedes the 2026-09-28 draft) · **Status:** approved
2026-10-01; **PARTLY BUILT** since (`4eb381e` onwards). *Corrected 2026-10-12: this line said
"No UI code written", which stopped being true on 2026-10-03.* Where this text and the code
differ, the status review of 2026-10-12 lists each difference; each awaits the owner's decision
on which side is right, and until then this document is NOT updated to match the code.
**§0 records the owner's decisions of 2026-10-12 on where this text and the code differed,
and the status of every main item. §13 is the list of checks that can be run only on the
cabinet. §14 is the security model; §15 the consequences of D6.1 for the UI. §16 is the
architecture — the cabinet as an edge device, Phase 1 decided and Phase 2 to be measured (owner,
2026-10-16).**

**RULE FROM 2026-10-16 (owner), to the end of the project: the spec comes FIRST.** Nothing is
built that this document does not describe. Where it is silent or contradicts itself, work STOPS
and the owner is asked — a gap is never filled by an assumption, and nothing is built first and
written down afterwards.

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
| 8 | Live values by websocket | 15 s polling | **WS — but only AFTER part B** (role filtering, §14). *Part B built 2026-10-12, so this no longer blocks; the switch is block 4 work.* The broadcast carries `customer_id`; switching `/marina` to WS before filtering would put customer identity on the page. Polling stays until then. **Switched 2026-10-15** — see the "`/marina` on the websocket" row in §0.2 | §7 |
| 9 | New `energy_intervals` rows carry `berth_id` | Only `berth_ref` | **SPEC.** Built 2026-10-12 (block 2): NULL = not known; old rows stay NULL — see the measured reason in §6 | §6, §13.9 20a, §13.10 27. `/scan` returns it too (BREAKING for the ERP, §13.7 13a); the admin export has it as the last column |

## 0.2 Status of the main items (2026-10-12)

BUILT+PROVEN = code + a test that can fail, green. BUILT-UNPROVEN = code, nothing proves it.
Evidence is a test, a commit or a path, never a claim.

| Item | State | Evidence |
|---|---|---|
| CORE `/api/marina/berths`, berth detail, status sentences and precedence | BUILT+PROVEN | `test_marina_core.py` TC-MC-01..14, `test_marina_core_shape.py` |
| `outlet_silent` (rank 2.5) | BUILT+PROVEN on dev, cabinet fact pending | block 3, 2026-10-12: a socket is silent when the fresher of its meter telemetry (`meter_load_updated_at`, every 5 s) and its status message (`socket_states.updated_at`) is missing or older than 60 s; the power state is then `unknown`, not `idle`. `test_outlet_silent.py` TC-OS-01..05 (02/03 failed on the code before). That idle sockets really report every 5 s is checked on the cabinet: §13.6b 11i |
| Guard on `/marina` | BUILT+PROVEN on dev; **owner's decision pending** | block 3, 2026-10-12: `services/guard_state.py` reads `guard.service.effective_state` per pedestal (worst camera wins; desired ARMED + silent worker stays UNAVAILABLE). `test_marina_guard_state.py` TC-MGS-01..06 (01/02/04/05 failed on the code before — every pedestal said "unavailable"). **Decided 2026-10-16 (owner):** "No guard on this pedestal" with no row — superseded by the "Guard UI" row below |
| **Guard UI — four sentences, arm, a visible alarm, playback** (owner, 2026-10-16; second order the same day) | **BUILT+PROVEN on dev 2026-10-16; cabinet checks §13.6c F.5, F.7, F.8, 11j. Q4–Q5 and SM-Q1..Q4 open** — `test_guard_ui_phase1.py` TC-GU-01..07, 09..11, 13..16: 18 of its 24 tests failed on the old code (the other six: two grid self-checks, two controls, and the `monitor` halves that were already refused); `e2e/guard.spec.ts` TC-GU-08, 12, 13: all five failed on the old page; the TC-GU-08 non-admin half caught a mutant that renders the button for every role (the first version of that test did not — it counted before the page finished asking, fixed). TC-GAPI-08 and -17, TC-MGS-01/03/05/06 changed to the owner's decisions. `test_smart_mode_scope.py` TC-SM-01/02 pass on the old code by design; two mutants (a smart-mode check on analyze; push_image in the gateway gate) each caught | §5.5.1 S1..S4 with the 15 s boundary and the 5 s ack, the row created on the worker's announce (REST no longer creates one), the two known faults (worker restart, lost ack); §5.5.2 Arm / Switch off, admin only (button and API, two tests); §5.5.3 rank 7 and `/marina/alarms` from guard events, the legacy `unauthorized_entry` separated; §5.5.4 playback; §5.5.5 list, frame, recording, labels admin only; §5.5.6 "Not measured"; §5.5.7 TC-GU-01..16, each failing on the old code; §4.11 smart mode is consumption only (TC-SM-01/02, SM-Q1..Q4 open). When the button lands, `guard_operator_runbook.md:3-6` ("no screen, curl") is corrected in the same commit. After `main`: DOC.4 (§13.12) |
| Row controls (power, water, light) | BUILT+PROVEN on dev 2026-10-15; cabinet 11l | The server decides: each facility carries `action` (on/off/null) and ONE `unavailable_reason` — `no_socket`, `no_contact`, `standalone`, `read_only`, `state_unknown`, `nothing_plugged`, `needs_scan` (`routers/marina.py`, `Gate`/`_offer`). A control is offered only when its endpoint will accept it: "Turn on" power only for a plug waiting (`pending`; with nothing plugged the endpoint 409s), water only with a live NFC reservation (§15), read by a query that does not write. `ControlledLine.tsx`: one sentence per reason, no control element in its place; a confirm before anything that ends a session or switches the shared light ("This light covers berths 1, 2, 3 and 4…"); after a tap it says "Sent" — not "done" — and a refusal shows the server's sentence, a missing answer says it is not known whether it switched. **Two defects fixed by it:** a smart-mode pedestal out of contact said "The pedestal is switching this itself" (`unavailable_reason` was always `standalone`), and a read-only `monitor` got `available: true` for endpoints that 403 it — both shown on the old code. Proof: `test_row_controls.py` TC-RC-01..07 all failed on the old code; TC-RC-06 taps every offered action against its real endpoint (accepted) and both facility refusals (refused), so the offer cannot drift from the endpoint; mutants caught — the reservation read via `get_live_pending`, which writes (TC-RC-04); "Turn on" offered on an idle socket (TC-RC-03, TC-RC-06). `marina.spec.ts` TC-UIRC-01..04 failed on the old pages; TC-UIR-03 is no longer vacuous (TC-UIRC-01 is its positive control). The water 409 now reads as a sentence first (`controls.py`; TC-RC-07). **Open, not fixed here:** `mqtt_client.publish` drops a command when the broker is disconnected and returns nothing, so the endpoint still answers `sent` — and a `stop` completes the DB session while the socket stays on. Changing it changes what the ERP receives: the owner's decision |
| TC-UIR-01 (no raw colour classes) | BUILT+PROVEN, with exemptions | `test_ui_rule_colours.py` (block 3, 2026-10-12): no status hue (red/green/amber/yellow/orange/emerald/lime/rose on a colour utility) in `pages/marina/**`, `components/marina/**` outside `Status.tsx`, whose exported `TONE` is the only palette. Measured with that pattern: 29 lines, 2 of them in `Status.tsx` (the earlier "32" used a pattern that was not recorded). Fixed now: MarinaGuard, MarinaAlarms, MarinaWater. Exempt per file until block 4: MarinaDashboard, BerthDetail, MarinaSetup — the gate fails when block 4 is marked DONE below while any is still exempt |
| Block 4 — UI v2 remainder | DONE on dev 2026-10-15; cabinet checks 11k–11p | Row controls, L3 history, nav of 4 (Analytics already out — see the "Block 4 (part)" row below; do not redo), `<PhaseBlock>`, wizard step 3, §9 splits, `/marina` on the websocket — each has its own row. `EXEMPT_UNTIL_BLOCK_4` is empty, so TC-UIR-01c holds. **This row is the deadline of TC-UIR-01's exemptions** — `test_ui_rule_colours.py` reads it; setting it to DONE with exemptions left fails the gate |
| Card 5 (water toggle, §1.3) | NOT BUILT — checked 2026-10-16: `report_water_sessions` exists nowhere in the code | *Corrected 2026-10-16: this row said the nav was not built either; the nav IS built — row "Nav — LAST in block 4" below.* |
| **Described here, not built — the spec check of 2026-10-16** | NOT BUILT | §5.4 alarms "filterable by pedestal and by berth" (the page filters active / all only); §5.3 the reference photo and "camera now" as pictures on berth detail (it shows sentences); §3 `TC-UIR-02` "every rendered condition has a string-table entry" (no test carries that id or asserts it); §9 `TC-UIS-01` (stale cabinet reads grey) and `TC-UIR-05..07` (never written); §9 the tap count (not measured); §1 BLOCK-1, the real berths at Krk (open); §1.3 Card 5 (row above). Guard UI and the four functions: §5.5, §17 |
| L3 history | BUILT+PROVEN on dev 2026-10-15; cabinet 11m | `/marina/berth/:id/history` (the socket that serves the berth NOW — said on screen, because assignments change and sessions are per socket) and `/marina/water/:pedestal/:V1|V2/history` (water is a pool, so its history is per valve; without it, taking `/history` out of the staff nav would take water history away). One component, `ConsumptionHistory.tsx`, a calendar month (UTC, as the report) at a time; no "Later" past the current month (absent, not disabled). **Session rows, not interval rows** — the §4.4 exception, same reason and same condition as the report, so the screen and the staff report say the same thing about the same session; **Owner's decision 2026-10-15: session rows, with `consumption_source`, as the report** — the report reads the session row, so the history must too; two views of one thing from two sources drift apart and then nobody knows which is true. Every figure carries `consumption_source` and both register readings (`usage_rows` now returns them — `test_l3_history.py` TC-L3-01/02 failed on the code before; staff still get no identity); unknown or provenance-less is `—`; any unmeasured session means NO month total, only "Total not shown: N of M". `marina.spec.ts` TC-UIH-01..04 all failed on the old frontend. Found in the old `/history` (admin, untouched): a water session reads "Socket 1" for V1 — the bare-digit ambiguity §4.5 forbids |
| Row amps after the cabinet goes silent | BUILT+PROVEN on dev 2026-10-15 | `_power_block`: `amps` is null once the telemetry is older than the outlet window — the same rule as `<PhaseBlock>`. It showed the last current as now for as long as a session stayed open. `test_phase_block.py` TC-AMP-01 failed on the code before (`7.25 is None`), with a fresh-telemetry control in the same test |
| Session churn on cabinet 1 — RECORDED, NOT BUILT (owner, 2026-10-15) | OPEN — measure after the package | **Measured 2026-10-15, read-only:** sessions on pedestal 1 by start month and status: 2026-06 completed 53; 2026-08 completed 3; 2026-09 completed 84; **2026-10 completed 707**. 178 sessions in total on 2026-10-12, max id 847 on 2026-10-15 — about 670 in three days; the newest five (ids 843–847, standalone) opened and closed at 11:46, 11:57, 12:01, 12:06 and 12:16. **Owner's hypothesis, not measured:** `_METER_ACTIVE_AMPS` is 0.30 A, socket Q4 reads 0.21–0.31 A, so the current crosses the threshold and the watchdog opens and closes sessions in a loop. To measure when its turn comes: how many have `energy_kwh` < 0.05 kWh, how many last under 5 min, on which socket, and whether the threshold has hysteresis. No fix before the package |
| Nav — LAST in block 4 (owner, 2026-10-15) | BUILT+PROVEN on dev 2026-10-15; cabinet 11p | **Staff:** exactly Marina, Water, Alarms, Guard (`Layout.tsx`; §9 "nav items visible to a monitor": 7 → 4). Dashboard, History and Berth Occupancy left the staff nav (their routes still answer); history is now L3 on each berth and valve. **Admin:** what it had, plus **Setup** → new `/marina/setup` (admin only in the route): one pedestal goes straight to its wizard, several are listed. Until now nothing linked to the wizard; it was reachable only by typing the address. Marina is `end`-matched, so it is not lit on `/marina/water`. `marina.spec.ts` TC-UIN-03/04 failed on the old nav (7 items; no Setup); a mutant without `end` fails TC-UIN-03 (two items lit). TC-UIN-01's proof that the nav exists moved from History to Water. Whole e2e suite 27 passed / 33 skipped. `dashboard.spec.ts` (skipped in full, D16) monitor test updated to the new nav so it does not assert the old one when un-skipped |
| `/marina` on the websocket (block 4, decision 8) | BUILT+PROVEN on dev 2026-10-15; cabinet 11o | `components/marina/useMarinaLive.ts`, fed by `hooks/wsBus.ts` (every `/ws` message, emitted by `useWebSocket` before the store handlers). **Live by WS:** a row's amps from `meter_telemetry_received`, a valve's L/min from `water_reading`. CORE's `litres_per_min` is null by design, so until now the water line never showed a flow figure on the cabinet. A live figure follows CORE's rules: only on an outlet CORE says is in use, and only for 60 s after it arrived (`OUTLET_STALE_S`). **Structure by REST:** a session, alarm, breaker or load event re-fetches CORE once per burst (1 s debounce), since status is the server's. A STATE report re-fetches only when it differs from what CORE last said: **measured in `mqtt_handlers.py`, `socket_state_changed` is broadcast on EVERY socket status message, changed or not** (`:675`, unconditional, despite its name), and `opta_status` / `pedestal_health_updated` on every heartbeat, so reacting to each would re-fetch at the cabinet's reporting rate, the load §5 rejects. TC-UIWS-04 covers it; two mutants (re-fetch on every report; `opta_status` as a trigger) each fail it. **Polling** only as fallback: 15 s while the socket is down, 60 s while it is up. `marina.spec.ts` TC-UIWS-01..04; 01..03 failed on the old dashboard. Mutants: a 15 s poll while connected, a figure that never expires, no fallback poll when down, and no debounce each fail their own assertion. Two vacuous checks were found by a mutant and fixed: a fired poll counted before its fetch arrived, and a single 16 s step that did not reliably cross a 15 s tick. **Found on the way:** the e2e helper `mockApi` aborted `**/ws**`, a glob that also matched the module `/src/hooks/wsBus.ts`, so every admin page went blank; it is now the `/ws` endpoint only. Whole e2e suite 25 passed / 33 skipped (the skips as before) |
| `vessel_match_configured` read a column nothing writes (found building step 3, 2026-10-15) | BUILT+PROVEN on dev 2026-10-15; cabinet 11n | L1/L2 decided "matching configured" from `berths.reference_image`. No upload path writes it: the admin upload and the ERP push (`/api/ext/.../reference-image`) write FILES, the matcher (`compute_match_score`) compares against those files, and only the first-start seed sets the column (`Full_Berth.jpg`, berth 1). So a berth with no photo read "checked against a photo", and one with photos read "No reference photo is set". Now `berth_analyzer.has_reference_images` (the matcher's own files, read-only). `test_vessel_match_configured.py` TC-VMC-01/02 failed on the code before. Also: the test suite wrote into the real `backend/backgrounds` (an empty `berth_N` per test berth, 41 on the dev box; on the old code TC-VMC-02's upload wrote a real file, removed). Rule 16: `BERTH_REFS_DIR` now points it into the per-run dir, TC-ISO-03 failed on the code before |
| `<PhaseBlock>` | BUILT+PROVEN on dev 2026-10-15 | Berth detail `power.phase_amps` (`routers/marina.py`, `_phase_amps`): the three stored per-phase currents, or null — null when the cabinet sent none (single-phase), no session is running, or the telemetry is older than the outlet window; a missing phase is null, never 0. `components/marina/PhaseBlock.tsx`, "Phase 1/2/3" in words, absent from the DOM on null. `test_phase_block.py` TC-PHB-01..05 failed on the code before (no field); mutants caught: staleness check removed (TC-PHB-04), missing phase as 0 (TC-PHB-05). `marina.spec.ts` TC-UIP-01 failed on the old page. **Refresh is the page's 15 s poll until `/marina` is on the websocket (this block).** The row's `power.amps` lacked the same staleness check — fixed, row above |
| Setup wizard | BUILT+PROVEN on dev 2026-10-15 (step 3); cabinet 11n | `MarinaSetup.tsx` (`4eb381e`). **Step 3 since 2026-10-15** (`SetupPhotos.tsx`): per berth, its socket from step 2 and its reference photos (add, remove), with one sentence: "N photo(s): the boat here is checked against them" or "No photo: the boat here is not checked". **No on/off checkbox — owner's decision 2026-10-15** (removed from §5.6): matching runs exactly when a berth has a photo, and a checkbox that stores nothing is not built. Photos are stored when added; Save stays the socket mapping. `marina.spec.ts` TC-UIW-01/02 both failed on the old frontend. **Route `adminOnly` since 2026-10-15** — before that it was admin only in the backend write and nowhere else, so staff could open it by typing the address. `marina.spec.ts` TC-UIN-02: staff typing `/marina/setup/1` land on `/dashboard` with no wizard (failed on the code before: the URL stayed), admin gets the wizard (positive control) |
| §9 size limits | BUILT+PROVEN on dev 2026-10-15 — per file AND total | **Raised 2026-10-16 by the owner to 2 752 lines** with the guard UI (2 752 measured; the guard page, its review component and "Not measured" in alarms): "a measure of movement, not a budget" — nothing cut. **Owner's decision 2026-10-15: the profile total limit is the measured size with block 4 complete — 2 507 lines** (.ts and .tsx, 21 files), enforced by `test_ui_rule_colours.py` TC-UIR-10. *I first reported 2 329: that was measured at `c6eb0ec`, before the websocket and nav commits, and counted .tsx only; corrected the same day.* | **Per file:** MarinaDashboard (402 → 168), MarinaSetup (307 → 234) and BerthDetail (264 → 204) split, no behaviour change: `PedestalBlock.tsx`, `BerthRow.tsx`, `SetupSockets.tsx`, `MonthFigure.tsx`, `DetailSection.tsx`; the largest marina file is now 234 lines (MarinaSetup). `marina.spec.ts` 21/21 unchanged. The limit was only a sentence until now; `test_ui_rule_colours.py` TC-UIR-09 enforces it and failed on the code before (402 / 307 / 264). *TC-UIR-09 and TC-UIR-10 were committed as TC-UIR-02 and TC-UIR-03, ids §3 and `marina.spec.ts` already used; renamed 2026-10-16.* Their raw status colours went to `Status.tsx` `TONE` (`okText`, `done` added), so `EXEMPT_UNTIL_BLOCK_4` is EMPTY. History: the target was "under 1 200"; at `c6eb0ec` the .tsx files alone were 2 329. Splitting moves lines, it cannot remove them; the growth is block 4's own features (row controls, L3 history, wizard step 3, `<PhaseBlock>`). Superseded by the owner's decision at the start of this row |
| `match_ok_bit` "never analysed" | BUILT+PROVEN | block 3, 2026-10-12: `vessel_matches` is `false` only for a measured mismatch (`state_code` 2), `true` only for `match_ok_bit` 1, otherwise `null` = not known — never analysed, analysis failed, berth empty, no reference to compare. UI says "not known" for null. `test_vessel_match_truth.py` TC-VMT-01 (the four not-known cases failed on the code before) |
| D2 paired redaction test (HTTP) | BUILT+PROVEN | `test_identity_redaction.py` TC-IDR-03: monitor gets none of the identity keys, admin gets them (failed on the code before, 2026-10-12) |
| Block 4 (part) — Analytics out of the nav (L3); `ui_v2_audit.md` §7 #9, **NOT the owner's nalaz 9** (`retention_service.py` — fixed separately in `4a4408b`, see the Nalaz 9 row) | BUILT+PROVEN 2026-10-14 | `Layout.tsx`: no Analytics item for any role; berth detail → "This month" → "Pedestal consumption history ›" opens `/analytics?pedestal=<id>` with that pedestal preselected (`Analytics.tsx` reads `?pedestal=`). The route itself is unchanged. `marina.spec.ts` TC-UIN-01 failed on the code before (nav link count 1; no berth link). Nav is now 7 items for admin's shared part, not yet the 4 of block 4. `BerthDetail.tsx` is 253 lines, 3 over the §9 limit it already had on block 4's list |
| **Nalaz 9** — retention deleted the last evidence under a false reason (`retention_service.py`) | BUILT+PROVEN on dev 2026-10-14; cabinet check §13.9a R.6 | The docstring justified pruning `sensor_readings` with "session totals are persisted on the sessions row" — false for a session with NO figure (`consumption_source` 'unknown' or never stamped; every standalone session before `aa1f74f`), whose raw readings are its only record. Now readings of a completed session are pruned only if it has a figure with a provenance; otherwise kept. `clear_telemetry_buffer` applies the same rule. `test_retention.py` TC-RET-09 failed on the code before (all 4 readings pruned, expected 1). **Not undone:** on cabinet 1 every unmeasured session older than 7 days has already lost its readings. Conservative by design (deletes less); reversing it is one function, `_protected_session_ids` |
| Plan item 4 — the reports: new format, staff file, legacy headers | BUILT+PROVEN on dev 2026-10-14; cabinet steps §13.9a | **Owner's decision 2026-10-14:** staff get a SEPARATE file, generated on its own with no customer column (`…staff.txt`, `/usage/staff-reports`, every operator); the admin file stays locked. Figures from the session row with provenance and both register readings (§4.4 says why, and when it returns to the ledger); unknown prints `—`; a total with any unmeasured session prints NO figure ("PARTIAL — N of M not measured"); a month not over or with open sessions is PROVISIONAL and regenerated — it used to be cached forever. `test_usage_report_truth.py` TC-REP-01..08, all eight failed on the code before; TC-REP-02 also caught two deliberate mutants (sum + note on the total line; sum on its own line). The five files on the cabinet are history: `scripts/mark_legacy_reports.py` prepends a header that states, per file, PARTIAL / INCOMPLETE from the database, and keeps the body bytes and the mtime (TC-LEG-01..04). **Answered on the cabinet 2026-10-15:** 2026-05 and 2026-07 are empty (459 B) because NO session started on pedestal 1 in those months at all — the per-month query returns rows only for 06, 08, 09 and 10. The empty files are true; the old filter did not lose them. (The script's INCOMPLETE line would have said otherwise per file, §13.9a R.2.) |
| Guard integration suite — its OWN broker (owner, 2026-10-15) | BUILT+PROVEN on dev 2026-10-15; cabinet G.9 | `test_guard_integration.py` took whatever answered on `localhost:1883` first. On the dev box that is a Windows mosquitto service (`C:\Program Files\mosquitto`, installed 2026-02-09, configuration unknown to us), so **every gate until 2026-10-15 ran the guard integration suite against a broker we did not configure.** That does not overturn the results (a broker is a broker), but they were measured against something we did not set up. Now: the suite starts its own mosquitto on a free port bound to 127.0.0.1, never falls back to 1883, an external broker only when `GUARD_TEST_BROKER=host:port` names one (the NUC runbook, on purpose); the gate (`run_tests.sh`) clears that variable and sets `GUARD_INTEGRATION_REQUIRED=1`, and prints the `GUARD-INTEGRATION BROKER:` line. **Negative control, the service itself:** a subscriber to `#` on the service during a run saw **69** live camera-11 guard messages under the old fixture and **0** under the new (connected both times). TC-GINT-10 failed on the old fixture (`{'host': 'localhost', 'port': 1883, 'own': False}`); a broker that cannot start errors the run with no fallback to the listening 1883; the old `GUARD_TEST_BROKER_HOST/PORT` fail the run |
| Commit gate by file list (owner, 2026-10-16) | BUILT+PROVEN on dev 2026-10-16 (`27788bb`) | Only `.md` staged → the docs-only check (every test file naming a `.md` file: today `test_ui_rule_colours.py` — TC-UIR-01c reads this document's "Block 4" row — and `test_gate_path.py`); anything else → the full commit gate; no bypass flag. `engineering_notes.md` rule 18. Live negative control: `27788bb` (.md + .py + .sh) printed "full gate: 3 changed file(s) that are not .md" and ran 1 262 tests. This row was committed on the docs-only path |
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

*SUPERSEDED 2026-10-14 by D14 (§11): the screen IS admin-only; `require_api_config` no longer
exists. The paragraph below is the record of 2026-10-01.*

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

**CORRECTED 2026-10-16:** the claim below that `invoice_service` is not on a live path is
FALSE — every session completion calls it (§17.5 C). The owner's decision on it is open.

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

*Updated 2026-10-16 (owner, twice): §5.5.1 is the full rule — four sentences S1..S4, the 15 s
boundary, the 5 s acknowledgement — and §5.5.6 "Not measured". NOT BUILT yet; the code still says
"Guard unavailable" for no row, a dead worker and a failed read alike.*

| Backend | Marina sees |
|---|---|
| no `guard_config` row for the pedestal | **No guard on this pedestal** |
| `ARMED`, `ALARM`, `RECORDING` | **Guard on** |
| `ARMING` | **Guard on** (brief "starting…") |
| `OFF`, worker alive and reporting OFF | **Guard off** |
| `SUSPENDED_CPU`, stalled ring | **Guard paused** + plain reason (`no_disk` is a flag, not a state — `watchdog.py:50`) |
| `limited_visibility` while armed | **Guard paused — too dark to see** |
| `UNAVAILABLE`, or any desired state with the worker silent for 15 s, unacknowledged for 5 s, or reporting OFF while desired ARMED | **Guard not answering** |
| the guard state could not be read (backend exception, or the page cannot reach the backend) | **Not measured** (§5.5.6) |

**`UNAVAILABLE` must never render as "Guard off"** — and since 2026-10-16 neither may a dead
worker that was switched off. Off is a decision someone made; not answering is a fault. The entire liveness design — LWT plus heartbeat plus in-memory `worker_seen_at` —
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

**Measured on cabinet 1, 2026-10-15 (owner, read-only):** the ledger WRITES again —
`energy_intervals` 9615 rows, last `interval_end` 2026-10-15 12:19:20 — and the newest standalone
sessions carry a start register and `consumption_source='register'` (ids 843–847,
`meter_energy_start_kwh` 280.81–280.85). So `aa1f74f` restored both, measured and not only read
in the code, and the register path is proven on the cabinet. `~/Cloud_IOT` reflog: `eb8ba94`
first arrived with the pull of 2026-10-10 18:26:03 local, `aa1f74f` with that of 2026-10-11
15:48:16. **Still unexplained:** the last row before the freeze is 18:12:59 local, 13 minutes
BEFORE the pull that brought `eb8ba94`; whether the service was already stopped then is in the
journal (not yet read). The exception above stands until condition (a)+(b) holds — a ledger that
writes is (a)'s precondition, not (a).

### 4.5 Six outlets, real spellings, attribution by scanned tag
`Q1`–`Q4` and `V1`/`V2`. Never bare digits — `"1"` is ambiguous between socket 1 and valve 1.
*Corrected 2026-10-16 (D6.1, §15): there is no tag table on the cabinet; a session is attributed
by the `erp_ref` the ERP sends with `/scan`, and the ERP bills.* **The dashboard is organised by
berth for monitoring; attribution follows the ERP's `/scan`.** A
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

### 4.11 Smart mode is consumption only; the camera is security (owner, 2026-10-16)

**DECIDED (owner):** smart mode concerns consumption only — power, water, light, sockets, valves.
The camera is security. The three camera functions — berth occupancy, the boat-to-photo match, and
guard — work whatever smart mode says, locally and through the API, and are configured from their
own menus, never from the smart mode screen. Smart mode itself stays as decided: switched only from
the admin screen (`POST /api/pedestals/{cabinet_id}/smartmode`, `require_admin`,
`routers/pedestal_config.py:336-341`).

**Every smart-mode check in the code, read 2026-10-16 (`grep smart_mode` over `backend/app` and
`frontend/src`):**

| Where | What it forbids with smart mode OFF |
|---|---|
| `routers/controls.py:324-339` `_require_smart_mode`, called at `:679` and `:778` | `POST /api/controls/pedestal/{id}/socket/{Q}/cmd` and `…/water/{V}/cmd` → 409 |
| `routers/external_api_gateway.py:126-142, 169-176, 329-353` | through the gateway, every write in `_CONTROL_PEDESTAL_RESOLVER` → 409: `controls.allow/deny/stop`, `controls.socket_approve/socket_reject`, `controls.socket_cmd/water_cmd`, `controls.reset`, `controls.led`, `diagnostics.run`, `sockets.config_patch`, `valves.config_patch`, `led_schedule.upsert/delete/test` |
| `routers/ext_breaker_endpoints.py:184-193` | `POST /api/ext/…/breaker/reset` → 409 |
| `routers/nfc.py:563-564` | an NFC scan is refused |
| `services/mqtt_handlers.py:586-597` | (OFF only) clears a stale "awaiting activation" marker |
| `services/mqtt_handlers.py:609`, `:754` | adopting a live electricity / water session the cabinet reports |
| `services/mqtt_handlers.py:1289, 1323` | with ON, standalone sessions are closed and control handed back; with OFF they are tracked |
| `services/mqtt_handlers.py:1590` | socket auto-activate |
| `services/mqtt_handlers.py:1761` | valve auto-open |
| `services/mqtt_handlers.py:849-863` | not a gate: stores the value the cabinet reports (`smartMode`) |
| `routers/marina.py:464-511, 549-566`; `services/marina_status.py:138` | the row controls are not offered; the berth reads "This pedestal is running on its own" (rank 2, §3) |
| `routers/pedestal_config.py:417` | not a gate: `/api/pedestals/health` reports it |
| `frontend/…/PedestalControlCenter.tsx:277-325, 604-642` | the admin control panel greys socket and valve controls |
| `frontend/…/PedestalView.tsx:441-450`, `PedestalOverview.tsx:62-65` | admin dashboard badge "Smart Mode: ON/OFF" |
| `frontend/…/PedestalBlock.tsx:38` | the marina page's standalone line |

**The three camera functions — none is conditioned by smart mode today** (read, not assumed):
occupancy and match run through `POST /api/admin/berths/{id}/analyze` (`routers/berths.py:393`),
`services/berth_analyzer.py` (its only skip is `is_rtsp_suspended`, `:244-245`),
`GET /api/ext/pedestals/{id}/berths/occupancy` (`ext_pedestal_endpoints.py:162`) and
`POST /api/ext/…/reference-image` (`:225`); guard through `guard/router.py` and the worker. None of
these files reads `smart_mode`, and none of their ids is in the gateway's resolver, so the gateway's
gate passes them. **Nothing to remove.** Kept so by TC-SM-01.

**The other direction — consumption commands that are NOT behind the check** (for the owner, not
changed — §4.11 Q):
- **Locally (REST, the admin dashboard), with smart mode OFF these are accepted:**
  `POST /api/controls/{session}/allow`, `/deny`, `/stop` (`controls.py:176, 217, 260` — allow
  switches the outlet on), `/sockets/{p}/{s}/approve`, `/reject` (`:352, 408` — approve switches
  on), `/pedestal/{id}/led` (`:479`, light), `/pedestal/{id}/reset` (`:443`, restarts the cabinet),
  `POST /api/pedestals/{p}/sockets/{s}/breaker/reset` (`routers/breakers.py:218`). The gateway
  refuses all of them for the ERP; the dashboard does not.
- **Automatic, no check:** the LED schedule fires `opta/cmd/led` (`services/led_scheduler.py:127`);
  a plug pulled out sends stop (`mqtt_handlers.py:1887-1912`); a stale pending socket is
  auto-rejected (`mqtt_handlers.py:4160-4195`).
- **Gated although not consumption:** `diagnostics.run` through the gateway (it also checks the
  camera) — 409 for the ERP with smart mode OFF.

**Tests (owner) — BUILT 2026-10-16, `tests/backend/test_smart_mode_scope.py`:**
- **TC-SM-01** — smart mode OFF: occupancy/match (`POST /api/admin/berths/{id}/analyze`,
  `GET /api/ext/…/berths/occupancy`, `POST /api/ext/…/reference-image` through the direct route and
  through the gateway) and guard (`/api/guard/status`, enable, disable) answer as with smart mode
  ON — never 409. It fails if a smart-mode check is added to any of them: shown with a mutant that
  adds `_require_smart_mode` to the analyze route, and one that adds `berths.push_image_ext` to the
  gateway's resolver.
- **TC-SM-02** — smart mode OFF: the socket and valve commands still answer 409, locally and
  through the gateway — the existing rule, untouched (`test_direct_socket_cmd_409_when_smart_mode_off`
  and its valve twin are kept; TC-SM-02 adds the gateway path and asserts no `opta/cmd` was sent).
- **TC-SM-03** — smart mode OFF: the local commands of SM-Q3 are not refused for smart mode — the
  same answer as with smart mode ON. Fails if a smart-mode check is added (mutant: one on the
  light).
- **TC-SM-04** — smart mode OFF: `diagnostics.run` through the gateway is not 409; the valve
  auto-open after it still does nothing (the existing `test_post_diag_skips_all_valves_when_smart_mode_off`).
  Fails on the old gate.
- **TC-SM-05** — the switch: `POST /api/pedestals/{cabinet}/smartmode` 403 for `monitor_control`
  and `monitor`; no catalogue path reaches it; `pedestals.health` carries `smart_mode` through the
  gateway only when listed.

**The definition (owner, 2026-10-16, fourth message) — written because we did not have it:**
smart mode decides whether **the ERP and the automation** may manage consumption — power, water,
light, sockets, valves. It does **not** decide what staff at the cabinet may do. Smart mode off
means: the cabinet does not run itself and the ERP does not manage it — a person at the cabinet
does. **Local commands therefore work with smart mode off.** If they answered 409 the cabinet would
be unusable whenever smart mode is off — and today it is off. That the gateway refuses all those
commands while the local dashboard accepts them is not a defect: it is exactly this rule.

**Answers (owner, 2026-10-16, fourth message):**
- **SM-Q1:** admin only is the SWITCH, not the state. Using smart mode without knowing it is on
  is the danger. Staff may see the sentence that the cabinet runs on its own (§3 rank 2), with no
  control at all; only admin sees and touches the switch (today: `PedestalControlCenter.tsx:727`
  renders it for admin only, `pedestal_config.py:336-341` refuses any other role). TC-SM-05.
- **SM-Q2:** the ERP may READ smart mode through `pedestals.health`, and only when that key is in
  the gateway list; it may never change it — no catalogue id may reach
  `/api/pedestals/{cabinet}/smartmode`. TC-SM-05.
- **SM-Q3:** no — the local commands stay as they are (allow / deny / stop, socket approve /
  reject, light, cabinet reset, breaker reset, the light schedule). TC-SM-03 fails if a smart-mode
  check is added to any of them.
- **SM-Q4 — measured from the code, then decided by the owner's rule** ("if diagnostics only reads
  and measures, it leaves the smart-mode check — the ERP may always run it, like the three camera
  functions; if any of its steps switches a socket on or opens a valve, that step stays under the
  check"). What `POST /api/pedestals/{id}/diagnostics/run` does, step by step:
  1. stamps `last_diagnostic_at` (auto-activate skips the next 60 s) — `diagnostics.py:74-75`;
  2. publishes `opta/cmd/diagnostic {"cabinetId", "request": "all"}` — `:78-81`;
  3. the cabinet answers on `opta/diagnostic` with its sockets, valves, time and door, and its
     hardware config (`firmware_requirements.md:30`; the firmware source is not in this repo —
     §13.14 S.1 measures that nothing switches);
  4. `_handle_opta_diagnostic` maps it to ok/fail/missing per sensor; a plugged, idle socket is
     marked `awaiting_activation` — a marker for the dashboard, no command
     (`mqtt_handlers.py:3674-3715`);
  5. the endpoint marks the pedestal `initialized` when every reported sensor is ok — a database
     flag (`diagnostics.py:105`);
  6. for each valve that answered ok, `_maybe_auto_open_valve` starts — the ONE step that could
     open a valve. It returns early always (ERP mode, §15; `firmware_requirements.md:3`) and has
     its own smart-mode check first (`mqtt_handlers.py:1761`).
  **Decision by the rule:** steps 1–5 read and measure, so `diagnostics.run` leaves the gateway's
  smart-mode gate (out of `_CONTROL_PEDESTAL_RESOLVER`); step 6 stays under its own check, which
  is not touched. TC-SM-04.

**OPEN — the definition against what is already decided and documented (for the owner):**
- **SM-Q5:** "local commands work with smart mode off" — but the local direct socket and valve
  commands (`controls.py:679, 778`) answer 409 with smart mode off, and the owner's earlier order
  said that rule "stays untouched" (TC-SM-02). Read here as: the SM-Q3 list works, the direct
  socket/valve commands keep their 409. Confirm or correct.
- **SM-Q6:** README (v3.28, firmware v3.0.0) says that with smart mode OFF "the Opta runs
  standalone — it manages sockets itself and **ignores NUC commands**". If that holds, a local
  command with smart mode off is sent and answered "Sent" but the cabinet does nothing — the
  person at the cabinet would believe it switched. Not measured: §13.14 S.2.

**§4.11 Q — as first asked (kept for the record):**
- **SM-Q1** — "no other view sees it": does that mean the SWITCH (today only the admin control
  panel has it; `MarinaSetup.tsx:25` says so) — or also the STATE? Today the marina page shows the
  consequence ("This pedestal is running on its own", §3 rank 2), the admin dashboard shows a badge,
  and `/api/pedestals/health` — which is in the ERP's list (§16.3b) — carries `smart_mode`. My
  reading: the switch. If it is the state, §3 rank 2 changes and that touches UI 2.0.
- **SM-Q2** — "the ERP gets it only if configured as an option through the API": today there is no
  catalogue id for smart mode at all (`api_catalog.py`), so the ERP cannot switch it; it can READ it
  through `pedestals.health`. Is reading allowed, or must it become its own id?
- **SM-Q3** — the consumption commands above that the dashboard accepts with smart mode OFF: put
  them behind `_require_smart_mode` (409), as socket and valve commands are?
- **SM-Q4** — `diagnostics.run` is refused to the ERP with smart mode OFF, although it is not
  consumption: take it out of the gate?

### 4.10 The simulator — rewritten 2026-10-02
Deleted 2026-03-15. **Rewritten 2026-10-02** against `opta/*` (`a8386c0`,
`simulator/pedestal_simulator.py`), tested by `tests/backend/test_simulator.py`. *Corrected
2026-10-16: this heading said it did not exist yet.*

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

*The drawing is of 2026-10-01. Superseded in part by the decisions of 2026-10-12 (§0.1): amps,
not watts (2); water per pedestal, not per berth (1); light and guard on a pedestal strip (4).
The built screen follows the decisions, not the drawing.*

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

*The drawing is of 2026-10-01: "W" is amps since decision 2, and the berth has no water line since
decision 1 (§0.1).*

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

**Rewritten 2026-10-16 from the owner's answers. NOT BUILT — this is what gets built (§0.2 row
"Guard UI").** Until 2026-10-16 this section listed an event list, frames, recording and labels
in one sentence, said nothing of arming, and nothing of it was built: guard was operated by curl.

Per pedestal, not per berth (one camera per pedestal).

```
┌────────────────────────────────────────────────────────┐
│  ‹ Back to marina                         GUARD        │
├────────────────────────────────────────────────────────┤
│  Pedestal MAR_KRK_ORM_01        ● Guard on             │
│                                 [ Switch off ]  admin  │
│                                                        │
│  Recent                                                │
│   16 Oct 21:14   Person seen — needs checking          │
│                  [ ▶ Play recording · 42 s ]   admin   │
│                  [ Correct ]  [ False alarm ]          │
│   15 Oct 03:02   Person seen — marked false alarm      │
│                  Recording deleted after 14 days       │
└────────────────────────────────────────────────────────┘
```

### 5.5.1 The sentences — owner, 2026-10-16 (second order, "Guard UI — faza 1")

**Four sentences for four states, never one "unavailable" for all of them** (owner). Plus one
sentence that is not a guard state at all: the reading itself failed (§5.5.6).

| # | Condition (backend) — exactly one row holds | Sentence |
|---|---|---|
| S1 | No `guard_config` row for any camera of this pedestal — **the worker has never announced itself** (the row is created only by that announce, below) | **"No guard on this pedestal"** |
| S2 | A row exists, and the worker is not answering — **whatever was switched on or off**: no LIVE message from it within **15 s** (below), never heard since the backend started, Last Will received, a command not acknowledged within **5 s**, **or** desired ARMED while the worker reports OFF and no command is waiting for its acknowledgement | **"Guard not answering"** |
| S3 | A row exists, the worker answers, desired ARMED, worker reports ARMED / ALARM / RECORDING / ARMING, no acknowledgement overdue | **"Guard on"** |
| S4 | A row exists, the worker answers, desired OFF, worker reports OFF, no acknowledgement overdue | **"Guard off"** |
| S5 | A row exists, the worker answers, no acknowledgement overdue, and guard is armed but not looking: desired SUSPENDED_CPU (or the worker reports SUSPENDED_CPU); or S3 holds with `limited_visibility`; or the worker reports a state the backend has no reason for (below) | **"Guard paused — processor overloaded"** / **"Guard paused — too dark to see"** / **"Guard paused — reason not reported"**. Never "Guard paused" alone |
| S6 | A row exists, desired OFF, the worker answers and reports ARMING / ARMED / ALARM / RECORDING, no person's command waiting, no acknowledgement overdue | **"Guard recording although switched off"** — a fault, shown as one on `/marina`, `/marina/guard` and berth detail. The backend sends the switch-off ONCE; not confirmed within 5 s → S2; confirmed (worker reports OFF) → S4 |
| — | **OPEN (§5.5.8 Q4b):** desired OFF, the worker answers and reports SUSPENDED_CPU or a state the backend does not know, nothing waiting or overdue | not decided — the owner's S6 is for a worker that reports it is recording; this one is not recording and not OFF. The code keeps today's answer ("Guard off"); the grid tests list these cells as open |

**S6 — DECIDED (owner, 2026-10-16, fourth message).** The worker says plainly that it is recording,
so the truth is known and must be said. "Guard not answering" would mean nobody knows the camera
is recording — and recordings are personal data; "Guard on" would be a lie about the system,
because someone asked for off. The owner's words: "Guard snima iako je isključen"; on screen in
English, "Guard recording although switched off".
**How it differs from the restart (item 1 below), for the record:** after a restart the backend
does not know the worker's state until it confirms, so "not answering" is right; here the worker
reports its state and it differs from what was asked, so that is said aloud.
**Once:** one switch-off per episode — not again while it waits, not again after it was missed
(then S2 stands until the worker reports OFF or acknowledges a later command). TC-GU-17 fails if
S6 is ever shown as on, off or not answering, and a mutant that sends the switch-off on every
message is caught.

**S5 — DECIDED (owner, 2026-10-16, third message): a fifth sentence, the reason always in it.**
The owner's reason, for the record: a paused guard is armed and its worker is alive, but it is not
looking — neither "on" nor "off" is true. The owner gave the sentences in Croatian ("Guard
pauziran — procesor preopterećen", "— previše tamno", "— razlog nije javljen"); the screens are in
English, so the strings are the English ones in the table. **"Reason not reported"** is reachable
only through a state the backend does not know as on, off or a known pause — today `NO_DISK`, which
the worker never sends (`no_disk` is a flag, `guard_worker/watchdog.py:50`) and which the old code
rendered as "there is no space to record" (`routers/marina.py:349-351`), or any state a later
worker adds. With a dead worker, S2 wins over S5: a paused guard whose worker is gone is not
answering. *Derived, not said by the owner: a `no_disk` flag alone does not pause — detection
continues without recording (`guard/router.py:303-304`), so it stays S3.*

**Read together, and details the build needs (2026-10-16, written before the code; not new
decisions — each follows from a sentence above, and is listed so the owner can see it):**
- **A waiting command.** "While a command is waiting the sentence comes from the reported state
  alone" is for a command a person sent (the button). The automatic re-arm after a worker restart
  is the case item 1 below names: S2 until the worker confirms. The backend marks which is which
  when it sends.
- **The worker's state, from every live message that carries one.** `state`, `health` and `ack`
  each carry the worker's state (`__main__.py:334-343, 721-722`; the ack's `state`); a LIVE one of
  any of them updates the reported state. A worker that answers but has never said its state (only
  alarm or detection traffic) is S2, reason "the worker has not reported its state" — today that
  reads ARMING, i.e. "Guard on" (`guard/service.py:253`).
- **The row needs the pedestal.** A live state message without `pedestal_id` creates no row and
  logs why — the camera id is never taken for the pedestal id (today's
  `get_or_create_config` default, `guard/service.py:199`).
- **Pauses and resumes are stored in their own table** (`guard_state_events`: camera, time, kind
  `paused_cpu` / `auto_resumed`, reason), never in `guard_events` — an unlabelled `guard_events`
  row is a rank-7 alarm (§5.5.3). `GET /api/guard/events` returns both kinds merged by time, each
  row with `kind`, 50 per page. **The budget** comes from the worker: its `health` adds
  `auto_resumes_used` and `max_auto_resumes` (`watchdog.py:165-167`, the limit `:67`) — a worker
  change. The counter "Automatic resumes left today: N of 2" is shown on `/marina/guard` to every
  role (it is not a picture of anyone); the rows are in the admin list. No reading of the budget →
  "Automatic resumes left: not measured".

**The boundary for S2 — 15 seconds, measured from the last LIVE message.** The worker publishes
`health` every 5 s in every state, OFF included (`guard_worker/__main__.py:95, 719`); the backend
calls it not answering when the newest live `state`, `health` or `ack` is older than
`guard_heartbeat_timeout_s` = **15 s** (`config.py:113`) — three missed health messages. A
retained replay never counts (`guard/service.py:349-411`). An acknowledgement is overdue after
`guard_ack_timeout_s` = **5 s** (`config.py:112`). Both are `.env` values on the cabinet; these are
the defaults this spec fixes. What the operator sees lags by up to the page's 15 s refresh, so a
worker that dies is shown as not answering at most 30 s later. After a backend restart every guard
reads S2 until its worker's next health message — at most 5 s — because liveness is in memory on
purpose (`guard/service.py:120`, the v3.40 lesson).

**Exactly one sentence per state, decided in ONE function** — the backend's guard sentence
(`routers/marina.py` `_guard_block` today). `/marina`, `/marina/guard` and berth detail show its
`sentence` verbatim; the page never derives a sentence from a state of its own. Today the page has
its own `GUARD_STYLE` table keyed by state (`MarinaGuard.tsx:36`) — it keeps colour and help text
only.

**The row is created when the worker first announces itself** (owner, 2026-10-16, repeated in the
second order: "Dok reda nema, stoji prva rečenica"), desired OFF, from a LIVE state message only —
a retained replay never creates a row (the v3.40 lesson, `guard/service.py:22-31`). **The state
message does not carry `pedestal_id` today** (only the alarm does, `guard_worker/__main__.py:576,
631`; state: `:334-343`), so the worker adds `GUARD_PEDESTAL_ID` to it — a worker change, part of
this build. **Consequence, derived — the REST handlers no longer create a row:** today
`get_or_create_config` creates one on the first enable or config change (`guard/service.py:192`),
which would make S1 false for a worker that never spoke. After the build `enable / disable / rearm
/ config` on a camera with no row answer **404 "No guard on this pedestal"**. Cabinet 1 has no
guard rows (measured 2026-10-15), so nothing there changes meaning.

**Two faults already known — each fixed, each with a test that fails on the old code (§5.5.7):**

1. **After a worker restart the state is read wrongly.** A worker that restarts while guard is
   armed comes up OFF (`guard_worker/__main__.py:305-308`) and nothing sends it the arm again: the
   backend publishes a command only from the REST handlers (`guard/router.py:159, 174, 194, 252`).
   **What the old code says, read from the code:** `/api/guard/status` says `enabled: true`
   (desired ARMED), and `/marina` says "Guard off" (`effective_state` returns the worker's OFF,
   `guard/service.py:253`). Neither is the truth — the operator asked for on and nothing is
   watching. There is also a path to **"Guard on"**: the worker's `health` carries its state
   (`__main__.py:721-722`) but the backend ignores that field (`guard/service.py:413-420`), so if
   the restart announce is not received, the ARMED reported before the restart stays, live health
   keeps the worker "alive", and the page says "Guard on" for a worker that is OFF.
   **Built:** (a) when a worker announces itself LIVE reporting OFF while desired is ARMED, the
   backend sends the arm once; until the worker acknowledges and reports ARMING/ARMED the sentence
   is S2 — never S3, never S4. Desired SUSPENDED_CPU is never re-armed this way (a guard the
   watchdog suspended must not rearm itself by restarting, the same comment). (b) the state field
   of a LIVE `health` message updates the reported state too, so the backend never holds an older
   state than the worker's newest message.
2. **A lost acknowledgement stays "Guard on".** `check_overdue_acks` only rebroadcasts
   (`guard/service.py:650-665`) and `effective_state` never looks at pending commands — with a
   command unacknowledged the page keeps saying what the worker reported before. **Built:** a
   command not acknowledged within 5 s puts the camera in S2 with reason "the guard worker did not
   acknowledge", as `guard_b1_design.md:256` already specified. It stays S2 until the worker
   acknowledges a later command or reports a state that matches the desired one. While a command
   is waiting and not yet overdue, the sentence is computed from the worker's reported state alone
   and the button says "Sent" (§5.5.2) — so a tap never flashes S2 for the second an ack takes.
3. **Auto-resume after a CPU suspension — DECIDED (owner, 2026-10-16, third message), and a
   CORRECTION of the premise I gave the owner.** The rule: a LIVE state ARMED while desired is
   SUSPENDED_CPU sets desired back to ARMED and the sentence is "Guard on". The owner's reason: the
   pause was not asked for by a human but by the worker, and the worker lifted it — the last human
   wish was "on", so this returns to it; the opposite of §5.5.8 Q4, where a human asked for off.
   Only a LIVE message — a retained or replayed one never lifts a pause (the S1 rule; TC-GU-16
   fails if an old message does). Every pause and every automatic resume is written to the event
   list, and `/marina/guard` shows how many automatic resumes are left in 24 h (limit 2,
   `guard_worker/watchdog.py:65-67`) — otherwise a cabinet that keeps overloading looks healthy
   while its budget drains. Budget spent and the worker still paused: "Guard paused — processor
   overloaded", unchanged.
   **CORRECTION, read from the worker after the question was asked:** I told the owner the worker
   "resumes watching on its own and reports ARMED". It does not. The watchdog decides to resume
   (`watchdog.py:444-455`, event `resumed_cpu`, the budget spent) and sets ITS state ARMED, but the
   worker's loop acts only on `suspended_cpu` (`guard_worker/__main__.py:711-716`): capture stays
   stopped, the worker's own state stays SUSPENDED_CPU, and that is what it publishes. So today an
   automatic resume spends the budget and resumes nothing — the "budget drains silently" the owner
   named is happening already, and the decided rule above never fires. **OPEN (§5.5.8 Q5)** whether
   the worker is fixed to actually re-arm on `resumed_cpu` in this build. **DECIDED (owner,
   2026-10-16, fourth message): fix the worker**, its own commit right after the guard UI and
   before the merge — otherwise TC-GU-16 tests a path that cannot happen on the cabinet. Two
   things: (1) on `resumed_cpu` capture really restarts; (2) the budget is spent ONLY when capture
   has really started and the worker has published ARMED — the watchdog says a resume is due, the
   worker arms, and only a successful arm records it. A failed arm spends nothing, stays
   SUSPENDED_CPU, and is said in its state reason. The owner's words: a counter that claims
   something happened when it did not is exactly the defect being hunted. Tests TC-GW-01..03
   (`test_guard_worker_resume.py`) fail on the old worker.

### 5.5.2 Arm and switch off — ADMIN ONLY (owner, 2026-10-16)

One button per pedestal on `/marina/guard`: **"Arm"** when the sentence is "Guard off",
**"Switch off"** when it is "Guard on" or "Guard paused". **No button** with "No guard on this
pedestal" or "Guard not answering" — there is nothing a tap could do; the sentence stands alone
(Rule 6: absent, not disabled). After a tap the button says **"Sent"**, and the sentence follows
the worker's acknowledgement — "Guard on" appears only when the worker confirms (ARMING → ARMED);
no acknowledgement within the timeout gives "Guard not answering".

**Admin in the button AND in the API**, not only in the menu: the button renders only for admin,
and `POST /api/guard/{camera_id}/enable | disable | rearm` and `PATCH /api/guard/{camera_id}/config`
become `require_admin` (today `require_control`, `guard/router.py:146-202`), as smart mode is
backend-enforced (§4.9). *Derived from the owner's decision that control is admin only, not
stated by the owner in these words — it is what makes the decision hold for a `monitor_control`
account with curl.* The ERP's channel is §17, not this role.

**Two separate tests** (owner, second order): the route answers 403 to `monitor_control` and to
`monitor` (TC-GU-07), and the button is not rendered for them (TC-GU-08). Both fail on the old
code — the route because `require_control` lets `monitor_control` through; the button because it
does not exist, so the admin half of TC-GU-08 fails. That the non-admin half is not vacuous is
shown by a mutant that renders the button for every role.

### 5.5.3 A guard alarm is visible — owner, 2026-10-16

- **Rank 7 reads guard EVENTS directly**, not the alarm table: a pedestal with any `guard_events`
  row whose `label` is NULL gives every berth of that pedestal **"Someone was seen — needs
  checking"** (one camera per pedestal; §5.3 says the events are the cabinet's). Until now rank 7
  read `active_alarms` rows of type "guard"/"unauthorized" (`routers/marina.py:480-489, 564-571`),
  which guard never writes — dead text.
- **`/marina/alarms` lists guard events** beside the other alarms: "Someone was seen — needs
  checking" while unlabelled (active), and resolved once labelled.
- **The legacy customer alarm is separated.** `POST /api/customer/alarms/trigger` writes an
  `active_alarms` row of type `unauthorized_entry` (`customer_alarms.py:15, 45`); today that row
  turns the berth into "Someone was seen — needs checking" (`routers/marina.py:488-489`), which
  is not guard. After the build it has no entry in the §3 table, so by §3's own rule it renders
  as unknown / "Something needs checking" — never the guard sentence.

### 5.5.4 Recording playback — ADMIN ONLY (owner, 2026-10-16: recordings are personal data)

**The list (DECIDED, owner 2026-10-16, third message):** every event retention still keeps
(14 days), newest first, 50 per page; pauses and automatic resumes in the same list (§5.5.1 item 3).

Per event, admin only: **"▶ Play recording · N s"** plays the clip in the page (HTML `<video>`
from `GET /api/guard/events/{id}/video`). When there is no clip, the row says why in words:
"No recording — there was no space to record" (`video_skipped`, `no_disk`), "No recording — it
could not be assembled" (`assembly_failed`), "Recording deleted after 14 days" (410 from the
endpoint). **The API is admin too:** `GET /api/guard/events/{id}/video` becomes `require_admin`
(today `require_any_role`, `guard/router.py:288-290`) — a button hidden from staff with the file
still served to them would be the menu-only rule the owner rejected.

**Cabinet fact, not known from here:** the clip is a stream copy of the camera's own codec
(`guard_worker/capture.py:252, 313`, `-c:v copy`). If the camera sends H.265, a browser may not
play it. A §13.6c check added with the build reads the codec of the first real clip; if it is not H.264 the page offers the file as a download
instead, and that is reported to the owner, not re-encoded on the cabinet.

**Second cabinet fact: can the backend read the clip at all?** The backend runs as `cloud-iot`
and serves the file; the worker writes it as `guard`. From the code: the installer creates the
directories with the default mode (`install-guard.sh:87-94`, `mkdir -p`, then
`chown guard:guard`, no `chmod`) and the unit sets no `UMask` (`cloud-iot-guard.service:24-25`),
so directories 755 and files 644 — readable by others. **Read from the code, not measured.** The
guard docs say otherwise (`guard:cloud-iot`, mode 2750 — corrected in the docs commit). The same
§13.6c check reads it as `cloud-iot`.

### 5.5.5 DECIDED (owner, 2026-10-16) — the event list, the frame and the labels are ADMIN ONLY

The frame is a picture of a person — personal data; the owner's rule that staff do not see
customer data applies all the more to a recording of a human being. So **everything that shows
or judges what guard saw is admin only, in the page AND in the API:**
`GET /api/guard/events`, `/events/{id}/frame`, `/events/{id}/video`, `/detections`,
`/detections/{id}/frame` and `POST /events/{id}/label` become `require_admin` (today
`require_any_role`, `guard/router.py:262-405`). `GET /api/guard/status` stays any role: it holds no
picture, and staff see guard's state only as the sentence on `/marina` and `/marina/guard`.

**What staff see:** the pedestal's guard sentence, and — on `/marina` and in `/marina/alarms` —
"Someone was seen — needs checking" while an event is unlabelled (a status sentence, no picture,
no time of a person). **What admin sees on `/marina/guard`:** the sentence, Arm / Switch off, the
event list (time, "Person seen", label state), the annotated frame, the recording, and
**Correct / False alarm**. Consequence, accepted: an unlabelled event keeps its pedestal at rank 7
until an admin looks.

**Guard events never become `active_alarms` rows** — rank 7 and `/marina/alarms` read
`guard_events` directly (§5.5.3). So `GET /api/alarms/active` (catalogue id `alarms.active`, the
ERP's alarm read) carries no guard event in Phase 1: guard is the cabinet's own security function
and goes to the ERP in Phase 2 at the earliest (§17.6).

**DECIDED — notifications stay off.** Your standing instruction: off until you have watched a
week. **There is no built-and-disabled notification path** that could be switched on by
accident — the code is absent, not flagged off.

### 5.5.6 "Not measured" — never "off", never zero (owner, second order)

**A failed reading has its own sentence: "Not measured".** The backend does not ask the worker; it
listens. So silence from the worker is a measurement — S2, "Guard not answering". "Not measured" is
the other case: the reading itself did not happen —

- the backend could not compute the guard state (an exception in `_guard_block`; today that reads
  "Guard unavailable", `routers/marina.py:333-334`) → `state: "not_measured"`, sentence
  **"Not measured"**;
- the page could not reach the backend → every guard line reads **"Not measured"**, and below it
  the last reading with its time IN the sentence: **"last seen 15:42: Guard on"** (DECIDED, owner
  2026-10-16, third message — never the bare "Guard on", or an old state looks like a
  measurement). No reading since the page opened: "Not measured" alone. No button. Today the page
  keeps showing the old sentence with a banner (`MarinaGuard.tsx:114-120`), so "Guard on" can
  stand for a reading that failed;
- the event list or a count could not be read → **"Not measured"**, never "No events" and never
  `0` — on `/marina/guard`, in `/marina/alarms`, and in the nav badge.

**No guard sentence, number or button is shown from a failed reading** — no "Guard off", no 0, no
Arm / Switch off (Rule 6: absent).

### 5.5.7 Tests — each must fail on the old code (owner, second order)

Shown with the old code checked out and with a mutant per fix, as for every test since 2026-10-16.

| Id | What it asserts | Why it fails on the old code |
|---|---|---|
| TC-GU-01 | **S1 is one sentence for one state.** Over the whole grid of guard facts (row yes/no × desired OFF/ARMED/SUSPENDED × worker live/stale/never/Last Will × reported OFF/ARMING/ARMED/ALARM/RECORDING × ack none/waiting/overdue), "No guard on this pedestal" is given exactly when there is no row, and no row gives nothing else | No row gives "Guard unavailable" |
| TC-GU-02 | **S2** the same way: "Guard not answering" exactly for the S2 condition | A dead worker with desired OFF gives "Guard off"; an overdue ack with a live worker gives "Guard on" — two sentences for one state |
| TC-GU-03 | **S3** the same way: "Guard on" exactly for the S3 condition | "Guard on" also comes out with an overdue acknowledgement |
| TC-GU-04 | **S4** the same way: "Guard off" exactly for the S4 condition | "Guard off" also comes out for a dead worker switched off, and for desired ARMED reported OFF |
| TC-GU-05 | **Worker restart:** guard armed; the worker restarts and announces OFF live → an arm command is published once, the sentence is S2 until the ack, then "Guard on"; with the announce lost, a live health reporting OFF never leaves "Guard on". Control: desired SUSPENDED_CPU → no arm sent | No arm is sent; the sentence is "Guard off"; with the announce lost it is "Guard on" |
| TC-GU-06 | **Lost ack:** an arm (and, separately, a switch-off) not acknowledged within 5 s → S2 with "did not acknowledge"; an ack within 5 s → no S2 | The lost arm reads "Guard off" (the worker's OFF); the lost switch-off reads "Guard off" (desired OFF wins, `guard/service.py:240-242`) while the worker may still be watching |
| TC-GU-07 | **Route:** enable / disable / rearm / config → 403 for `monitor_control` and `monitor`, 200 for admin | `monitor_control` gets 200 |
| TC-GU-08 | **Button (e2e):** Arm / Switch off rendered for admin, not for `monitor_control` or `monitor` | No button exists (admin half fails); non-admin half proven by a mutant |
| TC-GU-09 | **Row on announce:** a live state message creates the row (desired OFF) and S1 becomes S4; a retained one does not; REST enable on a camera with no row → 404 | No row is created; REST enable creates one |
| TC-GU-10 | **Alarm from guard events (§5.5.3):** an unlabelled `guard_events` row → rank 7 on every berth of its pedestal and a row in `/marina/alarms`; labelled → resolved; a customer `unauthorized_entry` alarm does NOT give the guard sentence | Rank 7 reads `active_alarms` only; the customer alarm gives the guard sentence |
| TC-GU-11 | **Admin only, API (§5.5.5):** `/events`, `/events/{id}/frame`, `/events/{id}/video`, `/detections`, `/detections/{id}/frame`, `POST /events/{id}/label` → 403 for `monitor_control` and `monitor`; `/status` 200 for them | All are `require_any_role` |
| TC-GU-12 | **Playback and labels (e2e):** admin sees the list, plays the clip in `<video>`, marks Correct / False alarm; the three no-clip sentences; staff see neither list nor buttons | None of it exists |
| TC-GU-14 | **S5** the same way as TC-GU-01..04: each paused sentence exactly for its condition, with its reason; a paused state is never "Guard on" or "Guard off"; never "Guard paused" alone | A suspended guard whose worker died reads "paused" (must be S2); the wording is "the pedestal is busy"; `NO_DISK` has an invented reason |
| TC-GU-15 | **One state, one answer, two places (owner, third message):** in the same state — the worker-restart state first, then the whole grid — the sentence `GET /api/guard/status` gives for the camera equals the sentence `GET /api/marina/berths` gives for its pedestal, which the page renders verbatim | `/api/guard/status` has no sentence; it says `enabled: true` where the screen says "Guard off" |
| TC-GU-16 | **A pause is lifted only by a live message:** desired SUSPENDED_CPU, a LIVE state ARMED → desired ARMED, "Guard on", a resume row in the event list; the same message RETAINED → nothing changes | No rule exists; the backend keeps SUSPENDED_CPU either way (fails on the live half) |
| TC-GU-17 | **S6:** desired OFF, a LIVE state ARMED → "Guard recording although switched off", one switch-off sent; repeated live messages send no second one; no confirmation in 5 s → S2; the worker reports OFF → S4. Never "Guard on", "Guard off" or "Guard not answering" while S6 holds | The cell reads "Guard off" (Q4 kept today's answer); no switch-off is sent |
| TC-GU-13 | **Not measured (§5.5.6):** the backend's guard read raising → "Not measured"; the page with the backend unreachable → "Not measured" and no button; the event count unreadable → "Not measured", not 0 | The backend says "Guard unavailable"; the page keeps the old sentence |

The cabinet-only part — the clip's codec, and whether `cloud-iot` can read guard's files — is a
§13.6c row in the build commit (§5.5.4).

### 5.5.8 The owner's answers, and what is still open

**Answered (owner, 2026-10-16, third message):** Q1 — "Guard paused" stays as S5 with its reason
in the sentence (§5.5.1). Q2 — 14 days, newest first, 50 per page (§5.5.4). Q3 — "Not measured",
the last reading below with its time in the sentence (§5.5.6). The rest of §5.5 accepted as
written, the 15 s boundary, the 404 without a row and the TC-GU-08 mutant included. Added: TC-GU-15
(the API and the screen give the same sentence).

**OPEN:**
- **Q4 — ANSWERED 2026-10-16 (fourth message): S6**, above. **Q5 — ANSWERED: fix the worker**
  (item 3). **Q4b — OPEN:** desired OFF while the worker reports SUSPENDED_CPU or an unknown state
  (S6 covers a worker that reports it is recording; this one is not).
- *(as asked)* **Q4 — switched off, but the worker says it is watching.** Desired OFF, worker alive and
  reporting ARMED / ALARM / RECORDING / ARMING, no command waiting or overdue. Reachable: a lost
  switch-off whose overdue mark was then cleared by a backend restart (the mark is in memory).
  Proposal: "Guard not answering" (reason: it is on although it was switched off), and the backend
  sends the switch-off once — the mirror of the re-arm. *Asked 2026-10-16; the answer that came back
  was about smart mode (§4.11); the auto-resume answer calls this case "the opposite, where a human
  asked for off", which points at the proposal but does not decide it.*
- **Q5 — auto-resume does not work in the worker** (§5.5.1 item 3, the correction). Fix it in this
  build (on `resumed_cpu` the worker re-arms capture and reports ARMED, so the decided rule
  fires), or leave the worker and record that the budget is spent without effect?

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

Step 3 of 3   Per berth: the vessel reference photo(s)
              Berth 3  Q3  2 photo(s): the boat here is checked against them  [ Add photo ]
              Berth 4  Q4  No photo: the boat here is not checked             [ Add photo ]
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

**DECIDED (owner, 2026-10-15) — no matching checkbox.** Matching runs for a berth exactly when it
has a reference photo, and the UI says so per berth; a checkbox that stores nothing is not built.
(The first drawing had one; removed.)

**Owner's decision, 2026-10-15:** smart mode and configuration are set ONLY from admin screens; no other view shows them, because using them without being admin is dangerous. The wizard is therefore admin only — in the route (`App.tsx`, `adminOnly`), not just in the menu — and is not in the staff nav (§9).

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
| `<GuardBadge>` | `guard{}` | CORE, mapped per §3 | **"No guard on this pedestal"** with no row; **"Guard not answering"**, never "off", for a silent worker (§5.5.1) |
| `<AttentionFilter>` | `status`, `status_rank` | client-side over CORE | — |
| `<BerthDetail>` | one berth + EXTENDED | `GET /api/marina/berths/{id}` | back to L1 with a sentence |
| `<OutletSpec>` | `rated_amps`, `phases`, `rated_liters_per_min` | `GET /api/nfc/outlets/{cabinet}` | "Not reported by this cabinet yet" |
| `<PhaseBlock>` | `currentAmpsL1..L3` | WS `meter_telemetry` | **absent** when the payload has no per-phase keys (§4.7) |
| `<ConsumptionFigure>` | `energy_kwh` / `water_liters` + `consumption_source` | CORE | **—** with "not measured"; never `0.0` |
| `<ConsumptionHistory>` | **session rows** with `consumption_source` and both register readings — owner, 2026-10-15 (§0.2 "L3 history"; *corrected 2026-10-16, this row said interval rows*) | `GET /api/pedestals/{id}/usage/history` | "No readings yet" |
| `<VesselMatch>` | `vessel_matches`, photos | existing occupancy endpoints | hidden unless `vessel_match_configured` |
| `<AlarmList>` | marina-scoped alarms | **new** `GET /api/marina/alarms` | "No alarms" |
| `<GuardEvents>` | guard events; Arm / Switch off; playback; labels (§5.5) | `GET /api/guard/status`, `GET /api/guard/events`, `POST /api/guard/{id}/enable|disable` (admin), `GET /api/guard/events/{id}/video` (admin), `POST /api/guard/events/{id}/label` | "No events" — **NOT BUILT** |
| `<SetupWizard>` | outlets + current mapping | `GET /api/nfc/outlets/{cabinet}`, `GET/PUT /api/marina/berth-assignments` | step 2 falls back to the canonical six, with the warning |

**DECIDED — live values arrive by websocket; structure arrives by REST.**
**WHY:** the WS already carries `power_reading`, `water_reading`, `session_*` and
`socket_state_changed`. Re-fetching CORE on every telemetry tick would make the dashboard
refetch 12 times a minute per cabinet.
**IF I AM WRONG:** poll CORE on a timer; strictly worse, but one hook.

**DEPENDENCY, 2026-10-12 (decision 8) — do not skip it.** `/marina` moves to the websocket ONLY
AFTER part B (§14: the broadcast filtered by role). Today the broadcast carries `customer_id`
(e.g. `water_reading`), so switching first would put customer identity on the marina page.
Part B was built 2026-10-12 and proven on dev (§14). **The switch was made 2026-10-15**
(`useMarinaLive.ts`; §0.2 row "`/marina` on the websocket"); the cabinet proofs are §13.6b and
§13 check 11o.

**DECIDED — one new backend endpoint for the reduction, two for the rest.**
`GET /api/marina/berths`, `GET /api/marina/berths/{id}`, `GET /api/marina/alarms`, and
`GET/PUT /api/marina/berth-assignments`. Nothing else is new; everything else reuses what
exists. *Since then, also new: `GET /api/pedestals/{id}/usage/staff-reports` (2026-10-14, §0.2
plan item 4); and, specified 2026-10-16 and not built, §5.5 and §17.*

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
| Nav items visible to a marina `monitor` | **7** | **4** (Marina, Water, Alarms, Guard) — **built 2026-10-15, TC-UIN-03** — *corrected 2026-10-15: Setup is NOT staff nav, because saving the wizard is `require_admin` and a menu item staff can open but never save is a false offer; the admin nav keeps what it has, plus Setup* | `Layout.tsx:40-57` — 7 unconditional; `system-health` and `settings` are `isAdmin`, `api-gateway` is `canApi` |
| Routes defined | **16** | **+6** marina, admin routes untouched | `App.tsx`, `grep -c '<Route'` |
| Pages | **12** | 12 kept for admin, **+1** marina root | `ls pages/` |
| Numbers on one dashboard tile | **5** (temp °C, moisture %, heartbeat age, pending count, active count) | **2** on an L1 row (amps, litres/min) — *amps since 2026-10-12, decision 2* | `PedestalCard.tsx:93-135` |
| Distinct indicators on one dashboard tile | **10** (5 numbers + `data_mode` / `initialized` / `ALARM` badges + OPTA and Cam dots) | **4** (status, power, water, guard) | same |
| Largest single component | **1 468 lines, 27 `useState`** (`PedestalControlCenter`) | **no marina component over 250 lines** — *2026-10-12: the limit STAYS; split inside block 4 — done 2026-10-15, largest now 234 (TC-UIR-09)* | `wc -l`, `grep -c useState` |
| Total lines across `components/pedestal/**` | **5 075** across 16 files | marina profile adds **under 1 200**, reuses none of it — *the limit STAYS; owner, 2026-10-15: the limit is now **2 507** (the size with block 4 complete, .ts and .tsx), TC-UIR-10* | `wc -l` |
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
most 2, plus `TC-UIB-01` (the app boots) and `TC-UIR-01..08` green. *Status 2026-10-16: written
and green — TC-UIR-01 (+01c), 03, 04, 08, 09, 10; NOT written — 02, 05, 06, 07 (§0.2 "Described
here, not built").*
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
| 3 | **Simulator**, rewritten against today's contract — **DONE 2026-10-02 (`a8386c0`)** | 1–4 berths, 6 outlets, shared valve, three-phase Q1, valve state — all renderable without a trip to Krk |
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

**Status of D14–D19, updated 2026-10-16** *(this heading said "none built"; D14, D15 and D19
are built):*

| | State | Evidence |
|---|---|---|
| D14 | **BUILT+PROVEN 2026-10-14** | every `/api/admin/ext-api` route is `require_admin`; `require_api_config` and `_API_CONFIG_ROLES` deleted; route `adminOnly`, nav item in the admin group. `test_roles.py` TC-ROLE-06b reads the routes from the app (7) and failed on the code before (`monitor_control_api got 200`). Checked first: the ERP service account (`api_client`) never could reach these — it is not an operator role. `monitor_control_api` now acts as `monitor_control`; kept for existing accounts, no longer offered for new ones. **Cabinet fact not checked:** whether any account there holds `monitor_control_api` and used the page |
| D15 | **FIXED 2026-10-14 — by removal** | The call is gone, not built: a per-pedestal detections route would have had nothing real to return (synthetic mode plays a demo video; person detection is the guard's). `CameraModal.tsx` plays the video with no overlay and says no detection runs; `getCameraDetections` and its types deleted; the `KNOWN_DEAD_CALLS` entry deleted, so the allowlist is empty and TC-FEBE-01 now fails on ANY dead call |
| D16 | NOT BUILT — only skipped | `test.skip(true, …D16…)` at line 23 of four specs |
| D17 | NOT BUILT — not reproduced off the cabinet | §13 check 17 measures it |
| D18 | NOT BUILT — cabinet configuration | `external_api_admin.py` default `[]` |
| D19 | **BUILT+PROVEN 2026-10-14** | The only live display was `PedestalView.tsx:508` ("Power … W"); removed — the meter's `current_amps` is shown in the same block. `SocketCard.tsx` and `ActiveSessions.tsx` also rendered it but were imported nowhere: deleted. `test_ui_no_powerkw_watts.py` TC-UIR-04: no `.tsx` reads `.watts`; failed on the code before with all three. The backend still computes and stores `power_watts` (`mqtt_handlers.py`) — nothing renders it |

*The table below is each item's ORIGINAL description (2026-10-01/02). Its current state is the
table above — where they differ (D14, D15, D19), the table above is right.*

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

**And (owner, 2026-10-16): check 17b runs BEFORE AND AFTER every change of the API gateway
configuration** — not only after an upgrade. The configuration approved on 2026-10-14 never reached
the cabinet and nobody noticed for two days (§16.3a). A configuration change is done when 17b
after it shows it.

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
| 11j | The guard line says what the guard service says (block 3) | `sudo -u cloud-iot /opt/cloud-iot/backend/.venv/bin/python3 -c "import sqlite3;c=sqlite3.connect('/opt/cloud-iot/backend/pedestal.db');print(c.execute('SELECT camera_id,pedestal_id,desired_state FROM guard_config').fetchall())"`; then `/marina` | No rows (guard not deployed on cabinet 1): before the Guard UI build the line reads "Guard unavailable"; **after it, "No guard on this pedestal"** (§5.5.1). With rows: the line's words are the `sentence` of `/api/guard/status` for that pedestal (worst camera) — the same words, TC-GU-15 | RECORD | ☐ |
| 11k | **`<PhaseBlock>` on the real three-phase socket** (block 4, 2026-10-15) — only Q1 on cabinet 1 sends `currentAmpsL1..L3`, so only the cabinet proves the block renders from real telemetry | With a session running on Q1 (any load): open the berth assigned to Q1 at `/marina/berth/<id>`, wait ≤ 15 s; then `sudo -u cloud-iot /opt/cloud-iot/backend/.venv/bin/python3 -c "import sqlite3;c=sqlite3.connect('file:/opt/cloud-iot/backend/pedestal.db?mode=ro',uri=True);print(c.execute('SELECT meter_current_l1,meter_current_l2,meter_current_l3,meter_load_updated_at FROM socket_configs WHERE pedestal_id=1 AND socket_id=1').fetchone())"`. **Control:** the same page for a berth on Q3 or Q4 | Q1's berth shows "Phase 1 / 2 / 3" with the three values the query returns (to 2 decimals); the Q3/Q4 berth shows NO phase block. All three query values NULL while Q1 draws = the firmware does not send per-phase keys: the block is correctly absent, RECORD it | RECORD — a block on Q3/Q4, or a phase shown as 0 A where the query has NULL, is a defect: report before R1 | ☐ |
| 11l | **Row controls do what they offer** (block 4, 2026-10-15) | (a) As a `monitor` account: `/marina` → every Power, water and Light line reads "View only: your account cannot switch outlets" and has NO button. (b) As admin or `monitor_control`, nothing plugged into Q2: its berth says "Nothing is plugged in", no button. (c) Water with no scan: V1 and V2 say "Water opens after the customer scans their card at the valve", no button. (d) Light: tap "Turn off" → the confirm names the berths → Cancel → nothing sent (`journalctl -u cloud-iot-backend --since "2 min ago" -o cat \| grep -c 'opta/cmd/led'` unchanged); then confirm → the LED goes off within ~15 s, and "Turn on" brings it back. (e) Power: plug a test load into a socket in a test session (NOT a customer's) → "Turn on" → it goes active; "Turn off" → confirm → the session ends | Each as written. (d) and (e) change state on the cabinet: do them with the owner present | RECORD — any button on a line whose sentence says it cannot be switched, or a tap the endpoint refuses on the first try, is a defect: report before R1 | ☐ |
| 11m | **L3 history says what the staff report says** (block 4, 2026-10-15) | As a `monitor`: open a berth on Q4 → History → "‹ Earlier" to 2026-09. Then download "Monthly report (.txt)" for the same month on the same screen | The screen's session count for Q4 equals the report's Q4 rows; each figure and its label (`meter reading` / `estimated…` / `—`) match; the screen's total equals the report's Q4 subtotal, or BOTH say no total. Then V1 → History: same check against the report's V1 section | RECORD — any difference between the screen and the file for the same session is a defect: report before R1 | ☐ |
| 11n | **Which berths are checked against a photo — from the photos, not the old column** (block 4, 2026-10-15) | `sudo ls -la /opt/cloud-iot/backend/backgrounds/ \| head -50; for d in /opt/cloud-iot/backend/backgrounds/berth_*/; do echo "$d $(sudo ls "$d" \| grep -ciE '\.(jpe?g\|png\|webp)$')"; done`; `sudo -u cloud-iot /opt/cloud-iot/backend/.venv/bin/python3 -c "import sqlite3;c=sqlite3.connect('/opt/cloud-iot/backend/data/users.db');print(c.execute('select id,berth_number,reference_image from berths').fetchall())"`. Then, as admin, `/marina/setup/1` → Next, Next | RECORD both lists. Step 3 says "N photo(s)…" exactly for the berths whose `berth_<id>` directory holds photos, and L2 Vessel says "No reference photo is set" for the others, **whatever the column says** (berth 1 was seeded with `Full_Berth.jpg`) | A berth reads "checked" with no photo in its directory, or the reverse: the backend is not running this commit (§13.2) | ☐ |
| 11o | **`/marina` live over the websocket, not by polling** (block 4, 2026-10-15) | As a `monitor`, `/marina`, DevTools → Network. (a) Filter `berths`: with nothing changing, one `GET /api/marina/berths` at load, then about one a minute, NOT every 15 s. (b) Plug a load into a socket with a session running: its amps change on the row within seconds, with no new `berths` request per change. (c) A water session on V1: the V1 line shows a L/min figure while water flows (before this commit it showed `—` always). (d) WS frames: search for `customer_id`, `nfc_user_id`, `erp_ref`: none (part B, 11f) | All four. RECORD the interval seen in (a) | (a) every 15 s = the socket is not connected (the WS dot): check §13.6 10–11 first. (c) still `—` while water flows = the cabinet sends no `water_reading` for that valve: RECORD, do not change code on the pier | ☐ |
| 11p | **The nav** (block 4, last, 2026-10-15) | (a) As a `monitor`: the sidebar. Tap each item. (b) As admin: the sidebar, then Setup | (a) Exactly **Marina, Water, Alarms, Guard**, in that order; each opens its screen, and only the open one is highlighted. No Dashboard, History, Berth Occupancy or Setup. (b) Everything admin had before, plus **Setup** last; Setup opens the wizard of pedestal 1 (cabinet 1 has one pedestal) | (a) more than four items = the frontend is not this commit (§13.2). (b) Setup lands on `/dashboard` = the account is not admin | ☐ |
| 11g | Admin still sees them | The same `curl` as 11d with an admin's token | The keys are listed — redaction is by role, not a loss of data. **This is 11d's control:** if the admin also gets no keys, the last 50 sessions carried no identity and 11d proved nothing — RECORD 11d as unproven | RECORD | ☐ |

## 13.6c Guard — install, then first start (section 1, 2026-10-13)

Guard is independent of everything else here: a failure in this section stops **guard only**.
It never rolls back the cabinet. Nothing in it prints the camera URL — it carries the camera's
password — and no check below puts the password on a command line.

**Install.** `nuc_image/install-guard.sh` — installs, never enables or starts. Proven on dev:
`test_guard_install.py` TC-GINS-01..16 (14..16, 2026-10-15: the model read where the
exporter writes it, readiness from guard.env's own path, and an unreadable model not ready;
with the model where cabinet 1 has it, 12 of the 16 failed on the installer before; 10..13, 2026-10-15: the telemetry step's four
branches, all failing on the installer before; 12 is the negative control, a smoke test that
cannot pass ends the install with the package put back). `guard_smoke.py` itself measured on
dev with openvino 2026.4.1 and a YOLO-shaped IR: passes with and WITHOUT `openvino-telemetry`;
fails with the `.xml` moved away and with it corrupted, and the real script on a real systemd (WSL Ubuntu
24.04, systemd 255), first run exit 3 without a model, second run all "unchanged".

| # | Check | Command / step | Expected | If it fails | Outcome |
|---|---|---|---|---|---|
| G.1 | Install | `sudo bash ~/Cloud_IOT/nuc_image/install-guard.sh; echo "exit=$?"` | `exit=3` and `MODEL MISSING` (or `MODEL NOT READABLE by 'guard'`) until G.6 holds; `exit=0` and `GUARD INSTALLED — not enabled, not started` if it is. **Never** "INSTALLED" with a missing model | `exit=1`: RECORD the `[x]` line and STOP guard. `pip install … FAILED` most likely means no openvino/numpy wheel for this Python (3.14) — `/var/log/cloud-iot/guard-install.log` says which | ☐ |
| G.2 | Install is not start | `systemctl is-enabled cloud-iot-guard; systemctl is-active cloud-iot-guard` | `disabled`, `inactive` | STOP guard | ☐ |
| G.3 | Idempotent | Run G.1 again | Every line `[=] … unchanged`, no `[+]`; same exit code | RECORD | ☐ |
| G.4 | The backend venv is clean | `/opt/cloud-iot/backend/.venv/bin/pip list 2>/dev/null \| grep -ci openvino` | `0` (the script also refuses to finish otherwise) | STOP guard — openvino must never be in the production venv | ☐ |
| G.5 | One instance id on both sides | `sudo grep -h '^GUARD_INSTANCE_ID=' /opt/cloud-iot/guard/guard.env /opt/cloud-iot/backend/.env \| sort -u \| wc -l`; if G.1 printed `added GUARD_INSTANCE_ID to the backend .env`: `sudo systemctl restart cloud-iot-backend` and repeat §13.5 check 7 | `1`. The backend reads the id at start: without the restart it hears no worker and guard reads "unavailable" | STOP guard | ☐ |
| G.6 | **The model: the path in guard.env points where the model really is** — a CHECK, not a copy (owner, 2026-10-15: one copy, one path; nothing is copied) | `sudo grep '^GUARD_MODEL_DIR=' /opt/cloud-iot/guard/guard.env`; `sudo -u guard ls -la "$(sudo sed -n 's/^GUARD_MODEL_DIR=//p' /opt/cloud-iot/guard/guard.env)/yolov8n_openvino/"`; `sudo test -d /opt/cloud-iot/guard/models && echo SECOND-COPY-DIR \|\| echo none` | `GUARD_MODEL_DIR=/opt/cloud-iot/backend/models`; the listing, read AS `guard`, shows `yolov8n.xml` 228 077 B and `yolov8n.bin` 12 708 664 B (measured there 2026-10-15, dated 2026-10-11 17:56); `none`. G.1 then says `model: present (…) — guard.env GUARD_MODEL_DIR=/opt/cloud-iot/backend/models points at it, readable by 'guard'`. Until 2026-10-15 the installer read `/opt/cloud-iot/guard/models`, where the model never was: G.1 would have answered `exit=3` | `Permission denied` = the guard account cannot read the backend's tree: RECORD the `ls -ld` of `/opt/cloud-iot`, `/opt/cloud-iot/backend`, `…/models`, `…/yolov8n_openvino` and tell the owner — do not copy the model to get round it. A different `GUARD_MODEL_DIR` (a guard.env kept from an earlier install) = correct that one line, then G.1 again. `SECOND-COPY-DIR` = record what is in it, tell the owner | ☐ |
| G.8 | **Which TELEMETRY branch ran.** `openvino-telemetry` comes in as openvino's dependency (measured 2026-10-15); step 9 removes it only if the smoke test passes without it | `sudo grep -E 'TELEMETRY:\|SMOKE (OK\|FAIL)' /var/log/cloud-iot/guard-install.log \| tail -4`; `sudo /opt/cloud-iot/guard/.venv/bin/pip list 2>/dev/null \| grep -ci openvino-telemetry` | RECORD the line: `TELEMETRY: REMOVED` with count `0`, or `TELEMETRY: KEPT` with count `1`, and a `SMOKE OK` line naming `/opt/cloud-iot/backend/models/yolov8n_openvino/…xml`. **If KEPT, F.3 must show the filter blocks**: it is then the only barrier | `NOT DECIDED` = no model (G.6), run G.1 again. A `SMOKE FAIL` that ends the install = openvino cannot run the model on this Python: STOP guard, record the line | ☐ |
| G.9 | **The guard integration suite on THIS cabinet's broker** | `cd ~/Cloud_IOT && GUARD_INTEGRATION_REQUIRED=1 GUARD_TEST_BROKER=127.0.0.1:1883 GUARD_FFMPEG=$(command -v ffmpeg) ./backend/.venv/bin/python -m pytest tests/backend/test_guard_integration.py -v -rs 2>&1 \| grep -E 'BROKER:\|passed\|failed\|error'` | `GUARD-INTEGRATION BROKER: EXTERNAL 127.0.0.1:1883, named by GUARD_TEST_BROKER` and `10 passed`. On dev the suite runs on its own broker (since 2026-10-15); this is the only run that measures the compose broker | `PRIVATE …` in the BROKER line = the variable did not reach pytest: the compose broker was NOT tested. Any failure: STOP guard, record the test name | ☐ |
| G.7 | The egress filter's assumptions hold on THIS cabinet | `docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' pedestal-mqtt-broker`; `pgrep -c docker-proxy`; `cat /etc/docker/daemon.json 2>/dev/null \|\| echo none`; `docker version --format '{{.Server.Version}}'` | The broker inside `172.18.0.0/16` (measured `172.18.0.2`). **Proxy mode MEASURED on cabinet 1, 2026-10-15:** no `/etc/docker/daemon.json`, so `userland-proxy` is on (the default); `docker-proxy` pids 2496 (`0.0.0.0:1883`) and 2502 (`[::]:1883`) → `172.18.0.2:1883`. The worker reaches the broker via loopback and `localhost` alone would do; `172.18.0.0/16` STAYS by the owner's decision, so guard survives a later switch to `userland-proxy=false` (unit comment). Re-run only to confirm nothing changed | Broker outside 172.18.0.0/16: STOP guard — the unit's allow list is wrong for this cabinet; tell the owner | ☐ |

**First start — a separate step, after the install passed.**

| # | Check | Command / step | Expected | If it fails | Outcome |
|---|---|---|---|---|---|
| F.1 | Camera settings, without printing them | `sudo -e /opt/cloud-iot/guard/guard.env` — set `GUARD_STREAM_URL`, `GUARD_CAMERA_ID`, `GUARD_PEDESTAL_ID`; then `sudo grep -c '^GUARD_STREAM_URL=rtsp://' /opt/cloud-iot/guard/guard.env` | `1` (a count, never the value) | STOP guard | ☐ |
| F.2 | The filter as installed | `systemctl show cloud-iot-guard -p IPAddressAllow -p IPAddressDeny` | Allow `127.0.0.0/8 ::1/128 172.18.0.0/16 192.168.1.0/24` (any order), Deny `0.0.0.0/0 ::/0` | STOP guard | ☐ |
| F.3 | **Blockade or fault?** — the camera and the broker from OUTSIDE the filter, then from INSIDE it | Outside: `timeout 5 bash -c '</dev/tcp/192.168.1.191/554' && echo camera-open`; `timeout 5 bash -c '</dev/tcp/127.0.0.1/1883' && echo broker-open`. Inside the same filter: `sudo systemd-run --wait --pipe -q -p IPAddressDeny=any -p 'IPAddressAllow=127.0.0.0/8 ::1/128 172.18.0.0/16 192.168.1.0/24' bash -c "timeout 5 bash -c '</dev/tcp/192.168.1.191/554' && echo camera-open; timeout 5 bash -c '</dev/tcp/127.0.0.1/1883' && echo broker-open"` (`systemd-run -p` does not take the word `localhost` — measured — hence the prefixes) | Both lines both times | Open outside, closed inside = **the filter**, not the device: do not touch the camera, tell the owner. Closed outside too = the device or the broker — the filter is not the cause | ☐ |
| F.4 | Start | `sudo systemctl enable --now cloud-iot-guard`; wait 15 s; `systemctl is-active cloud-iot-guard`; `journalctl -u cloud-iot-guard -n 20 --no-pager -o cat \| grep -c 'MQTT connected'` | `active`, `1` or more | Exit 2 = no camera URL (F.1); exit 4 = no instance id (G.5); `cannot reach the MQTT broker` = run F.3 before anything else | ☐ |
| F.5 | The backend hears ITS worker | Logged in as admin: `/api/guard/status` | The camera listed (the row is created by the worker's live announce, §5.5.1 — built 2026-10-16), `pedestal_id` the cabinet's, `worker_alive: true`, `state` `OFF`, `sentence` "Guard off"; `/marina/guard` says the same words. **On a release before the Guard UI build** the list is EMPTY until the first enable — that is the old code, not a failure | Camera listed with `worker_alive: false` while F.4 passed: the instance ids differ, or the backend was not restarted after G.5. **No camera listed** on the new code: the worker sent no `pedestal_id` — an old worker; `journalctl -u cloud-iot-backend \| grep "without pedestal_id"` | ☐ |
| F.7 | **The clip's codec** (§5.5.4 — not knowable from the repo: the clip is a stream copy of the camera's own codec) | After the first real alarm with a recording: `f=$(sudo find /var/lib/marina-guard/recordings -name '*.mp4' \| head -1); sudo -u cloud-iot ffprobe -v error -select_streams v:0 -show_entries stream=codec_name -of csv=p=0 "$f"`; then on `/marina/guard` as admin, ▶ Play recording on that event | `h264` and it plays in the page. Anything else (`hevc`): the page still offers "Download the recording" | Not `h264`: RECORD the codec and report it to the owner — the page shows the download; nothing is re-encoded on the cabinet | ☐ |
| F.8 | **The backend can read guard's files** (§5.5.4 — read from the code as 755/644, never measured) | The same `$f`: `sudo -u cloud-iot test -r "$f" && echo READABLE; stat -c '%U:%G %a' "$f" "$(dirname "$f")"` | `READABLE`; owner `guard`, file mode readable by others or by the group `cloud-iot` | Not readable: playback answers an error for every clip — RECORD the owner and modes and report; do not chmod by hand | ☐ |
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
| 17b | **Phase 1: no camera endpoint is allowed to the ERP** (§16.3, owner 2026-10-16 — GDPR) | `sudo -u cloud-iot /opt/cloud-iot/backend/.venv/bin/python3 -c "import sqlite3,json;c=sqlite3.connect('file:/opt/cloud-iot/backend/pedestal.db?mode=ro',uri=True);r=c.execute('SELECT allowed_endpoints FROM external_api_config WHERE id=1').fetchone();ids=sorted(e['id'] for e in json.loads(r[0] or '[]')) if r else [];print(len(ids));print(ids);print([i for i in ids if i.startswith('camera.')])"` . **Then the ERP's calls (2026-10-16 it reports calling `camera.frame_ext` and `camera.stream_ext`):** `journalctl -u cloud-iot-backend --since "14 days ago" -o cat \| grep -E 'GET /api/ext/pedestals/[^ ]+/camera/(frame\|stream)' \| grep -oE '" [0-9]{3}' \| sort \| uniq -c` | RECORD the count and the list (the owner states 17 on 2026-10-15). The last line `[]`. The ERP's camera calls: every one `503` (dead calls). **No access lines at all = the access log is off: RECORD as unproven, not as a pass** | A `camera.*` id in the list = an image path to the ERP is open against the Phase 1 decision: tell the owner; it is removed on `/api-gateway` by the owner's decision, not on the pier | ☐ |
| 17d | **Restore the ERP's list** (§16.3b) — 17b FIRST, then this, then 17b AGAIN | Copy `scripts/fix_gateway_allowed_endpoints.py` from the release; dry run: `sudo -u cloud-iot /opt/cloud-iot/backend/.venv/bin/python3 fix_gateway_allowed_endpoints.py --db /opt/cloud-iot/backend/pedestal.db`; then the same with `--apply --backup /opt/cloud-iot/backend/pedestal.db.pre-gateway-$(date -u +%Y%m%dT%H%M%SZ)`. **And, to answer how 14.10 failed:** `sudo ls -la /var/backups/cloud-iot-erp/ /tmp/krk/ 2>&1; sudo grep -h krk_gateway_config /root/.bash_history /home/*/.bash_history 2>/dev/null` | The dry run lists 23 now and the diff; `--apply` ends with the 17b reading: `17`, the 17 ids, `[]`. RECORD the three listings: a `pedestal-*.db` under `/var/backups/cloud-iot-erp/` = an `--apply` got as far as the backup; none and no history line = it was never run with `--apply` | Any `camera.*` after = STOP, tell the owner. Exit 4 = the row read back differs from the target: restore from the backup (§13.11 procedure) | ☐ |
| 17e | **After the upgrade: the code refuses camera endpoints to the ERP** (§16.3) | `read -s EXT_KEY` (the gateway key); `for p in pedestals/1/camera/frame pedestals/1/camera/stream camera/1/snapshot; do echo "$p $(curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $EXT_KEY" http://localhost/api/ext/$p)"; done`; then on `/api-gateway` as admin: the four camera endpoints | Every line `403`; on the screen the four carry "Camera endpoints are not allowed to the ERP in Phase 1 — owner's decision, GDPR" and no tickbox | `200` on any = the upgrade did not bring this code (§13.2): remove the camera ids with 17d at once, and tell the owner | ☐ |
| 17c | **What occupancy says on the cabinet today** (§17.5 A — before the fix) | `sudo -u cloud-iot /opt/cloud-iot/backend/.venv/bin/python3 -c "import sqlite3;c=sqlite3.connect('file:/opt/cloud-iot/backend/data/users.db?mode=ro',uri=True);print([r[1] for r in c.execute('PRAGMA table_info(berths)')]);print(c.execute('SELECT * FROM berths').fetchall())"`; `/opt/cloud-iot/backend/.venv/bin/pip list 2>/dev/null \| grep -ci openvino` | RECORD every berth's occupancy fields and the last analysis time, and the openvino count (`0` expected, G.4). Occupied on a berth seen EMPTY at the time = finding A on the cabinet | RECORD — the fix is §17.5 A, not on the pier | ☐ |

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
| R.6 | **Nalaz 9 holds on the cabinet** — 8 days or more after the upgrade (the purge runs hourly, cutoff 7 days) | `sudo -u cloud-iot /opt/cloud-iot/backend/.venv/bin/python3 -c "import sqlite3;c=sqlite3.connect('file:/opt/cloud-iot/backend/pedestal.db?mode=ro',uri=True);print(c.execute(\"SELECT COUNT(*) FROM sensor_readings r JOIN sessions s ON s.id=r.session_id WHERE s.status='completed' AND (s.consumption_source IS NULL OR s.consumption_source NOT IN ('register','integrated_legacy')) AND r.timestamp < datetime('now','-8 days')\").fetchone())"` | More than 0 if any session without a figure completed in the days after the upgrade (its old readings survived); 0 is correct only if no such session exists — then RECORD as unproven | 0 while such sessions exist = the old rule is still deleting: report it | ☐ |

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

## 13.12 The documents — before the release is declared done (owner, 2026-10-16)

What is done and committed to `main` must be in the two PDFs: the **ERP specification** and the
**user guide**, both in the project folder. Both are generated by scripts in the repo
(`docs/generated_documents.md`), so regenerating them is a step of the release, and the release
is NOT done until these rows pass.

| # | Check | Command / step | Expected | If it fails | Outcome |
|---|---|---|---|---|---|
| DOC.1 | **ERP specification v4, under a NEW name** | `generate_erp_integration_doc.py` with `OUTPUT_PATH` → `Cloud_IOT_ERP_Integration_Guide_v4.pdf` (today it writes `_v3.pdf`, `:18`), its content corrected to the code first: event names, the §18 envelope and signature, `berth_id` int or null, authentication (§18.5) | `Cloud_IOT_ERP_Integration_Guide_v4.pdf` in the project folder; its events, envelope and auth match `erp_session_payload_contract.md` | The release is not done | ☐ |
| DOC.2 | **v3 untouched** — it is the record of what the ERP was given | `git diff --stat <release> -- Cloud_IOT_ERP_Integration_Guide_v3.pdf` | No change | Restore it from git; v3 is never regenerated | ☐ |
| DOC.3 | **The user guide** — `docs/User Guide.pdf`, from `scripts/generate_user_guide.py` (owner, 2026-10-16: the existing name; see below) | the generator, after its text is checked against the screens of this release (§5, §5.5, nav) | The guide in the project folder describes this release's screens | The release is not done | ☐ |

**DOC.4 — guard, when it lands on `main` (owner, second order 2026-10-16).** The user guide gets
the `/marina/guard` chapter: the four sentences (and "Not measured"), Arm / Switch off for admin,
the alarm, playback and Correct / False alarm for admin. The ERP guide v4 states that guard sends
nothing to the ERP in Phase 1 — `alarms.active` carries no guard event, and no camera endpoint is
open to the ERP (§16.3). Both PDFs regenerated in the release, as DOC.1 and DOC.3.

**DECIDED (owner, 2026-10-16): existing names, nothing invented.** The user guide is
`docs/User Guide.docx` from `scripts/generate_user_guide.py`; the PDF obligation means a PDF from
the SAME source with the same base name, `docs/User Guide.pdf`. The only new name is the ERP guide
v4, because v3 contains errors and must not be overwritten.

**OPEN — one conflict to resolve before DOC.3 runs:** `docs/generated_documents.md` keeps
`docs/User Guide.docx` tracked as the RECORD of v3.34, never regenerated over; the generator writes
exactly that path (`generate_user_guide.py:16`). A guide that describes this release regenerates
it. Either the record is superseded (it stays in git history at `6ae28fd`) or the generator writes
the new .docx beside it. Proposal: supersede it — git history keeps v3.34 byte for byte.

## 13.14 The first ERP read test — the owner's ten points (2026-10-16)

Run AFTER §13.2 (the one upgrade) and 17b → 17d → 17b → 17e. Nothing here changes the cabinet. No
firewall on the NUC in any form — not ufw, iptables, nftables, Docker rules, sshd, cloudflared,
tailscaled: limiting :80 to the VPS is a **Tailscale ACL in the tailnet admin panel — the owner's
task**, not this list's.

| # | Point | Command / step | Expected | If it fails | Outcome |
|---|---|---|---|---|---|
| E.1 | The cabinet runs the newest `main` | `git -C ~/Cloud_IOT fetch -q origin && git -C ~/Cloud_IOT rev-parse --short HEAD origin/main`; `ss -ltn 'sport = :8000'`; `curl -s -o /dev/null -w '%{http_code}\n' http://localhost/api/sessions` | Both hashes equal; `127.0.0.1:8000`; `401` or `403` (§16.3c — `200` is the old code) | Not on main: §13.2. `200`: STOP the ERP test | ☐ |
| E.2 | `display_id` and the cabinet's label | `sudo -u cloud-iot /opt/cloud-iot/backend/.venv/bin/python3 -c "import sqlite3;c=sqlite3.connect('file:/opt/cloud-iot/backend/pedestal.db?mode=ro',uri=True);print(c.execute('SELECT p.id,p.name,c.opta_client_id,c.dock_id FROM pedestals p LEFT JOIN pedestal_configs c ON c.pedestal_id=p.id').fetchall())"` | One row: id, name, `MAR_KRK_ORM_01`. The `/api/ext` routes answer with `display_id` = `opta_client_id` (`ext_pedestal_endpoints.py:147`) | RECORD | ☐ |
| E.3 | Tailscale up, its address, the same tailnet as the VPS | `tailscale ip -4; tailscale status \| head -20` | `100.65.235.29`; the VPS listed as a peer | RECORD | ☐ |
| E.4 | What listens on the Tailscale interface | `sudo ss -ltnp` | `:80` (nginx) on `0.0.0.0` or `100.65.235.29`; `:8000` only on `127.0.0.1` after E.1; **`:1883` on `0.0.0.0` — measured 2026-10-16, mosquitto anonymous: reachable on the tailnet until the owner's ACL closes it**; RECORD every other listener | A listener not on this list: RECORD and tell the owner — no firewall here | ☐ |
| E.5 | `:80` reachable ONLY from the VPS | the owner's Tailscale ACL; then from the VPS `curl -s -o /dev/null -w '%{http_code}\n' http://100.65.235.29/api/auth/me` and the same from another tailnet device with `-m 5` | VPS: `401`; the other device: timeout | The ACL, the owner's task | ☐ |
| E.6 | NTP synchronised | `timedatectl show -p NTPSynchronized --value; timedatectl show -p Timezone --value` | `yes` | RECORD — timestamps to the ERP would be off | ☐ |
| E.7 | Smart mode now | `sudo -u cloud-iot /opt/cloud-iot/backend/.venv/bin/python3 -c "import sqlite3;print(sqlite3.connect('file:/opt/cloud-iot/backend/pedestal.db?mode=ro',uri=True).execute('SELECT pedestal_id,smart_mode FROM pedestal_configs').fetchall())"` | `0` (measured OFF 2026-10-16; stays off for the read test). The value is the cabinet's report — firmware resets it to OFF on every boot | RECORD | ☐ |
| E.8 | The gateway today | 17b, plus `SELECT active,verified FROM external_api_config WHERE id=1` | After 17d: 17 ids, all `monitor`, no `camera.*`, no `usage.*` | 17d | ☐ |
| E.9 | Berth → socket as the cabinet keeps it | `sudo -u cloud-iot /opt/cloud-iot/backend/.venv/bin/python3 -c "import sqlite3;print(sqlite3.connect('file:/opt/cloud-iot/backend/pedestal.db?mode=ro',uri=True).execute('SELECT pedestal_id,berth_id,socket_id FROM berth_assignments ORDER BY socket_id').fetchall());print(sqlite3.connect('file:/opt/cloud-iot/backend/data/users.db?mode=ro',uri=True).execute('SELECT id,name,berth_number,pedestal_id FROM berths').fetchall())"` | RECORD both lists; the ERP compares with its own | RECORD | ☐ |
| E.10 | Both databases saved before the test | §13.1 row 0.5 (backup API, both, `integrity_check`) | `['ok', 'ok']` | STOP | ☐ |
| S.1 | Diagnostics switches nothing (§4.11 SM-Q4 step 3 — the firmware is not in the repo) | With smart mode OFF and nothing plugged in: admin → Diagnostics; then `journalctl -u cloud-iot-backend --since "5 min ago" -o cat \| grep -E 'OutletActivated\|ValveAutoOpen\|opta/cmd/(socket\|water)'` | No `OutletActivated`; at most `ValveAutoOpen … SKIPPED` lines | An outlet or valve switched: STOP — `diagnostics.run` goes back under the gate; tell the owner | ☐ |
| S.2 | With smart mode OFF, does the cabinet act on a local command? (§4.11 SM-Q6) | Smart mode OFF (now): on the admin dashboard switch the light; watch the light and `journalctl -u cloud-iot-backend --since "2 min ago" -o cat \| grep -i 'led'` | RECORD whether the light changed and whether the cabinet acknowledged (`opta/acks` for `cmd/led`) | If the cabinet ignores it: tell the owner — a "Sent" that does nothing | ☐ |

**Which answers are measurements and which only prove the connection** (§17.5 findings A and B):
the occupancy and match fields — `berths.list` `occupied*`, `match*`, `state_code`, and
`berths.occupancy_ext` — prove only that the call works; the threshold is 0.30 instead of 300 and
the drawn sector is not used. Every other answer of the 17 is a measurement.

## 13.13 Not yet on this list

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


---

# 16. Architecture — the cabinet as an edge device: Phase 1 decided, Phase 2 to be measured

**Owner, 2026-10-16.** From this date the spec is the control point of the work, not a record
after it: nothing is built that this document does not describe, and where it is silent or
contradicts itself, work stops and the owner is asked.

## 16.1 Phase 1 — DECIDED: everything stays on the cabinet

The cabinet is a device at the edge of the network. It runs four evaluation functions on its own
camera, and **everything stays on the cabinet, exactly as today**:

| # | Function | Its result | What reaches the ERP |
|---|---|---|---|
| 1 | Berth occupancy | 1 or 0 — occupied or not | the result |
| 2 | Vessel match | match or no match — is it the right boat. The reference photo stays on the cabinet | the result |
| 3 | The sector inside the camera image that the evaluation uses | a rectangle per berth | the sector as configured (numbers) |
| 4 | Guard (new) | state, and events | state and events — never a frame, never a clip |

**Towards the ERP goes state and result only — never an image, never video.**

**Condition of Phase 1, not an option:** each of the four can be started LOCALLY (an operator on the
cabinet's own UI) **and** THROUGH THE API (from the ERP). §17 specifies how.

**Pull is the truth, push is the trigger** (owner's hybrid). The ERP's authoritative read is a GET;
a webhook event tells it that something changed and is never the only copy of a fact.

## 16.2 Today against Phase 1 — measured from the code, 2026-10-16

| Function | Local, today | From the ERP, today | Result to the ERP, today |
|---|---|---|---|
| 1 Occupancy | `/berths` "Analyze", `POST /api/admin/berths/{id}/analyze` (`require_control`). **Manual only:** the periodic loop is disabled (`berth_analyzer.py:295-303`, "on-demand mode") | read only: `GET /api/ext/pedestals/{id}/berths/occupancy`, `GET /api/ext/berths`; nothing starts it | `berth_occupancy_updated` webhook — but only after someone clicks Analyze (`berths.py:543`) |
| 2 Match | the same "Analyze" (histogram match); a second "Match" button runs a Re-ID engine whose result is never stored (§17.4) | can upload a reference photo (`POST /api/ext/pedestals/{pid}/berths/{bid}/reference-image`); cannot start a match | pull only: the webhook strips the match fields (`webhook_service.py:50-60`) |
| 3 Sector | drawn on the frame, `SectorConfigModal.tsx` → `PUT /api/admin/berths/{id}/config` | read only (in `GET /api/ext/berths`); set on the cabinet by design (`ext_pedestal_endpoints.py:216-217`) | — |
| 4 Guard | **nothing in the UI** — curl only (§5.5) | nothing: no guard entry in `api_catalog.py` | nothing: no guard event in `EVENT_CATALOG` |

So **no function meets the Phase 1 condition today.** The gap per function is §17.

## 16.3 Camera endpoints — they exist, they are NOT allowed to the ERP

`camera.snapshot`, `camera.stream` (`api_catalog.py:23-24`), `camera.frame_ext`,
`camera.stream_ext` (`:65-66`) return a frame, MJPEG, or the camera's stream address. **They stay
in the code and in the catalogue** — they are used locally and Phase 2 may need them — **but they
are not in the ERP's `allowed_endpoints`. Enabling them for the ERP is blocked by the owner's GDPR
decision.**

**The catalogue is not the allow list — measured in the code.** The gateway refuses any path whose
catalogue id is not in `external_api_config.allowed_endpoints` (`external_api_gateway.py:279-302`,
403 "Endpoint not allowed"); the direct `/api/ext/...` routes check the same list
(`ext_pedestal_endpoints.py:102-114`, called at `:394` for the frame and `:473` for the stream).
So a catalogued camera endpoint gives the ERP nothing unless the cabinet's list names it.
**Confirmed by both sides, 2026-10-16: the ERP does not call the camera endpoints in Phase 1.**

**What the cabinet's list holds is a cabinet fact and is NOT measured from here.** The owner stated
that the configuration of 2026-10-15 enabled 17 endpoints and no `camera.*` among them. **The ERP
reports (2026-10-16) that it calls `camera.frame_ext` and `camera.stream_ext` TODAY** (it removes
them, its decision D30). On the code the cabinet runs (`main` = `e80a4c1`) a camera endpoint NOT in
the list answers **503** "Feature not available / Not enabled" (`ext_pedestal_endpoints.py:394-398,
473-477`), so either the ERP's calls get 503 and are dead, or the list does contain them and the
image path to the ERP is OPEN. Only the cabinet answers which: §13 check 17b, with the journal's
status codes for those calls. **If they are allowed, it is a live hole in Phase 1 and comes first.**

**DECIDED (owner, 2026-10-16): the CODE refuses `camera.*` while Phase 1 holds** — "a configuration
that can be set by hand is not a rule but a memory". Built as:

- one constant, `PHASE1_NO_IMAGES_TO_ERP = True`, in `services/api_catalog.py`, beside the
  catalogue; a catalogue entry carries `"image": True` for every endpoint that returns a frame, a
  stream or a stream address (`camera.snapshot`, `camera.stream`, `camera.frame_ext`,
  `camera.stream_ext`);
- `PUT /api/admin/ext-api/config` refuses (422, with the sentence "Camera endpoints are not allowed
  to the ERP in Phase 1 — owner's decision, GDPR") any `allowed_endpoints` entry whose catalogue
  entry has `image`;
- AT REQUEST TIME the gateway and the direct `/api/ext/...` routes refuse an `image` endpoint
  whatever the stored list says (403) — a list saved before this commit, possibly on the cabinet
  now, must not keep the path open;
- `/api-gateway` shows those endpoints greyed with the same sentence, not as a tickbox;
- a test that fails if any catalogue entry returning `image/*` or a stream URL lacks `image`, and
  one that a stored list containing `camera.frame_ext` still gets 403.

**How it is lifted, exactly — only when Phase 2 AND the owner's GDPR decision are both recorded:**
(1) the owner's decision is written in this section with its date; (2) ONE commit sets
`PHASE1_NO_IMAGES_TO_ERP = False` and changes the test that guards it in the same commit, citing
that decision — the same way the §9 limit is changed (TC-UIR-10); (3) the release that carries it
says so in its notes, and an admin then enables the endpoints on `/api-gateway`. Never an `.env`
value, never a flag on the screen: lifting it is a reviewed code change, like any other rule.

**BUILT+PROVEN on dev 2026-10-16** (same commit as §16.3b). `test_camera_ban.py` TC-CB-01..07 — all
eight fail on the code before; mutants caught: no request-time check in the gateway (04), no check
on saving (02), the frame route without its refusal (03). On the old code TC-CB-04's request was
PROXIED to the camera route (the hole, reproduced). The existing camera-route tests keep testing
the routes' own logic behind the ban with an explicit `phase2_images` fixture. The screen:
`api_gateway.spec.ts` TC-UIG-01/02, both failing on the old page — a refused endpoint has its
sentence and no tickbox; an older stored list holding one is offered for saving and saved without
it. **Found on the way:** the dev/e2e proxy matched `'/api'` as a string prefix, so the PAGE
`/api-gateway` was sent to the backend and never loaded in dev or e2e; now `'/api/'`, as nginx on the
cabinet (`location /api/`) — production was not affected. **Order (owner, 2026-10-16, after 17b
was measured):** this code ban is built in the SAME job as the cabinet's list repair (§16.3b),
before the guard UI. Negative control: saving a list with
`camera.frame_ext` is refused, and a request to that endpoint with such a list already stored is
refused.

### 16.3a MEASURED on cabinet 1, 2026-10-16 (owner) — images DID reach the ERP; the 14.10 configuration never landed

**§13 check 17b, run by the owner:** **23** endpoints enabled for the ERP, not 17. **All four
camera endpoints enabled** — `camera.frame_ext`, `camera.snapshot`, `camera.stream`,
`camera.stream_ext`. The journal, 14 days: **12 × `200`** on
`GET /api/ext/pedestals/*/camera/(frame|stream)`. So frames and the stream address DID go to the
ERP: the Phase 1 rule was broken, and that is measured, not inferred.

**FINDING (procedure, not code), 2026-10-16: the gateway configuration prepared, reviewed and
approved on 2026-10-14 never reached the cabinet, and we worked for two days as if it had.**
Nobody checked that it landed. The list on the cabinet is the one that was there before:

| | |
|---|---|
| Asked for, missing | `berths.list`, `breakers.pedestal_list_ext`, `breakers.socket_get_ext`, `sockets.config_list`, `valves.config_list` |
| Not asked for, present | `berths.occupancy_ext`, `breakers.marina_alarms_ext`, `load.marina_alarms_ext`, `load.socket_history_ext`, `usage.history`, `usage.report_download`, `usage.reports_list`, and the four `camera.*` |

**Not run, or run and refused? — what the code says, and what only the cabinet can say.** The
14.10 script is `scripts/krk/krk_gateway_config.py` in the ERP project (`erp-iot`, `2d5415e`,
2026-10-13), not in this repository. Its `--apply` **refuses with exit 5** ("--apply odbijen:
riješi ČEKA ODLUKU / BLOKADA") while ANY endpoint enabled today, outside its 17 and not
`camera.*` / its three forbidden ids, has no `--keep` / `--keep-monitor` / `--drop` decision. On
this cabinet there are SEVEN such (`berths.occupancy_ext`, `breakers.marina_alarms_ext`,
`load.marina_alarms_ext`, `load.socket_history_ext`, `usage.history`, `usage.report_download`,
`usage.reports_list`). So a run of `--apply` without seven decisions could not have written
anything — by design. **Which of the two happened is on the cabinet, not in the code** (§13 17d):
a `--apply` that got past the refusal requires `--backup` and leaves that file under
`/var/backups/cloud-iot-erp/`; the script was copied to `/tmp/krk/`; the shell history of the
account that ran it.

**Second finding, same list: the ERP can download the monthly reports.** `usage.history`,
`usage.report_download` and `usage.reports_list` are enabled. The reports carry `customer #<id>`.
**And locking the reports to admin does NOT close this:** the gateway calls the internal route with
a short-lived ADMIN token it mints itself (`external_api_gateway.py:74-88`, D3), so the ERP gets
what admin gets — on `main` and on `develop` alike. Whether the ERP may read customer ids in
reports is a decision, not a lock: the ERP owns the customer (D6.1), but the report is the
cabinet's. **OPEN — owner.** Until it is decided, `usage.*` is not in the ERP's list.

**From now on: §13 check 17b runs BEFORE AND AFTER every change of the gateway configuration —
not only after an upgrade.** The "before" is what is being changed; the "after" is the proof that
it landed. A change without both is not done.

### 16.3c MEASURED 2026-10-16 — `main` answers five routes without a login; this is why the upgrade goes BEFORE the ERP test

**Measured on dev, on `main`'s code (`e80a4c1`, a worktree, the test client, no token):**
`GET /api/sessions`, `/api/sessions/active`, `/api/sessions/pending`, `/api/pedestals`,
`/api/berths` → **200** with no login; `/api/pedestals/health`, `/api/alarms/active`,
`/api/marina/berths` → 403. The same probe on `develop` (`3ab0cc6`): all eight 403 (146ab75,
"every /api route proves identity"). Cabinet 1 runs `aa1f74f`, older than `main`; nginx proxies
`/api/` on :80 (repo config), and :80 is reachable on the tailnet — so these five answer every
device on the tailnet without a login. **Not measured on the cabinet itself** — the reading is of
the code it runs; §13.14 point 1 measures it there. The owner (2026-10-16): the heaviest finding of
the report.

**The order (owner, 2026-10-16) — one merge, one upgrade:** guard UI commit → the worker fix
(§5.5.1 item 3) → the camera password and the customer name out of the gateway (§16.3d) → merge
`develop` into `main` → upgrade → 17b → the script (17d) → 17b → 17e. The ERP test after that,
never before.

### 16.3d DECIDED 2026-10-16 — the camera password and the customer's name never leave through the gateway

**The camera password.** `GET /api/berths` returns `camera_stream_url` (`routers/berths.py:146`),
and saving the camera settings writes the username and password INTO that address
(`routers/pedestal_config.py:174-191`). The gateway proxies as admin (D3), so `berths.list` would
hand the ERP the camera password. **Decided (owner):** the field must not exist in anything the
gateway or an `/api/ext` route can return — otherwise the first person who puts it back releases
the password again. Built as ONE filter on every response the gateway returns (not a fix in one
route), and on the `/api/ext` routes: `camera_stream_url`, `camera_username`, `camera_password`
removed wherever they occur. `berths.list` stays in the 17 once this is in. **The password is never
printed** — not in a log, not in a test, not in an error message.

**The customer's name.** `sessions.*` stays in the list; the ERP may have `customer_id`,
`nfc_user_id`, `erp_ref` — that is the whole point, the ERP bills and must know whose session it
is. It may NOT have `customer_name` — the ERP has its own customer records. The same filter removes
`customer_name`. `usage.*` stays closed: finished bulk reports the ERP computes itself anyway.

**Tests (`test_gateway_secrets.py`):** TC-GS-01 `berths.list` through the gateway has no
`camera_stream_url`, while the admin's own `GET /api/berths` still does (the filter is the
gateway's, not a deleted field); TC-GS-02 with a camera password set, no response of ANY catalogue
GET endpoint through the gateway, and no `/api/ext` route, contains it — the assertion names the
endpoint, never the value; TC-GS-03 `sessions.active` through the gateway has `customer_id`,
`nfc_user_id`, `erp_ref` and no `customer_name`. All fail on the old gateway.

### 16.3b Restoring the cabinet's list — `scripts/fix_gateway_allowed_endpoints.py`

**BUILT+PROVEN on dev 2026-10-16 — to be RUN on the cabinet (§13 17d).** Standard library only, so
it runs beside the code the cabinet has now (`main`), before the upgrade. `test_fix_gateway_list.py`
TC-FGW-01..07, on a throwaway database holding the measured 23: with no script 8 of 9 fail (the
ninth checks the fixture is the 23); mutants caught — `camera.*`/`usage.*` written when targeted
(07), `--apply` without a backup (02), an id the catalogue lacks written (05). Dry run against
`main`'s own catalogue: 23 → 17, ADD the five missing, REMOVE the eleven, nothing else.

- **Target:** the 14.10 list — the 17 ids `pedestals.health`, `pedestals.list`,
  `pedestals.status_ext`, `berths.list`, `sessions.active`, `sessions.pending`, `alarms.active`,
  `load.pedestal_get_ext`, `load.socket_get_ext`, `load.pedestal_alarms_ext`,
  `breakers.pedestal_list_ext`, `breakers.socket_get_ext`, `water.status_ext`,
  `sockets.config_list`, `valves.config_list`, `analytics.daily`, `analytics.summary` — every one
  `monitor`; **no `camera.*`, no `usage.*`.** All 17 exist in `main`'s catalogue (read
  2026-10-16); the script checks again against the code it runs beside, and an id that is not
  there is LISTED and NOT written. Everything else enabled today is removed — including
  `berths.occupancy_ext`; occupancy stays readable to the ERP through `berths.list`.
- **Only `allowed_endpoints` changes.** `active`, `verified`, `webhook_url`, `allowed_events` and
  the key are untouched (written in one `UPDATE` of one column, inside `BEGIN IMMEDIATE`).
- **Rules, as for every cabinet script:** dry run by default; prints the current state (count, each
  id and mode, the `camera.*` and `usage.*` it finds) and the diff old → new (KEEP / ADD /
  TO MONITOR / REMOVE); writes ONLY with `--apply`; `--apply` requires `--backup PATH`, a path that
  does not exist yet, to which it copies the database through SQLite's backup API and checks the copy
  with `PRAGMA integrity_check` before writing anything; after writing it reads the row back and
  prints the 17b reading (count, list, `camera.*` = `[]`), exit 4 if it differs from the target.
  Idempotent: a second run says "no difference" and writes nothing.
- **Tests** on a throwaway database holding the cabinet's 23 (rule 16): dry run changes nothing;
  `--apply` without `--backup` refused; with it, the backup exists and is intact, the list is the 17,
  every other column unchanged; an id missing from the catalogue listed and not written; a second
  run writes nothing.


## 16.4 Phase 2 — a DIRECTION, NOT a decided architecture; the measurement decides

**Direction:** small files move — images, never video — and the evaluation functions move to the
ERP to unload the cabinet. The reference photo is uploaded to the ERP; the cabinet returns an image
of the boat at the berth on request. **Guard:** detection stays on the cabinet (video never
leaves it); in Phase 2 its CONTROL moves to the ERP. *(My reading of "faza 2 kontrola na ERP-u":
arming, disarming and event review are operated from the ERP. Owner to confirm.)*

**The owner is explicit: testing shows which is better.** Nothing of Phase 2 is built until the
measurement below says so. **This is a PROPOSAL of the measures, not built; the thresholds are the
owner's to set.**

**Where:** cabinet 1 (the NUC on the pier, the real camera, the real uplink), never the dev box —
a measurement taken elsewhere does not describe the cabinet (rule 17). **When:** after Phase 1 is
deployed, with all four functions running as they will in service (occupancy at its configured
interval, guard armed at 1 frame/s), for **7 consecutive days**, plus a 7-day control period with
the functions off for M2.

| # | What is measured | Unit, and how | What the outcome would mean |
|---|---|---|---|
| M1 | **What the functions cost the cabinet** | **% of one CPU core**, as a 7-day mean and a p95 of 1-minute samples, per function (guard process; occupancy + match runs) and for the whole machine; **MB** of resident memory; **ms** per inference, p50 and p95 (the owner measured one inference at 274 ms on this CPU). From guard's health message, the backend's per-run timing, and a 1-minute `/proc/stat` + `/proc/meminfo` sampler | High = there is load to take off the cabinet; low = moving the functions unloads nothing |
| M2 | **Whether that cost harms the cabinet's own work** | **ms**, p95: backend request time; MQTT message → database delay; control tap → cabinet ack. Functions ON (M1's week) against OFF (control week), same hours of the day; reported as the **difference in ms and in %** | A real difference = the functions slow what the cabinet is for; none = their cost is harmless where they are |
| M3 | **What moving images would cost the uplink** | **kB** per evaluation image (the sector crop, JPEG); **images per day** at the configured interval; **MB per day**; upload **success %**; upload **time in s**, p50 / p95 — a test upload of the real crop to an ERP test endpoint every interval for the week | Small, reliable and fast = Phase 2 is affordable; otherwise it trades a small CPU cost for an uplink dependency |
| M4 | **How late the ERP learns a result** | **s** from frame to result at the ERP, both ways: on the cabinet + push (Phase 1) against upload + ERP evaluation (Phase 2); p50 / p95 | Phase 2 later than Phase 1 = the ERP learns occupancy later than today |
| M5 | **Evaluation lost while the uplink is down** | **hours per week** the cabinet could not reach the ERP (failed deliveries, tunnel down), and the **longest single outage in hours** | Every such hour is an hour of no evaluation in Phase 2 (in Phase 1 the cabinet keeps evaluating offline) |

**The outcome rule — the shape is proposed, the numbers are the owner's, set AFTER seeing what
is measured** (the owner, 2026-10-16: "I do not set thresholds before I know what is measured"):

- **Moving makes sense** when BOTH hold: (a) the cabinet is under pressure — M1 above a share of a
  core the owner sets, or M2 worse by more than a margin the owner sets; AND (b) the uplink can
  carry it — M3, M4 and M5 inside limits the owner sets.
- **Stay in Phase 1** when the cabinet has headroom (M1 and M2 inside their limits): moving adds a
  dependency on the uplink and buys nothing.
- **Guard is decided separately** with the same measures: its own M1 share, and for control on the
  ERP, M4 for arm → acknowledgement and M5 (a guard that cannot be armed while the uplink is down).
  Guard events to the ERP are Phase 2 (§17.6).

---

# 17. The four functions — startable locally AND from the ERP (Phase 1 condition, §16.1)

**Owner, 2026-10-16. NOT BUILT — this is what gets built, in the order of §17.7.**

## 17.1 Rules for every ERP endpoint below

- **Catalogued, and allowed per cabinet.** Each endpoint gets an id in `api_catalog.py`; the ERP
  reaches it only when the cabinet's `allowed_endpoints` names it (§16.3). A write needs the
  endpoint's mode set to `bidirectional` AND `allow_bidirectional` in the catalogue — the
  gateway's existing rule (`external_api_gateway.py:308-315`).
- **The same rule on the direct `/api/ext/...` routes.** Today they check only that the id is
  listed (`ext_pedestal_endpoints.py:102-114`), so `berths.push_image_ext` accepts a write in
  read-only mode. Fixed in the same build: one check, shared with the gateway.
- **Result, never image** (§16.1): no endpoint here returns a frame, a crop or a clip.
- **Pull is the truth, push is the trigger.** Every pushed event has a GET that returns the same
  fact; the event carries the result itself (small), never a link to an image.

## 17.2 The table

| # | Function | Locally (UI → endpoint, role) | From the ERP (new unless marked) | Pushed to the ERP |
|---|---|---|---|---|
| 1 | Occupancy | `/berths` "Analyze" → `POST /api/admin/berths/{id}/analyze` (`require_control`, exists); **and periodically** (§17.3) | `POST /api/ext/pedestals/{id}/berths/{bid}/analyze` → runs now, answers `{occupied: 1|0|null, match, analysed_at}`; `GET /api/ext/pedestals/{id}/berths/occupancy` (exists) | `berth_occupancy_updated` (exists; today only after a manual click) — on a CHANGE of the result, from either trigger |
| 2 | Match (histogram, §17.4) | the same analysis | the same `POST …/analyze`; the result in `GET …/berths/occupancy` (added: `match: true|false|null`); reference photos: `POST …/reference-image` (exists), plus `GET …/reference-images` (count and names only — no bytes) and `DELETE …/reference-images/{name}` | **new** `vessel_match_updated` `{pedestal_id, berth_id, match: true|false|null}` on a change. Today the match fields are stripped from the occupancy event (`webhook_service.py:50-60`) |
| 3 | Sector | `/berths` → sector drawn on the frame → `PUT /api/admin/berths/{id}/config` (exists) | `GET` the sector as numbers (in `GET /api/ext/berths`, exists); setting it: yes, as numbers (§17.6.1 — the shape today is a rectangle); **the API shape is the ERP's proposal, R27–R30** | — |
| 4 | Guard | `/marina/guard` Arm / Switch off, admin (§5.5.2) | `POST /api/ext/pedestals/{id}/guard/enable`, `…/guard/disable`; `GET /api/ext/pedestals/{id}/guard/status` (the §5.5.1 state and sentence); `GET /api/ext/pedestals/{id}/guard/events` (time, label, has-recording — never the frame or the clip) | **not in Phase 1** — guard stays local; to the ERP in Phase 2 (§17.6.2). The ERP endpoints in this row wait for the R30 shape |

## 17.3 Occupancy runs periodically AND on request (owner, 2026-10-16)

Today the loop is disabled (`berth_analyzer.py:295-303`, "on-demand mode"), so the ERP receives a
state only after someone clicks Analyze — Phase 1 function 1 is not met. **Built:** one
analysis per configured berth every `occupancy_interval_min` minutes, plus on request (UI and
ERP). The interval is a per-pedestal setting on the admin `/berths` screen and through
`PATCH /api/ext/pedestals/{id}/berths/schedule` (bidirectional). **Proposed default 15 min, 0 =
off, minimum 1** — the owner sets the default; §16.4 M1 measures what it costs. An analysis
skipped (camera unreachable, thermal suspension, `is_rtsp_suspended`) leaves the result `null` =
not known, never 0, and is logged; it never pushes a change.

## 17.4 Match is the histogram; Re-ID is NOT IN USE (owner, 2026-10-16)

For Phase 1 "match" is the engine whose result is STORED and which the UI already shows: the
histogram comparison against the berth's reference photos (`compute_match_score`,
`berth_analyzer.py:195-222`; stored as `match_ok_bit`, `state_code`, `match_score`).

**Re-ID is not in use.** `POST /api/admin/berths/{id}/match` computes an embedding similarity and
returns it, but nothing stores it or broadcasts it (`berths.py:678-681`), and the ERP cannot
reach it. It decides nothing. **Built:** the "Match" button and the Re-ID sample upload leave the
UI (`BerthOccupancy.tsx:121, 454`; `SectorConfigModal.tsx:232`); the two endpoints
(`/match`, `/sample-embedding`) stay in the code, marked in their docstring as not in use in
Phase 1 and deciding nothing, like the dormant QR code (§8). Joining it to the stored result is a
Phase 2 question, not Phase 1 work.

## 17.5 Findings from the 2026-10-16 check — three live defects

**A. Occupancy reads "occupied" almost always on the cabinet — LIVE DEFECT in function 1.**
`detect_conf_threshold` defaults to **0.30** (`auth/berth_models.py:30`, meant as a detector
confidence). The analysis passes it as the Laplacian edge-variance threshold, whose intended
value is 300: `detect_threshold=berth.detect_conf_threshold or 300.0` (`berths.py:498`) — 0.30
is not falsy, so the 300 is never used, and `detect_ship` answers `variance > 0.30`
(`berth_analyzer.py:149-174`), true for almost any picture. **On the cabinet the fallback is
the only path:** the OpenVINO detector (`cv_services.yolo_detector` → `yolo_openvino.py:429`,
lazy import) needs openvino in the backend venv, and §13.6c G.4 requires it NEVER to be there.
So every analysis on cabinet 1 reads occupied unless the frame is nearly flat. **Fix, after the
guard UI:** two separate settings — the detector confidence (0.30) and the edge-variance
threshold (300) — never one field read as both; a test that a flat image is empty and a
textured one occupied with the real defaults. Cabinet check §13 17c records what the berths
say today.

**B. The sector barely affects the result — function 3 does not drive function 1.** The route
crops the drawn sector from its snapshot (`berths.py:455-476`), but that crop feeds only the
OpenVINO detector (absent on the cabinet, A) and the Laplacian result computed from it
(`:489`) is thrown away. The result comes from `analyze_berth_now`, which grabs a SECOND,
uncropped snapshot (`berth_analyzer.py:255`) and judges a fixed centre crop of it — 60 % for
occupancy (`:163`), 80 % for the match (`:208`). The sector is drawn and ignored. **Fix, with A:**
one snapshot per analysis, cropped to the berth's sector, and both occupancy and match judged on
that crop; a test that a change outside the sector does not change the result.

**C. The cabinet still writes invoices — against the owner's standing decision.** Every
session-completion path calls `create_invoice_for_session` (`controls.py:307`,
`mqtt_handlers.py:1427, 3786`, `customer_sessions.py:282`); it writes an invoice whenever the
session has a `customer_id` (`invoice_service.py:18`), and the still-registered legacy customer
routes set one (`customer_sessions.py:159, 183`, `mobile.py:292`; `main.py:880-882`). §1.4 said
"`invoice_service` is not on a live path" — wrong. **Decided 2026-10-16: the cabinet stops writing invoices (§17.6.3).**

**Found 2026-10-16 — NOT fixed, measured later (owner):** `test_marina_core.py` TC-MC-05 and TC-MC-06 fail when the file runs alone (5 berths instead of 4; `no_socket` instead of `standalone`) and pass in the suite — the same on `6bbfb1f`, before the guard build. A test that passes in the suite and fails alone has hidden shared state; the same pattern as the 223 tests that touched the real database.

**Found 2026-10-16 while writing TC-SM-01 — NOT fixed, for §17.5's build:** the local analyze
route (`POST /api/admin/berths/{id}/analyze`) with no frame from the buffer and none from the
camera raises inside the request: the Laplacian fallback (`routers/berths.py:489`) hands the
empty picture to `detect_ship`, which raises `PIL.UnidentifiedImageError`
(`services/berth_analyzer.py:139, 162`; reproduced with no frame and with an empty grab) — the
caller gets a 500 instead of "the camera gave no picture", and nothing is recorded. It
belongs with "a failed analysis is stored as empty" above: leave the last result, say why.
**Owner, 2026-10-16: not now** — in the same package as findings A and B, right after the ERP
test, when occupancy and match become a measurement. Then the rule holds: a failed analysis says
"not measured", never `occupied: false` and never zero.

## 17.6 DECIDED (owner, 2026-10-16)

1. **The sector, from the ERP without an image — yes; that is Phase 1** (the ERP never sees the
   frame). **What the sector IS today, measured:** an axis-aligned RECTANGLE, not a polygon — four
   fractions of the frame, `zone_x1`, `zone_y1`, `zone_x2`, `zone_y2` (0.0–1.0, top-left and
   bottom-right), plus `use_detection_zone` (1/0), per berth, in `users.db` table `berths`
   (`auth/berth_models.py:35-39`, defaults 0.2 / 0.2 / 0.8 / 0.8). Drawn by mouse-drag as one
   rectangle (`components/berths/SectorConfigModal.tsx:88, 295-297`), saved by
   `PUT /api/admin/berths/{id}/config` (`SectorConfigModal.tsx:200-204` → `routers/berths.py:112-122,
   755-764`). No polygon, point list or vertex exists anywhere in the code (searched). One berth has
   one sector; the berths of a pedestal share one camera, so one frame holds several sectors.
   Today the values are NOT validated (any float, x1 ≥ x2 accepted) and the modal's fallback is 0.1
   where the model's default is 0.2. Guard's zone is a separate rectangle per camera
   (`guard_config.zone_*`). **The API shape is the ERP's proposal (R27–R30, §18.8) — not built
   before it is agreed.**
2. **Guard events to the ERP — NOT in Phase 1.** Guard is the cabinet's own security function and
   the ERP does not bill it. It stays local; it is Phase 2 (§16.4).
3. **Invoices (finding C) — the cabinet STOPS WRITING them.** `create_invoice_for_session` returns
   without writing, and logs once per call: `invoice not written for session N — invoice writing
   is off by the owner's decision of 2026-10-16: the ERP bills`. One place (`invoice_service.py`),
   not the four call sites, so no path can miss it. Existing invoice rows and every read path stay —
   history is not deleted. Test: completing a session with a `customer_id` on each of the four paths
   writes no invoice (fails on today's code) and the log line appears.
4. **Smart mode off does NOT block the camera functions** — occupancy and match are independent of
   smart mode, and blocking them would blind the cabinet in exactly the state it is in today.
5. **Occupancy interval: 15 minutes, configurable** (owner). One inference measured at 274 ms on
   this CPU (owner), so every 15 minutes is negligible.
6. **Found answering the ERP (A4/A5), added to finding A's fix:** a FAILED analysis (snapshot
   failed, thermal suspension) is stored as `occupied_bit = 0` and the berth set to "free"
   (`routers/berths.py:524-534`, `berth_analyzer.py:243-260`) — a failure reported as "empty",
   pushed to the ERP as `occupied: false`. Rule 8: unknown is not zero. Fixed with A: a failed
   analysis leaves the last result and its time untouched, records the error, and pushes nothing.

## 17.7 Build order (owner, 2026-10-16, second message)

1. Guard UI (§5.5). 2. The ERP webhook block (§18) — before the weekly report, because without
the envelope and the two session events the NFC end-to-end test cannot pass. 3. Findings A and B
(§17.5). 4. This section's API, locally and from the ERP. 5. The weekly report (admin only, §18.6).


---

# 18. The ERP webhook — one sender, an envelope, a signature (agreed with the ERP, 2026-10-16)

**NOT BUILT — this is what gets built, as one block, one commit per item (#5, #6, #7, #8, C).**
The contract text the ERP reads is `docs/erp_session_payload_contract.md`, *Webhook delivery*;
this section is the cabinet-side specification and the evidence.

## 18.1 The split, agreed 2026-10-16

| # | Who | What |
|---|---|---|
| 5 | **cabinet** | the envelope `{event, event_id, data, timestamp}` |
| 6 | **cabinet** | `telemetry` and `session_ended` leave by webhook — `session_ended` fast, because the ERP bills on it |
| 7 | **cabinet** | ONE sender with ONE key — the ERP holds one key per cabinet, so one of our two senders always gets 401 |
| 8 | **cabinet** | HMAC signature on every delivery — the ERP makes it mandatory once the cabinet signs |
| C | **cabinet** | the reference-photo upload honours the gateway's read-only mode (§17.1); the ERP does not use that path in Phase 1, so closing it breaks nothing |
| 1, 3, 4, 9 | ERP | `/scan` body from the ERP's own tag → cabinet + outlet mapping (D6.2); the water command only after the session exists (`classify_409`); our event names; `berth_id` int or null, as data for comparison |
| 2 | — | nobody calls `/scan` yet: expected, NFC is the ERP's phase 7. Not a finding |

## 18.2 Today — two senders, measured from the code

| | Sender A — the session webhook | Sender B — the gateway webhook |
|---|---|---|
| Code | `services/erp_webhook.py` `post_erp_event` | `services/webhook_service.py` `dispatch_webhook`, a broadcast hook (`main.py`, `ws_manager.add_broadcast_hook`) |
| URL | `ERP_WEBHOOK_URL`, `.env` (`config.py:141`) | `external_api_config.webhook_url`, set on `/api-gateway` |
| Key it sends | `X-API-Key: ERP_API_KEY` — the INBOUND `/api/nfc` key, sent back out (`erp_webhook.py:100`) | `X-API-Key:` the gateway key, `external_api_config.api_key` (`webhook_service.py:94-104`) |
| Body | FLAT: the 16-key session payload plus `event` (`erp_webhook.py:86`) — no `data`, no id, no time | `{event, data, timestamp}` — no `event_id`; `data` is `message["data"]` or `{}` |
| Events | `session_activated` (`mqtt_handlers.py:2073`), `telemetry` at most every 60 s (`:2146-2149`), `session_ended` (`:1946-1949`, `:2193-2196`) — **only for a session with an `erp_ref`** (`is_erp_reportable`) | whatever `ws_manager.broadcast()` carries AND `allowed_events` names |
| Signature | none | none |

**#6, precisely.** `session_telemetry` and `session_ended` reach the websocket through
`broadcast_to_session` (`mqtt_handlers.py:2131, 2213`), which — unlike `broadcast()` — runs no
hooks (`websocket_manager.py:85` against `:88-100`), so **sender B never sees them**. Sender A does
send `telemetry` and `session_ended`, but only for a session carrying an `erp_ref`; with nobody
calling `/scan` (#2) no session has one, so sender A sends nothing either. Either way the ERP
receives no session event today.

## 18.3 What is built

**One sender (#7).** One function delivers every webhook: one URL, one key, one signature. It is
called DIRECTLY from the session code for the three session events — never through the websocket
broadcast, so which websocket channel a message travels on can never decide what the ERP gets
(the defect behind #6) — and from the broadcast hook for the catalogued non-session events
(`berth_occupancy_updated`; later §17's `vessel_match_updated` and guard). **The URL is
`external_api_config.webhook_url`**, set on `/api-gateway` (§1.3: per-deployment integration
choices live on that screen, not in `.env`); `ERP_WEBHOOK_URL` is removed. Session events go to
that URL for every session with an `erp_ref` (the contract's rule, unchanged), without being
listed in `allowed_events`; the catalogued events go only when listed, as today.
**The key: a SEPARATE signing secret (owner, 2026-10-16), §18.7.**

**The envelope (#5):**

```jsonc
{
  "event":     "session_ended",                         // the contract's names (ERP #4)
  "event_id":  "MAR_KRK_ORM_01:session_ended:847",       // unique per event, STABLE on resend
  "cabinet_id": "MAR_KRK_ORM_01",                        // R22
  "data":      { /* the 16-key session payload, unchanged */ },
  "timestamp": "2026-10-16T21:14:03Z"                    // when the EVENT happened, UTC
}
```

- **`event_id`** is derived from what the event is about, never random, so a resend of the same
  event carries the same id: `{cabinet_id}:{event}:{session_id}` for `session_activated` and
  `session_ended` (each happens once per session); `{cabinet_id}:telemetry:{session_id}:{t}`
  for telemetry, `t` the epoch second of the reading it carries; `{cabinet_id}:{event}:{subject}:{t}`
  for the catalogued events (`subject` the berth or camera id, `t` the time of the result).
- **`timestamp`** is the time of the event, fixed when the event is created; a resend never
  changes it. The body is serialised ONCE and every attempt sends those same bytes, so the
  signature of a resend is identical too.
- **`data`** for session events is `nfc_service.build_session_payload` — the same function as
  `GET /api/nfc/session/{id}`, so push and pull cannot disagree (pull is the truth).

**The signature (#8, R25):** `X-Webhook-Signature: sha256=<hex>`, HMAC-SHA256 over the exact raw body bytes
with the cabinet's key (Q1). The ERP recomputes it over the bytes it received; any change to the
body fails it.

**Delivery:** `session_ended` is sent the moment the session completes. Each event is attempted
up to **3 times — at once, after 5 s, after 30 s** — with the identical body; after that, pull
covers it (`GET /api/nfc/sessions?ended_from=…`). Not persisted across a backend restart.
*Proposal — the retry schedule is not stated by the ERP.*

**C:** the shared write check of §17.1 — a direct `/api/ext/...` write needs the endpoint's mode
`bidirectional` and `allow_bidirectional`, as the gateway already requires.

## 18.4 Proof, written first, each failing on today's code

- `telemetry` and `session_ended` for an `erp_ref` session reach a test ERP endpoint, with the
  sender configured only on `/api-gateway` (fails today: sender B never sees them, sender A uses
  another URL).
- The envelope has exactly `event, event_id, data, timestamp`; `data` equals
  `GET /api/nfc/session/{id}`.
- A forced resend carries the same `event_id`, `timestamp` and bytes; two different telemetry
  readings carry different ids.
- The signature verifies with the key and fails with any other key and with one changed byte.
- `ERP_WEBHOOK_URL` set alone sends nothing (one sender).
- `POST /api/ext/.../reference-image` with the endpoint in read-only mode → 403 (today 200).

## 18.5 Authentication, cabinet side — confirmed from the code (for the ERP, 2026-10-16)

`/api/ext/*`: `Authorization: Bearer <JWT>`, role `external_api` (the gateway key from
rotate-key, also compared with the stored key) or `api_client` (a service-account token from
`POST /api/auth/service-token`) — `external_api_gateway.py:59-65`, `ext_pedestal_endpoints.py:45-75`.
`/api/nfc/*` (scan, session, sessions, sessions/ack, session stop): `X-API-Key` equal to the
cabinet's `ERP_API_KEY` — `auth/erp_api_key.py:21-28`. (`/api/nfc/mode`, `/outlets` and
`/reconciliation*` are operator screens with an operator JWT, not the ERP's.)

## 18.6 The weekly report — no longer anything to do with the ERP (2026-10-16)

The ERP computes its weekly figures itself from the sessions and the meter history; it needs no
report from the cabinet. `docs/erp_session_payload_contract.md:216-217` promised the ERP "the
cabinet's weekly consumption report" — a report that never existed and that nobody needs: the
sentence is DELETED there (with this date and reason), not fulfilled. **The weekly PDF stays in
the package as the owner's own request from the start: a report the owner downloads as ADMIN.**
Its shape (content, grouping, the source of every figure, one page; the source is the session row
with `consumption_source` and both register readings) is proposed in this spec before anything is
built.

## 18.7 DECIDED (owner, 2026-10-16) — the signing secret

**Not `ERP_API_KEY`.** One secret for two purposes in two directions means that if the ERP's copy
leaks, both fall. The ERP already keeps a separate webhook key per cabinet (`webhook_key_enc`).

- **`ERP_API_KEY`** stays what it is: the key the ERP sends to `/api/nfc/*` (inbound only).
- **The webhook signing secret** is new and separate: `external_api_config.webhook_signing_secret`,
  set by the owner on `/api-gateway` beside the webhook URL — the screen where per-deployment
  integration settings live (§1.3) — and entered on the ERP's side as that cabinet's webhook key.
  At least 32 characters. **Write-only:** the API never returns it (it answers "set" or "not set",
  as the gateway key's `***`), and it is never logged. With no secret set, nothing is sent — an
  unsigned webhook is not sent at all, and the screen says so.
- **`X-API-Key` on outbound:** kept in THIS release, dropped in the NEXT (owner), so the ERP can
  accept both while it switches. **Which value it carries in the transition is the ERP's answer:**
  today sender A sends `ERP_API_KEY` and sender B the gateway key, and one of them gets 401 — the
  one sender sends the value the ERP's receiver accepts today (§18.8 Q-ERP).

## 18.8 The ERP's requests to the cabinet (2026-10-16) and the retry rule

| | Request | Status |
|---|---|---|
| R22 | envelope `{event, event_id, cabinet_id, timestamp, data}` | specified §18.3 (with `cabinet_id`) — build |
| R23 | `session_ended` on EVERY end path — the ERP's stop and the operator's included; telemetry under ONE fixed name | specified below — build |
| R24 | one sender, one key; URL from `/api-gateway`; `ERP_WEBHOOK_URL` deleted | §18.3 — build |
| R25 | HMAC on every webhook, `X-Webhook-Signature: sha256=…`, the separate secret | §18.3, §18.7 — build |
| R26 | the upload honours the gateway mode; plus listing and deleting reference photos through `/api/ext` | §17.1, §17.2 — build |
| R27–R30 | start occupancy; start a match with its result SEPARATE from occupancy; read and set the sector; guard state and alarms without an image | **the ERP sends its proposal of the exact shape — NOT built before it is agreed.** (Guard alarms to the ERP: Phase 2, §17.6.) |

**R23 — `session_ended` from every end path, measured.** Twelve places complete a session
(`session_service.complete`): `main.py:418` (comm loss), `controls.py:276` (operator stop), `:736`,
`:832`, `customer_sessions.py:264`, `nfc.py:1003` (ERP stop), `mqtt_handlers.py:1316, 1326, 1382`,
`:1919` (unplug), `:2177` (SessionEnded), `:3770`. **Only two send `session_ended`: unplug and the
Opta's SessionEnded.** Built: `session_ended` is emitted from inside `session_service.complete`
itself — one place every path passes — de-duplicated by the existing `mark_ended`, so no future end
path can forget it. Telemetry keeps the one name `telemetry` (the ERP adopted our names, #4).

**The retry rule (ERP, 2026-10-16).** Until the ERP has R22 it refuses webhooks of an unknown
shape with 422 and relies on pull. **A 4xx is PERMANENT** — 400, 401, 403, 404, 409, 410, 413, 422
mean the contract or the key does not match, and repeating cannot succeed: not retried, logged once
with the event, `event_id` and status. **Retried only on a 5xx, a timeout or a network error** —
three attempts (at once, +5 s, +30 s), identical bytes. 408 and 429 count as transient (retried).

## 18.9 The ERP's questions, answered from the code (2026-10-16)

- **A1 — after an operator or ERP stop, does a SessionEnded arrive and `session_ended` go out?**
  **No — nothing goes out.** The operator stop (`controls.py:260-319`) and the ERP stop
  (`nfc.py:978-1012`) complete the session and publish `stop`, with no webhook. The Opta's
  SessionEnded that follows finds no active session and returns with a warning, "SessionEnded …
  but no active session found" (`mqtt_handlers.py:2163-2165`), before the webhook (`:2193-2196`).
  The same holds for comm loss, idle timeout and the other completion paths above. Fixed by R23.
- **A3 — `event_id`?** **None today**, in either sender (`erp_webhook.py:63-87` adds only `event`;
  `webhook_service.py:94-98` sends `event, data, timestamp`). Proposed (R22): deterministic, stable
  on resend — `{cabinet_id}:session_activated:{session_id}`, `{cabinet_id}:session_ended:{session_id}`,
  `{cabinet_id}:telemetry:{session_id}:{epoch second of the reading}`.
- **A4 — the reference-photo upload.** `POST /api/ext/pedestals/{pid}/berths/{bid}/reference-image`
  takes the RAW request body (no multipart, no content type checked); the bytes are written as
  given, with no check that they are an image, under `erp_<UTC time>_<epoch>.jpg`
  (`ext_pedestal_endpoints.py:245-256`, `berth_analyzer.py:84-92`). **No size limit** on this route
  (the 1 MB limit is the gateway proxy's, `external_api_gateway.py:30`, and this route does not pass
  through it). It **ADDS** a photo; it never replaces. **No listing or deleting through `/api/ext`**
  — only locally (`GET`/`DELETE /api/admin/berths/{id}/reference-images`). R26 adds both; the
  missing image check and size limit are fixed with it (a body over 5 MB or not a JPEG/PNG/WebP is
  refused). *Proposal: 5 MB.*
- **A5 — is the match result separate from occupancy?** **No.** `GET /api/ext/pedestals/{id}/berths/
  occupancy` returns `occupied` and `last_analyzed` only (`ext_pedestal_endpoints.py:189-206`). The
  match exists only in `GET /api/ext/berths` (`berths.list`) as `match_ok_bit`, `state_code` (0
  empty, 1 occupied + match, 2 occupied + mismatch) and `match_score`; the webhook strips them
  (`webhook_service.py:50-60`). R28 separates it.
- **A6 — do guard alarms come through `alarms.active`?** **No.** Guard writes only its own tables
  (`guard_events`, `guard_detections`, `guard_recordings`) and never an `active_alarms` row, so
  `GET /api/alarms/active` has no guard alarm under any `alarm_type`. That stays so in Phase 1
  (§5.5.5, §17.6).

**Q-ERP — one question back to the ERP:** which value does your webhook receiver accept TODAY —
the cabinet's `ERP_API_KEY` or its gateway key? The transition release sends that one in
`X-API-Key` beside the signature (§18.7).
