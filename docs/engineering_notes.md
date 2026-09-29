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

## Appendix — things that look like over-engineering and are not

One line each on what they prevent, for whoever maintains this next. Removing any of them
restores a specific, previously-observed failure.

*(To be completed in the docs pass — see the access-control plan and the guard design for the
current entries: provenance-not-boundary on `X-Ext-Api-Caller`; the sustained-quiet clock
restarting on any CPU rise; releasing the assembly pin on failure; recording clip age from the
filename rather than mtime; 404-not-403 on someone else's session; three divergence states
rather than two.)*

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
