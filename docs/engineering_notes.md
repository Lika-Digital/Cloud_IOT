# Engineering notes — rules that cost us something to learn

Cross-cutting rules, each earned from a specific defect. They live here rather than inside the
design document that happened to expose them, because **a general rule filed under a specific
design document is a rule nobody finds.**

Each entry says what happened, the rule, and how it is enforced. Where a rule is enforced only
by this document, that is stated — a rule with no mechanism is a hope.

---

## 1. A predicate a retained replay can satisfy is not a liveness check

**Caught us three times, and the third was inside the test written to prevent the first two.**

- **v3.40, cabinets.** The broker replays the last retained message per topic to every new
  subscriber. After a backend restart, a cabinet silent for 19 days delivered its final status
  looking exactly like a live one, and the handler stamped it `online` with a fresh heartbeat.
- **v3.42, guard worker.** Same rule applied from the start — but the retain flag alone was
  insufficient. A **Last Will is delivered to already-subscribed clients with RETAIN=0**
  ([MQTT-3.3.1-9] sets that flag only for messages delivered in response to a *new*
  subscription), so the will was indistinguishable from live traffic and `mark_seen` stamped a
  dead process as alive.
- **v3.42, the integration test itself.** Its "the worker is up" predicate was
  `reported(cam)["state"] is not None`. A retained Last Will from an earlier run satisfied it, so
  a command was published to a worker that had not yet subscribed, and QoS 1 dropped it silently.

> **"Some state exists for this device" and "this device is there" are different claims.** Only
> live traffic establishes the second.

**In practice:** assert on liveness, not on the presence of data — `liveness.is_alive()` is sound
by construction because `mark_seen` is reachable only from non-retained traffic. Clear retained
state around tests that depend on absence. And ask whether the *content* could only have come
from a live sender: `UNAVAILABLE` could not, which is why it never counts as proof of life.

**Enforced by:** `TC-GINT-05`, `TC-GAPI-07`, `TC-NFCE-06`, and `liveness.mark_gone()`.

---

## 2. Authentication answers "who is this", never "may this caller touch this record"

**v3.43.** Four NFC endpoints validated the `X-API-Key` and then acted on whatever session id or
`user_id` the request named. A valid key is not a claim to a particular record. The same
credential is compiled into the mobile app bundle as `EXPO_PUBLIC_ERP_API_KEY`, so it must be
assumed known.

> **A boundary is only as good as who holds the credential.** And a machine key distributed to
> every customer's phone is not a machine key.

**In practice:** any endpoint naming a specific record under a credential that identifies *one
party among many* needs an object-level check. Operator roles are exempt by design — an operator
is role-authorised for every record, which is what being an operator means.

**Enforced by:** `TC-OAZ-01` scans the live route table and fails on anything unclassified; the
per-endpoint behaviour is `TC-NFCA-01..10`. The scan is the load-bearing half, because the defect
was four endpoints nobody had thought about, and per-endpoint assertions cannot catch the fifth.

---

## 3. Never pipe a failure you need to see through something that discards it

**Twice, the same mistake in different clothes.**

- A test's failure message built the worker log with an **f-string argument**, evaluated before
  the wait began — so it always printed an empty log, and three runs were diagnosed blind.
- A commit was piped through `tail -4`, which cut off *"Commit aborted — tests must pass"*, and
  `tail`'s own exit 0 masked the non-zero status. The commit was reported as running when it had
  already failed.

> **Read the evidence at the moment of failure, through something that preserves it.** A lazily
> evaluated callable, not an eager string. A captured file, not a truncating pipe.

**In practice:** `_await(..., diagnose=callable)` rather than a formatted message. `cmd > out.txt
2>&1; echo $?` rather than `cmd | tail`. In shell pipelines, `PIPESTATUS[0]` — the last command's
status is not the one you care about.

**Enforced by:** nothing automatic. This one is discipline.

---

## 4. A test that skips has not verified the claim

A skipped test reads as a pass in every summary line, and the questions most likely to be skipped
are the ones only answerable where it matters — on the hardware, on the marina LAN, with ffmpeg
installed.

> **Count and name skips. Never bury them in a total.**

**In practice:** `run_tests.sh` prints the skip count with reasons. The guard integration suite
has a `GUARD_INTEGRATION_REQUIRED=1` mode where a skip becomes an outright failure, and the
deployment runbook invokes it that way, so a missing broker on the NUC cannot masquerade as a
green deployment. When a negative-half assertion was about to skip for want of a seeded customer,
the customer was created in the test instead — the skip would have left the actual claim
unverified.

**Enforced by:** `_unanswered()` and `TC-GINT-08`; `run_tests.sh`'s skip report.

---

## 5. Fail on unrecognised input rather than extracting whatever you recognise

**v3.43.** `_socket_name_to_id` stripped non-digits and returned the result, defaulting to 1 when
there were none. So `_socket_name_to_id("V1")` returned **1** — a water valve resolving to
electricity socket Q1, silently and with confidence. It was unreachable only because a separate
validation refused to store a `V1` tag, and relaxing that validation is the first thing anyone
adding water support does: the single protection in the way was the one the next change removes.

> **A parser that falls back to extracting whatever it recognises will eventually return a
> confident wrong answer.** An identifier the system does not recognise is an error, not a
> best guess.

**In practice:** an allowlist and a raise. Where the caller cannot tolerate an exception, guard
it *per item* so one malformed entry skips itself rather than aborting the batch.

**Enforced by:** `UnknownOutletName`, `TC-RES-01..06`.

---

## 6. Only a capture is evidence of what hardware sends

**v3.43, immediately after writing rule 5.** Having refused to let the parser guess, I seeded its
allowlist from a docstring claiming the water payload carried `{"id":"WTR-1"}`. A real capture
from MAR_KRK_ORM_01 (firmware 3.1.0) shows `{"id":"V1"}`. The `WTR-n` spelling exists nowhere in
real traffic — only in that docstring and in a topic we publish that nothing subscribes to.

In the same change I wrote that bare-digit socket names were "load-bearing for real traffic".
They are not: real firmware uses `Q1`..`Q4` exclusively. Bare digits appear only under
`marina/cabinet/...`, a topic family the firmware never publishes — so they are load-bearing for
the 26 *tests* that exercise it, which is a weaker and accurate claim.

> **A spelling that appears only in our own documentation, our own tests, or a topic we publish
> that nobody subscribes to is not evidence of what the hardware sends.**

**In practice:** mark provenance per entry. `_SOCKET_NAMES` and `_VALVE_NAMES` now carry
`# VERIFIED, firmware 3.1.0` or `# unverified — marina/* scheme only` against each group, because
"this is in our tests" and "this is what hardware sends" are different claims and the code
previously gave no way to tell them apart.

**Corollary, same root cause:** the comment above the `MARINA_*` topic regexes said
*"(real hardware)"* and meant the opposite. Every handler in that family fires only from tests.

---

## 7. While a commit gate is in flight, the working tree is frozen

**Three times from one root cause**, which is two more than it should have taken.

A pre-commit hook tests **the tree as it is at that moment**, not the snapshot that was staged.
So editing files while a gate runs means it tests something nobody intended, and running a
second test suite alongside it means both share one SQLite file and clobber each other. The
symptoms are convincing and worthless: ten failures across unrelated modules, a commit reported
as running when it had already aborted, and a failure list that evaporates on a clean run.

> **Start a gate, then touch nothing — no edits, no test runs — until it finishes.** If work
> must continue, separate it first (`git stash push --keep-index`), so the gate sees one
> coherent change.

**And fix the gate rather than working around it.** The reason the rule kept being broken is
that the gate took 8–10 minutes and sometimes never finished, so waiting felt expensive. The
cause was measurable: `pip-audit` fetches PyPI's advisory database and ran >122 s without
completing. Its *result* was already advisory — its *runtime* was unbounded, and **a
non-blocking check that can hang forever still blocks.**

**Enforced by:** the gate split (`GATE_LEVEL=fast` on commit, `full` on push), hard timeouts on
every network-dependent stage, and a not-run report at the end so a fast gate is never mistaken
for a complete one. `scripts/install_git_hooks.sh` exists because `.git/hooks/` is untracked, so
a gate improvement on one machine otherwise reaches nobody — and a fresh clone has no gate at
all while looking exactly like one that passed.

---

## 8. Zero and unknown are different values, and must stay different rows

**v3.43, meter registers.** A cumulative register that does not move between two boundaries
means genuine zero consumption — a boat plugged in and drawing nothing, which is a true
observation worth recording. A register that could not be read means we do not know.

Collapsing the second into the first loses a real measurement *and* asserts something false:
zero tells ERP the customer used nothing, and they would bill accordingly.

> **`0.0` is a measurement. `None` is the absence of one.** Never coalesce them, and never
> default the second to the first because a column is non-nullable.

**Enforced by:** `DeltaResult.status` distinguishing `ok` / `unknown` / `rejected`, and
`consumption_source` on the session recording how a figure was derived.

---

## 9. A broad `git add` is not a shortcut, it is an unreviewed commit

**v3.43.** `git add -A backend frontend mobile docs tests` staged 42 generated files alongside
a nine-file change: a QR PNG per test cabinet, berth background images, the status JSON the
app writes while running, Playwright's `test-results/`, and `backend/data/` — which is where
the **auth database** lives.

The gate passed. Every check was green, because nothing in the suite has an opinion about what
is *in* a commit. It was harmless this time. The same command on a machine that had once run
against production credentials would have published them, and the diff was too large to notice
by eye — which is the actual mechanism: the noise is what hides the one file that matters.

> **Stage the paths you edited.** `git add -A <dir>` means "and whatever else happens to be
> there", which on a working machine is runtime output, local databases and test artefacts.
> If a broad add is genuinely wanted, read `git status --short` before committing, not after.

**Enforced by:** `.gitignore` entries for the four directories involved — which closes those
four, not the class. The habit is the control.

---

## 10. An error count nobody acts on hides the next error

**v3.43.** `tsc --noEmit` on the mobile package reported four errors, all known and none
urgent, so nobody read the output. A fifth arrived —
`mobile/app/(app)/mobile/socket/[pedestal_id]/[socket_id].tsx` imported
`../../../../src/api/mobile`, four directory levels up where five were needed, resolving to
`app/src/api/mobile`, which does not exist. The **entire QR landing flow could not build**,
and had not for some time.

The number is not the problem. **Four** is as good as **zero** if someone checks that it is
still four. What breaks is a count that is merely tolerated: the signal degrades to noise, and
then the tool is off while still appearing to run. Same shape as rule 4 — a skipped test has
not verified the claim — one level up: a check whose output is known to be noisy has stopped
being a check.

> **Every check has a budget of zero.** Either the count is zero, or the expected set is
> written down and compared. "It always prints a few" is a check that has stopped working.

**Enforced by:** `tests/run_tests.sh` runs `tsc --noEmit` on `mobile/` at the full gate, with
the baseline brought to zero first — the four were fixed, not waived: a chat `direction` type
widened to `string`, two styles referenced but never defined, and the import itself. Any error
now fails the gate. The eslint "deps not installed" branch, which used to skip silently, now
reports itself in the NOT RUN summary for the same reason.

---

## 11. A claim the owner approved is not thereby true — and is harder to dislodge

**v3.43.** I reported that the firmware publishes no per-valve state. The owner accepted it and
approved a dash-with-tooltip in the UI on that basis. It was wrong:
`opta/water/V{n}/status` had carried `state` and `hw_status` all along. The handler broadcast
both and stored neither, so every later reader fell back to `socket_states` — keyed by outlet
number alone — and answered a question about V1 with socket 1's plug-in signal. "Cable
detected" on a tap.

The sign-off is what makes this its own rule. An unexamined wrong fact gets corrected the next
time someone looks. A wrong fact that has been **stated, reviewed and approved** acquires a
decision on top of it, and anyone who later sees the contradiction has to argue with the
decision rather than with the fact. It took writing a code comment asserting the claim before
it got checked against a capture.

> **An approval transfers a decision, never a fact.** When reporting something as a constraint
> of the hardware, the world, or another system, cite the evidence in the same sentence — and
> if the evidence is a docstring or your own earlier message, say so, because that is the case
> where you are most likely wrong.

Same root as rule 6, one level out: there, documentation became a source of truth about
hardware it had never been checked against. Here, **a report** did.

**Caught by:** reading the real payload in the handler while writing a comment about it.
`grep` for the field name would have done it at any point in the preceding six months.

---

## Appendix — things that look like over-engineering and are not

One line each on what they prevent, for whoever maintains this next. Each looks like needless
complication; removing any of them restores a specific, previously-observed failure.

| Looks odd | Why it is there |
|---|---|
| **One unreadable interval makes the whole session's figure unknown** | The sum of a partial set is not the total. Reporting it as one is a silent under-report, and the customer is the one it favours least. |
| `X-Ext-Api-Caller` is called a *provenance hint*, never a security boundary | Anyone who can already reach the API with an operator token could set it. It holds ERP to a stricter contract than a human; nothing is *granted* on its strength. Pretending a settable header is a control would be worse than having no discriminator. |
| The sustained-quiet clock **restarts on any CPU rise**, not just on a suspension | Otherwise a box flapping at the limit accumulates unrelated quiet and resumes guard on it, then immediately re-suspends. |
| Manual re-arm clears the **CPU window**, not only the budget | A re-armed guard judged on samples from the overload it just recovered from is re-suspended within seconds. |
| The assembly pin is released **in a `finally`** | A failed clip assembly would otherwise pin segments for ever, and the capture ring silently stops reclaiming disk. |
| Clip age comes from the **filename**, not mtime | A file copied, restored or touched gets a new mtime, and retention would then keep evidence it should have dropped — or drop evidence it should have kept. |
| **404, not 403**, for someone else's session | A distinct "forbidden" confirms the record exists, which is all an enumeration of sequential ids needs. |
| **Three** divergence states, not two | "ERP stopped reconciling" and "nothing happened worth reconciling" need different responses. One alarm for both gets muted, and then the first goes unnoticed too. |
| Ownership is checked **before** the already-ended check | Otherwise a 409 tells a stranger the session exists and what state it is in. |
| `provisioned_by` **raises** instead of defaulting to "(unknown)" | A caller with no actor has a bug; a default hides it, and an unattributable NFC mapping decides who pays. |
| A valve reads its **own** state and never `socket_states`, and reports **"unknown"** when that state is stale | `socket_states` is keyed by outlet number alone, so consulting it for a valve returns the ELECTRICITY socket of the same number — "cable detected" on a tap, or "idle" while water ran. A *plausible* wrong answer, which is the dangerous kind. The staleness check is the same rule as 1: a stored state three days old is not a reading. |
| A valve has **no "pending"** state, and the fault check is **skipped** for one | "Pending" means physically connected and awaiting activation, which comes from the socket's plug-in detection; the firmware has no valve analogue, so the state does not exist rather than being unread. And no valve **fault** vocabulary has ever been observed, so a fault check would be asserting a value we have never seen — a passing answer indistinguishable from a real one. |
| A water tag is refused on a mode-2 site until a flag says the app shipped | The refusal looks like an obstacle to whoever is holding the tag. An app build from before v3.43 cannot resolve `V1`, and its adoption check treats an unresolved outlet as "matches anything" — so the next customer to scan water is shown, and billed for, a stranger's electricity session. A procedure that depends on remembering will be forgotten at the next site. |
| The outlet **type** is stored on the tag rather than derived from its name | Both inbound name vocabularies accept bare digits, so `"1"` cannot distinguish socket 1 from valve 1. There is no function that could recover it later. |
| `V1` declared as a socket is **refused**, not corrected to a valve | Either the name or the type is wrong and nothing on the server knows which. Picking one writes a mapping nobody asked for, and this mapping decides which outlet a customer's tap energises. |

---

## Appendix — the simulator

`simulator/pedestal_simulator.py` and `simulator/generators.py` were **deleted on 2026-03-15** by
`be0df4f` ("fix(nuc-image): remove simulator…"), 480 lines in total, for the stated reason "not
needed on NUC". They were removed from the repository rather than excluded from the NUC image, so
nothing has been able to start a simulator since.

`simulator_manager.py` was left pointing at the deleted path, and `Popen` on a missing file raises
`FileNotFoundError`, which was caught and logged — so "Start Simulator" failed silently into the
error log for six months while the dashboard answered `running: false` with no explanation.
v3.43 makes the absence explicit (`simulator_available()`, `NOT_INSTALLED_MESSAGE`, and a `reason`
on the status and start endpoints).

**Recorded here so the next person who finds `simulator_manager` does not hunt for code that has
not existed for six months.** A rewrite against the current contract — the `opta/*` topic family,
per-valve water with `total_l`, configurable 1–4 berths with the shared-valve case, and the
six-tag NFC model — is planned to land after the UI v2 spec is approved and before UI
implementation, at which point it pays for itself immediately: every configuration the wizard
must handle needs rendering and looking at.
