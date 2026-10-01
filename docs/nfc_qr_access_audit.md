# NFC / QR access-control audit

> ### ⚠ QR IS DORMANT — decision of 2026-09-30
>
> **NFC is the supported provisioning and customer-entry path.** The QR code, the
> `/api/mobile/qr/*` router, the landing screen and `tests/backend/test_mobile_qr_claim.py`
> are **dormant, not removed**: nothing is deleted, nothing is maintained, nothing is
> extended, and the test suite is skipped in full with the reason
> `"QR is not a supported path, decision of 2026-09-30"`.
>
> Anything below describing QR records how it worked on the day it was parked. It is **not a
> statement about the current system** and must not be treated as current when planning,
> estimating or answering a question about what the product does. UI v2 contains no QR
> screens, wizard steps or CORE fields.
>
> The v3.43 six-outlet parity work on it is finished and stays. Nothing further is planned.


**Date:** 2026-09-27 · **Status: AUDIT ONLY — nothing changed.** Awaiting approval of one
consolidated plan rather than a sequence of access-control patches.

For each rule: **how it works today**, **whether it meets the rule**, **what must change.**

---

## RULE 1 — NFC/QR configuration must be ADMIN ONLY

### Verdict: **FAILS.** Marina staff can write, reassign and delete NFC tags today.

### How it works today

Every NFC/QR configuration endpoint is gated by `require_control`, not `require_admin`:

| Endpoint | Guard | Who that admits |
|---|---|---|
| `POST /api/nfc/tags` | `require_control` | admin, **monitor_control**, **monitor_control_api** |
| `POST /api/nfc/tags/bulk` | `require_control` | same |
| `DELETE /api/nfc/tags/{cabinet_id}/{socket_id}` | `require_control` | same |
| `PATCH /api/nfc/mode/{cabinet_id}` | `require_control` | same |
| `POST /api/pedestals/{cabinet_id}/qr/regenerate` | `require_control` | same |
| `GET /api/nfc/tags/{cabinet_id}` (read) | `require_any_role` | + monitor |

`dependencies.py:_CONTROL_ROLES = {"admin", "monitor_control", "monitor_control_api"}`.

**The enforcement is correctly placed** — it is a real backend dependency on every write
endpoint, not a hidden button. A known URL cannot bypass it. The tier is simply wrong:
`monitor_control` is the "Monitoring and Control" profile, i.e. exactly the marina staff
this rule says must be excluded.

### Three reasons this was invisible to a reader

Worth recording as a finding in its own right, since you noted the same thing:

1. **`nfc.py:4` claims a guard it does not use.** Its module docstring says
   *"Operator/admin (JWT, **require_admin**): provision/remove/list NFC tags per socket."*
   The code uses `require_control`. Anyone reading the file would reasonably conclude the
   control was already admin-only.
2. **The two docstrings contradict each other.** `dependencies.py:require_control`
   explicitly lists **"NFC/QR"** among the sections it gates. So one file says admin-only
   and the other says control-tier, and the code follows the second.
3. **The frontend variable is misnamed.** `PedestalControlCenter.tsx:925` —
   `const isAdmin = canControl(role)`, where `canControl` includes `monitor_control` and
   `monitor_control_api`. It is then threaded down as `isAdmin={isAdmin}` into
   `NfcProvisioningTable`, which uses it to show the tag inputs and Provision/Remove
   actions. A variable named `isAdmin` that is not "is admin" is how a reviewer misses this.

### Deliberate decision, or drift? **DELIBERATE — and recorded.**

This was chosen, not drifted into. `README.md` v3.34 changelog:

> **Backend**: new `require_control` dependency (admin OR monitor_control) gates the
> write/control endpoints in the non-admin sections (session controls, breaker reset,
> smart-mode/auto-activate/threshold config, LED, **NFC/QR**, billing config, contracts, …)

and `tests/backend/test_roles.py` carries 16 role-gating tests asserting
`admin`/`monitor_control` are **allowed** on those writes.

So there is a recorded decision to override. But reading it, the reasoning looks like a
**blanket policy** — *"monitor_control may configure every section except the three
admin-only ones (System Health, Settings, API Gateway)"* — rather than a considered
judgement about NFC specifically. NFC/QR appears in a list of eleven things, not as its own
call. Nothing in the changelog argues that marina staff *should* be able to re-point a
physical tag to a different socket.

### Who else uses `require_control`, and what tightening would break

54 call sites across 12 routers:

```
berths.py 11 · controls.py 10 · pedestal_config.py 7 · nfc.py 5 · meter_load.py 5
contracts.py 3 · chat.py 3 · usage_history.py 2 · qr.py 2 · data_export.py 2
breakers.py 2 · billing.py 2
```

Only **nfc.py (5)** and **qr.py (1 write)** are in scope for this rule. Checking the callers
you were worried about:

| Caller | Affected by tightening to `require_admin`? | Why |
|---|---|---|
| **ERP / myMarina** | **No** | The gateway mints a short-lived **admin** JWT for every proxied call (`external_api_gateway.py:_make_internal_admin_jwt`, `role="admin"`, 5 min). ERP already arrives as admin and would satisfy `require_admin` unchanged. |
| **Mobile app / berth holders** | **No** | `_get_current_user` rejects any JWT whose role is not in `_OPERATOR_ROLES`; mobile and customer tokens are `role="customer"`. They cannot reach NFC config at all today. |
| **Human `monitor_control` operators** | **Yes — intended** | This is the change. |
| **`test_roles.py`** | **Yes** | Its expectations assert `monitor_control` succeeds on NFC/QR writes and would need updating alongside. |

**So tightening is safe for every machine caller.** The only behavioural loss is human
marina staff, which is the point of the rule.

### What must change

- `nfc.py`: `POST /tags`, `POST /tags/bulk`, `DELETE /tags/...`, `PATCH /mode/...` →
  `require_admin`.
- `qr.py`: `POST /qr/regenerate` → `require_admin` (it invalidates codes customers scan).
- Reads (`GET /tags`, `GET /mode`, `GET /qr/all`) can stay `require_any_role` — seeing which
  tag is on which socket is legitimately useful to staff and is not configuration.
- Fix the three misleading signals: the `nfc.py` docstring, the "NFC/QR" entry in
  `require_control`'s docstring, and rename the frontend `isAdmin` to match what it tests
  (or bind the NFC table to a genuine admin check).
- Update `test_roles.py` to assert `monitor_control` is now **403** on NFC/QR writes — the
  test should encode the new rule, not be deleted.

---

## RULE 2 — NFC mapping: tag id → pedestal → socket, configured once by admin

### Verdict: **MEETS the rule**, with one gap in the audit trail.

### How it works today

`nfc_tags` (pedestal.db):

```python
nfc_tag_id     = Column(String, unique=True, nullable=False, index=True)
cabinet_id     = Column(String, nullable=False, index=True)   # "MAR_KRK_ORM_01"
socket_id      = Column(String, nullable=False)               # "Q1".."Q4"
provisioned_at, provisioned_by, is_active
```

| Requirement | Status | Evidence |
|---|---|---|
| tag id stored per socket | **Yes** | `cabinet_id` + `socket_id` per row |
| globally unique | **Yes** | DB-level `unique=True` **and** a service-layer pre-check |
| resolvable back to pedestal + socket | **Yes** | tag → `cabinet_id` → `PedestalConfig.opta_client_id` → `pedestal_id`; `socket_id` → int |
| cannot be assigned to two sockets | **Yes** | unique constraint; `provision_tag` raises `DuplicateNfcTagError(cabinet, socket)` naming the current owner |
| re-assignment deliberate | **Yes** | provisioning a new tag for a socket sets the previous row `is_active=False` rather than deleting — history is kept |
| re-assignment logged | **Partial** | `provisioned_by` (admin email) + `provisioned_at` are recorded on **creation** |
| unknown/unassigned tag fails clearly | **Yes** | `404 "NFC tag not provisioned"`. **No fallback to a default socket** — verified in `nfc_scan`. |

### What must change

Small, and not urgent:

- **`remove_tag` records no actor or time.** It sets `is_active=False`, so the row survives,
  but nothing says *who* removed a tag or *when*. For a control that decides which socket a
  customer's tap energises, removal deserves the same trail as creation.
- **`provisioned_by` is nullable.** Any path that omits it leaves an unattributed mapping.
  Worth making non-null at the service layer.

---

## RULE 3 — the ERP path must resolve the same way

### Verdict: **The code does not work the way the rule describes.** Stating plainly what it actually does.

There are **two separate ERP paths**, and **neither** carries "NFC tag id + pedestal name".

### Path A — `POST /api/nfc/scan` (X-API-Key)

```python
class NfcScanBody(BaseModel):
    nfc_tag_id: str
    user_id: str
```

- **There is no pedestal name in the request.** Only tag id and ERP user id.
- Resolution is **by tag id alone**: `get_active_tag_by_id` → `cabinet_id` + `socket_id`.
- **It does not switch anything.** It pre-registers intent with a 5-minute TTL; the socket
  activates later, on plug-in.

On the resolution property you asked about, the outcome is *right for a different reason*:
because tag ids are globally unique, one tag id yields **exactly one** socket. There is no
guessing, no partial match, and no "first socket on that pedestal".

**But the absence of the pedestal name removes a cross-check that would be worth having.**
If a tag were physically stuck on the wrong pedestal, or provisioned against the wrong
cabinet, the scan resolves to whatever the database says and arms **the wrong socket**,
silently. Sending the pedestal name would let us detect that mismatch and refuse. That is
an argument for adding it as **verification**, not as part of resolution.

### Path B — ERP socket on/off, via the API gateway

`api_catalog.py`: `controls.socket_cmd` → `/api/controls/pedestal/{pedestal_id}/socket/{socket_name}/cmd`, `allow_bidirectional: True`.

- Addressed by **numeric `pedestal_id` + socket name (`Q1`..`Q4`)**.
- **No NFC tag involvement at all.**

So the on/off request ERP makes does not mention a tag, and the request that mentions a tag
does not switch anything. Those are two different mechanisms, and the described
"tag id + pedestal name → socket → switch" is neither.

### Error distinctness: **FAILS in four places**

| Situation | Today | Problem |
|---|---|---|
| Unknown tag | `404 "NFC tag not provisioned"` | — |
| Tag exists, pedestal row missing | **`404 "NFC tag not provisioned"`** | **Identical message for a different fault.** A provisioning error is indistinguishable from an unknown tag. |
| Socket already charging | `409 "Socket already in use"` | — |
| Another live pending scan | **`409 "Socket already in use"`** | **Identical message.** ERP cannot tell "someone is charging" from "someone scanned 30 s ago". |
| **Smart mode OFF** | **not checked at all** | `grep smart_mode backend/app/routers/nfc.py` → **0 matches.** `/scan` returns `"status":"pending"` and *"Please plug in your charger"*. The NUC cannot activate the socket in standalone mode, so the customer plugs in and **nothing happens**, with no signal to ERP. |
| **Pedestal offline** | **not checked at all** | `grep opta_connected` → **0 matches.** Same shape: scan succeeds, nothing can follow. Not hypothetical — this cabinet was silent for 19 days in September. |

### Authorization parity: **does NOT match the local UI — it is broader, by design**

The rule asks whether the ERP endpoint enforces the same rules as the local UI. It does not:

- The gateway mints a **5-minute internal admin JWT** for every proxied call
  (`_make_internal_admin_jwt`). An ERP API key therefore acts with **admin** authority on
  any allowlisted endpoint — strictly more than the local UI's `require_control`.
- The only constraint is the **allowlist**: `allow_bidirectional: True` plus the
  operator-enabled endpoint set in `external_api_config`. Not the role system.

This is coherent with the single-tenant model (one key per marina/ERP, per
`project_single_tenant_per_marina`), and it is why tightening Rule 1 will not break ERP. But
"same authorisation rules" is not an accurate description of today, and the allowlist is
doing all the work — so **which endpoints are enabled is the entire access-control surface
for ERP.**

### What must change

- Give each failure its own status/message: unknown tag vs unresolvable pedestal; socket in
  use vs pending scan held by someone else.
- **Check smart mode and pedestal liveness in `/scan`** and return distinct, actionable
  errors (e.g. `409 "Pedestal is in standalone mode — socket cannot be activated remotely"`,
  `503 "Pedestal offline"`). Promising a customer that plugging in will work when it cannot
  is the worst failure here.
- **Decide** whether ERP should send the pedestal name as a cross-check. My recommendation:
  yes, optional at first and logged on mismatch, then required — it catches mis-provisioned
  tags, which is the one failure the current design cannot detect.
- Document the gateway's admin elevation explicitly in the ERP guide, so the allowlist is
  understood as the access-control boundary it actually is.

---

## Summary

| Rule | Verdict |
|---|---|
| 1 — NFC/QR admin-only | **FAILS** — `require_control` admits marina staff; deliberate per v3.34, but a blanket decision, and three misleading signals hid it |
| 2 — mapping model | **MEETS** — unique, resolvable, no default-socket fallback; removal lacks an audit trail |
| 3 — ERP path | **DIVERGES** — no pedestal name is sent, two unrelated paths, four indistinguishable/missing error cases, and ERP runs with admin authority rather than UI-equivalent rules |

Nothing has been changed. One consolidated plan on request.

---

## ADDENDUM — the real end-to-end flow, and the agreed target (2026-09-27)

Recorded before step 5 so it is not re-derived. **Decisions are the user's; this is the
target for the consolidated access-control change, NOT yet planned or built.**

### How it actually works today, end to end

1. The user scans the NFC tag with the mobile app.
2. The mobile app sends the tag id to **ERP**.
3. **ERP** holds its own mapping tag id → pedestal → socket, and resolves it.
4. ERP sends the pedestal a command to activate that socket.
5. The pedestal replies. **Nothing plugged in → "socket idle", refused.** Plug detected →
   confirmed, ERP tells the app, charging starts.

The mobile app and ERP already work this way. **Our side is what needs finishing.** This
means the audit's "Path B" (gateway → `/api/controls/.../socket/{name}/cmd`) is the REAL
activation path, and raises a question for the plan: **is `/api/nfc/scan` used by this flow
at all, or is it a second integration shape?** To be answered in the plan, not assumed.

### Agreed target: double-bookkeeping, deliberately

ERP sends **both** the tag id **and** the socket it resolved. The pedestal keeps its own
tag → socket mapping and **checks the two agree before acting**.

Two independent records of the same mapping mean a disagreement exposes an error that is
otherwise invisible: a tag stuck on the wrong socket, two labels swapped at installation, or
a wrong socket number typed into ERP. Without the check the pedestal switches the wrong
socket and **the customer pays for a neighbour's power**.

The cost is maintaining the mapping twice, so mismatches are handled deliberately rather
than failing hard everywhere:

| Case | Behaviour |
|---|---|
| tag and socket **agree** | act |
| tag and socket **disagree** | **refuse, and raise an ALARM** — not a quiet error. Physical installation and configuration have diverged and someone must look. |
| pedestal has **no mapping** for that tag | **act on ERP's instruction**, but log that it could not be verified. **Do not block** — an incomplete local mapping must not stop a paying customer charging. |

The mismatch case joins the distinct error responses already identified, so ERP and the app
can tell the user something true.

### Open question for the plan

Whether `/api/nfc/scan` should also carry the pedestal, or whether it is a separate concern
from the ERP activation path and should be left alone.

### Also settled for the plan

- **NFC endpoints are NOT in the ERP catalog at all** (`grep nfc api_catalog.py` → no
  matches), so they are not proxyable through the gateway today. Tightening Rule 1 to admin
  therefore does **not** leave the allowlist as the only barrier for NFC — ERP has no NFC
  path whatsoever. The allowlist-is-the-access-surface point still holds for every endpoint
  that IS on it, and still needs documenting in the ERP guide.
