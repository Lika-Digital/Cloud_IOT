# Access-control plan — NFC, QR and smart mode, as one change

**Date:** 2026-09-28 · **Status:** for approval. **No code written.**
**Reads with:** `docs/nfc_qr_access_audit.md` (findings + your addendum),
`docs/ui_v2_audit.md §1 Rule 6b` (smart mode).

One change, because these are the same defect wearing three hats: a control that decides
physical access or who pays is sitting in the operations tier instead of the installation
tier. Role tests get **rewritten to encode the new rules**, not adjusted until they pass.

Seven items below are marked **[DECIDE]**. One of them (§1) is new since the audit and
changes the shape of the plan, so it comes first.

---

## 0. First, the question you asked me to answer

> *"On `/api/nfc/scan`: my end-to-end description does not include it, which means either the
> mobile app uses it and my picture is incomplete, or it is a legacy path from an earlier
> design. Find out which before proposing anything."*

**The mobile app uses it. It is live, not legacy, and your picture is incomplete in a way that
matters more than the endpoint itself.**

Evidence:

| Where | What |
|---|---|
| `mobile/src/api/nfc.ts:42-44` | `nfcScan()` → `POST /api/nfc/scan` |
| `mobile/app/(app)/scan.tsx:16` | the app's own flow comment names it as step 2 |
| `mobile/NFC.md:9` | documented app flow |
| `mobile/src/hooks/useWebSocket.ts:37` | the app waits for activation *after* its own scan call |
| `mobile/src/store/sessionStore.ts:27` | stores `user_id` "what we sent to /api/nfc/scan" |
| `README.md:192`, `generate_erp_integration_doc.py:621-666` | documented to the ERP integrator |
| v3.38 | `sessions.nfc_user_id` and `GET /sessions/by-user/{user_id}` exist *because* of the `user_id` sent to `/scan` |

So it is load-bearing, and removing it is off the table.

**The part that is not in your description:** the app does not only talk to ERP. It calls our
API **directly**, and it authenticates with **the ERP machine key**:

```
mobile/src/api/nfc.ts:13   const ERP_API_KEY = process.env.EXPO_PUBLIC_ERP_API_KEY ?? ''
mobile/src/api/nfc.ts:17   const erpConfig = () => ({ headers: { 'X-API-Key': ERP_API_KEY } })
```

That is the finding, and §1 is about it.

---

## 1. **[DECIDE 1]** The ERP machine key is distributed to customer phones

`EXPO_PUBLIC_*` values are **compiled into the app bundle** by Expo — that is what the prefix
means. So the static key that authenticates ERP is shipped to every customer who installs the
app, and is recoverable from any installed build. It is a shared secret held by everyone who
has the app.

That alone would be a hardening item. What makes it this plan's problem is what the key
reaches, because **three NFC endpoints authenticate the caller and then never check what the
caller is entitled to:**

| Endpoint | Auth | Object check |
|---|---|---|
| `GET /api/nfc/session/{id}` (`nfc.py:253-262`) | ERP key | **none** — `db.get(Session, session_id)` |
| `POST /api/nfc/session/{id}/stop` (`nfc.py:294-305`) | ERP key | **none** — same |
| `GET /api/nfc/sessions/by-user/{user_id}` (`nfc.py:264-292`) | ERP key | **none** — any `user_id` |
| `POST /api/nfc/scan` (`nfc.py:211-241`) | ERP key | **none** — `user_id` is whatever the caller says |

Consequences, stated as classes rather than recipes:

1. **Billing data disclosure.** Session ids are sequential integers, and the payload carries
   energy, duration and estimated cost. Any key holder can read any session.
2. **Attribution integrity.** `/scan` takes `user_id` as free text and that value becomes
   `sessions.nfc_user_id`, which is what `by-user` and the ERP reconcile against. A caller can
   pre-register a charge under someone else's identifier.
3. **Availability.** `/stop` ends any active session by id. A key holder can stop another
   berth's charging.

Each is a *missing object-level authorisation* check — the caller is authenticated but never
authorised for the specific record. That is independent of the key exposure and would be worth
fixing even if the key were server-only; the exposure is what turns it from an ERP-trust
question into a customer-trust one.

**My recommendation — two stages, and only the first is in this change:**

**Stage 1, in this change (small, no app release needed):** add the object checks.
- `/session/{id}` and `/session/{id}/stop`: require the session's `nfc_user_id` to match a
  `user_id` supplied by the caller, and 404 (not 403) when it does not — a mismatched id
  should not confirm that the session exists.
- `/sessions/by-user/{user_id}`: unchanged in shape, but it becomes the *only* endpoint whose
  contract is "trust the caller's claim about identity", and that is documented as such.
- `/scan`: reject a `user_id` that does not look like an ERP user id, and log every scan with
  the resolved tag, socket and claimed user so attribution disputes are answerable.

**Stage 2, NOT in this change — needs your decision and an app release:** the mobile app stops
holding the ERP key. The three customer-facing calls move to the customer's own Bearer token
(the app already has one — `role="customer"`, 30-day expiry), and ownership is enforced from
the token rather than a claimed `user_id`. `X-API-Key` then means what it says: genuine
server-to-server ERP. The key should also be rotated, since the current one must be assumed
known.

**[DECIDE 1]** — approve Stage 1 inside this change, and say whether Stage 2 becomes its own
piece of work. I recommend yes, and soon, but it is an app release and a coordination with the
ERP side, so it should not be smuggled into an access-control tightening.

> I should be straight about one thing: the audit did not catch this. It checked *who may
> configure* NFC and *how the ERP path resolves*, which is what you asked, and it read
> `require_erp_api_key` as an adequate boundary without asking what was behind it or who holds
> the key. Finding it took reading the mobile client, which I only did because you told me to
> establish whether `/scan` was live.

---

## 2. Rule 1 — NFC/QR configuration becomes admin only

Per your decision: it was deliberate but the reasoning was a blanket category policy, not a
judgement about NFC. Re-pointing a physical tag is an installation act.

| Endpoint | Today | Becomes |
|---|---|---|
| `POST /api/nfc/tags` (`nfc.py:164`) | `require_control` | `require_admin` |
| `POST /api/nfc/tags/bulk` (`nfc.py:172`) | `require_control` | `require_admin` |
| `DELETE /api/nfc/tags/{cabinet}/{socket}` (`nfc.py:196`) | `require_control` | `require_admin` |
| `PATCH /api/nfc/mode/{cabinet}` (`nfc.py:98`) | `require_control` | `require_admin` |
| `POST /api/qr/regenerate` | `require_control` | `require_admin` |
| `GET /api/nfc/tags/{cabinet}` (`nfc.py:143`) | `require_any_role` | **unchanged** |
| `GET /api/nfc/mode/{cabinet}` (`nfc.py:89`) | `require_any_role` | **unchanged** |
| `GET /api/qr/all` | `require_any_role` | **unchanged** |

Reads stay open deliberately: seeing which tag is on which socket is how staff diagnose a
customer's complaint, and it is not configuration. **[DECIDE 2]** — confirm reads stay open.

Nothing machine-facing breaks: NFC endpoints are **not in the ERP catalog at all**
(`api_catalog.py` has no `nfc` entries), so ERP has no NFC path to lose. The only access lost
is human `monitor_control` operators, which is the intent.

## 3. Smart mode becomes admin only

`backend/app/routers/pedestal_config.py:340`: `require_control` → `require_admin`.

Same shape, and arguably more consequential than the NFC tightening: smart mode OFF makes the
cabinet ignore the NUC entirely, so it is the single heaviest write in the marina profile and
is currently the same tier as switching a socket. Also confirmed: `smartmode` is **not** in
`api_catalog.py`, so the gateway cannot proxy it — the allowlist concern does not apply here,
but `monitor_control_api` calling directly is admitted today and this closes that too.

The UI v2 spec assumes this is done (`ui_v2_spec.md §1.4`), which is why it belongs here and
not in the UI work.

## 4. The three misleading names — all fixed in this change

You were right that this is how it stayed invisible. Leaving any one of them would let it
happen again.

1. **`nfc.py:4`** — module docstring says *"Operator/admin (JWT, require_admin): provision /
   remove / list NFC tags"* while the code uses `require_control`. After §2 the docstring
   becomes true rather than being edited to match the old behaviour.
2. **`auth/dependencies.py`** — `require_control`'s docstring lists NFC/QR as control-tier.
   That entry is removed, and the docstring gains a one-line statement of the *principle*
   (installation acts are admin; operations are control) so the next such decision has a rule
   to follow instead of a list to copy.
3. **Frontend `const isAdmin = canControl(role)`** — a name that asserts one thing and tests
   another. Renamed to `canControl`, and the NFC/QR configuration UI is bound to a genuine
   admin check. Cosmetic in effect — the backend is the enforcement — but it is the line that
   made three reviewers believe the rule held.

## 5. Rule 3 — the four error defects

All four in scope, per your decision.

| # | Today | Becomes |
|---|---|---|
| 1 | unknown tag **and** unresolvable pedestal both `404 "NFC tag not provisioned"` | unknown tag `404 "NFC tag not provisioned"`; tag resolves but pedestal row missing `500` + *"tag is provisioned to a cabinet this system does not know"* — it is our provisioning error, not the customer's |
| 2 | socket charging **and** another pending scan both `409 "Socket already in use"` | in use `409 "Socket already in use"`; held `409 "Another customer scanned this socket moments ago — try again shortly"` with the expiry |
| 3 | smart mode **not checked** (`grep smart_mode nfc.py` → 0) | `409` + *"This pedestal is running on its own and cannot be switched remotely"* |
| 4 | pedestal liveness **not checked** (`grep opta_connected` → 0) | `503` + *"Pedestal is not responding"* |

**#4 is the one I treat as most serious**, per your instruction. Today `/scan` answers
*"pending — please plug in your charger"* when the NUC cannot act at all. The customer plugs
in, waits, nothing happens, and blames the system rather than retrying. Given this cabinet was
silent for 19 days in September, it has almost certainly already happened.

Liveness check specifics, and this is where the guard work pays in: **the check must not come
from a retained MQTT message.** `PedestalConfig.opta_connected` / `last_heartbeat` are the
right inputs, with the same staleness threshold the comm-loss watchdog uses. A cabinet whose
last retained status looks fine is exactly the v3.40 failure
(`docs/guard_b1_design.md §14` — a predicate a retained replay can satisfy is not a liveness
check). **[DECIDE 3]** — confirm `/scan` should hard-fail on a stale heartbeat rather than
proceed with a warning.

## 6. Double-bookkeeping — the tag ↔ socket cross-check

Your agreed target, unchanged. ERP sends both the tag id and the socket it resolved; we check
they agree before acting.

| Case | Behaviour |
|---|---|
| agree | act |
| disagree | **refuse + raise an ALARM.** Physical installation and configuration have diverged; someone must look |
| no local mapping for that tag | **act on ERP's instruction**, log that it could not be verified. **Never block** — an incomplete local mapping must not stop a paying customer charging |

Two implementation notes:

- **Which endpoint carries it.** The real activation path is the gateway →
  `/api/controls/.../socket/{name}/cmd` (audit Path B), so the cross-check belongs there: it
  is the call that actually switches power. `/scan` is pre-registration and switches nothing,
  so a mismatch there is worth logging but is not the safety-critical case.
  **[DECIDE 4]** — agreed, or do you want the check on `/scan` too?
- **The alarm.** It uses the existing `active_alarms` mechanism so it appears where operators
  already look, rather than a new notification path. Notifications to the marina stay off.
- **Optional then required.** Per the audit recommendation: accept the socket field as
  optional at first and log mismatches, then make it required once ERP is reliably sending it.
  **[DECIDE 5]** — approve the staged rollout, or require it immediately.

## 7. Rule 2 — the audit-trail gap

Small, as you said.

- `remove_tag` records neither actor nor time. Add `removed_by` / `removed_at` (the row already
  survives as `is_active=False`).
- `provisioned_by` is nullable, so some paths can leave an unattributed mapping. Enforce it at
  the service layer.

## 8. The ERP guide — document the gateway's admin elevation

The gateway mints a 5-minute internal admin JWT for every proxied call, so an ERP key acts
with admin authority on any allowlisted endpoint. **The enabled-endpoint allowlist is the
entire access-control surface for ERP**, and anyone reading the role system would assume
otherwise. This is stated plainly in the ERP guide.

Your question — should NFC endpoints be on that allowlist at all? **No, and they are not.**
There are no NFC entries in `api_catalog.py`, so nothing needs removing; the guide should say
that this is deliberate, so a future contributor does not add them for convenience. NFC
configuration is an installation act performed by an admin on the box, not something ERP
should be able to do remotely.

---

## 9. Role tests rewritten, not adjusted

Per your instruction. `tests/backend/test_roles.py` currently asserts `monitor_control`
**succeeds** on NFC/QR writes, because it was written to describe the behaviour rather than the
rule. Adjusting those expectations to 403 would leave a test that says "this is what the code
does" — which is how the original drift became invisible.

Instead the file is restructured around the **principle**, with a declarative table:

```
INSTALLATION_ACTS = [  # admin only — they change what the hardware IS
    ("POST",   "/api/nfc/tags",                  ...),
    ("POST",   "/api/nfc/tags/bulk",             ...),
    ("DELETE", "/api/nfc/tags/{cab}/{sock}",     ...),
    ("PATCH",  "/api/nfc/mode/{cab}",            ...),
    ("POST",   "/api/qr/regenerate",             ...),
    ("POST",   "/api/pedestals/{cab}/smartmode", ...),
]
OPERATIONS = [ ... ]          # admin + monitor_control
OBSERVATIONS = [ ... ]        # any operator role
```

and three tests that iterate it: every installation act is 403 for `monitor_control`,
`monitor_control_api` and `monitor`; every operation is 200/202 for `monitor_control`; every
observation is reachable by `monitor`.

**Plus one test that is the real regression guard:** a route-table scan asserting that no
endpoint matching the installation-act patterns is wired to `require_control`. That catches a
*new* NFC or smart-mode endpoint added later with the wrong dependency — which is the actual
failure mode here, and which no amount of per-endpoint assertions would have caught.

New tests for the rest:

| Area | Tests |
|---|---|
| §1 object checks | a session id belonging to another `user_id` returns 404 on read and on stop |
| §5 errors | four cases, each asserting a **distinct** status+message pair, not merely non-200 |
| §5 liveness | a stale `last_heartbeat` with a healthy-looking retained status still fails |
| §6 cross-check | agree → acts; disagree → refuses **and** raises an alarm row; no mapping → acts and logs |
| §7 audit trail | removal records actor and time; provisioning without an actor is rejected |

---

## 10. What breaks, and what does not

| | Effect |
|---|---|
| ERP (gateway) | **nothing.** No NFC or smartmode entries in the catalog |
| Mobile app | **nothing in Stage 1.** The three object checks need a `user_id` the app already sends |
| `monitor_control` operators | **lose** NFC/QR configuration and smart mode. This is the intent |
| `monitor` operators | unchanged |
| Admin | unchanged |
| Existing tags/sessions | unchanged — no migration except two nullable columns added in §7 |

Reversibility: every item is a dependency swap or an added check. No data is deleted, and no
schema column is dropped.

---

## 11. What I am NOT proposing

- **Not removing `/api/nfc/scan`.** It is live (§0).
- **Not changing how ERP resolves tags.** Global tag uniqueness already yields exactly one
  socket; the pedestal name stays a cross-check, as you framed it.
- **Not moving the mobile app off the ERP key in this change** (§1 Stage 2) — that needs an app
  release and ERP coordination.
- **Not touching the customer auth system**, chat, contracts or billing endpoints.
- **No new notification path.**

---

## 12. Decisions needed

| | Decision |
|---|---|
| **[DECIDE 1]** | Stage 1 object checks in this change; Stage 2 (app off the ERP key, key rotated) as its own piece — approve, and confirm Stage 2 is wanted |
| **[DECIDE 2]** | NFC/QR **reads** stay `require_any_role` |
| **[DECIDE 3]** | `/scan` hard-fails on a stale heartbeat rather than warning |
| **[DECIDE 4]** | the tag↔socket cross-check lives on the controls activation path, not `/scan` |
| **[DECIDE 5]** | cross-check socket field optional-then-required, rather than required at once |
| **[DECIDE 6]** | role tests restructured around installation/operation/observation, including the route-table scan |
| **[DECIDE 7]** | ERP guide states the gateway's admin elevation, and that NFC is deliberately absent from the catalog |

Once these are settled I will implement it as one commit series on `develop`, with the role
tests written first so the tightening is demonstrated by a test that fails before the change
and passes after.
