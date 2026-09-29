# ERP API key — blast radius, and the rotation procedure

**Date:** 2026-09-29 · **Status:** procedure ready; **execution blocked on a precondition
with a date** (§3).

The static `ERP_API_KEY` has been compiled into every installed mobile app build since the
NFC feature shipped, as `EXPO_PUBLIC_ERP_API_KEY` — that prefix is Expo's marker for
"embedded in the bundle". **Treat the current key as known until it is rotated.** Everything
below follows from that.

---

## 1. Blast radius — what the key actually reaches

Established by reading the code, not assumed. Two directions, and the second is the one that
was missing from the access-control plan.

### 1.1 Inbound — exactly four endpoints

`require_erp_api_key` gates these and nothing else:

| Endpoint | What it does | Object check (v3.43) |
|---|---|---|
| `POST /api/nfc/scan` | pre-registers intent to charge | identity from the principal |
| `GET /api/nfc/session/{id}` | session status incl. energy and estimated cost | owner only → 404 |
| `GET /api/nfc/sessions/by-user/{user_id}` | all sessions for one user id | own id only → 403 |
| `POST /api/nfc/session/{id}/stop` | ends a live charging session | owner only → 404 |

All four are now object-guarded (`e7a5e45`), which is why the key being public is a
containable problem rather than an open door. Before that commit it was an open door.

### 1.2 NOT reachable with this key

Worth stating explicitly, because "an API key leaked" invites worst-case assumptions:

- **The ERP gateway** — separate credential (Bearer JWT, `role="external_api"` /
  `"api_client"`), and it already has a rotate-key endpoint of its own. Unaffected.
- **Every operator endpoint** — operator JWT plus role checks.
- **Every customer endpoint** — customer JWT.
- Camera streams, MQTT, admin settings, billing configuration, user management, guard.

### 1.3 Outbound — the key is also **our identity to ERP**

This is the part that changes the picture, and it was not in the plan:

```
backend/app/services/erp_webhook.py:56
    headers={"X-API-Key": settings.erp_api_key or "", ...}
```

`post_erp_event()` sends **the same key** to `settings.erp_webhook_url` on socket-activated,
60-second telemetry and session-ended events. So this is a **bidirectional shared secret**: a
public inbound key is also a public outbound identity.

Consequence: a holder of the key can attempt to impersonate this NUC to ERP's webhook and post
forged session events — activated, telemetry, ended. On ERP's side that is a billing-corruption
path, and it is *outside* anything we can guard from here.

Two honest caveats:

- **Whether ERP validates that header is on ERP's side, and I cannot verify it from this
  codebase.** If ERP does validate it, the forgery path above is real. If ERP ignores it, their
  webhook has no authentication at all, which is a different and larger problem worth raising
  with them either way.
- The webhook URL lives in `.env`, not in the app bundle, so an attacker needs that too. That
  is obscurity, not a control, and should not be counted as mitigation.

### 1.4 Not in git

Checked: no `.env` file is tracked (`git ls-files` shows only `*.env.example`), and the one
commit matching `EXPO_PUBLIC_ERP_API_KEY` (`0f0a5c5`) contains the variable name and the
`setup-env.js` logic, never a value. **The key is in shipped bundles, not in the repository.**

---

## 2. Why rotation cannot simply be done now

Rotation is one line in `.env` plus a backend restart. The problem is who else holds the key:

**The shipped mobile app uses it for `POST /api/nfc/scan`.** Rotate today and NFC charging in
Krk breaks — every scan returns 401 (`mobile/app/(app)/scan.tsx:112` shows the app's own
error string for exactly that) — until the app is rebuilt and redistributed.

So "rotate now" and "do not couple rotation to an app release" cannot both hold while the app
still needs the key. The resolution is to remove the dependency first.

---

## 3. The sequence, with dates

| # | Step | Target date | Blocks |
|---|---|---|---|
| 1 | **ERP takes over `POST /api/nfc/scan`** on the mode-1 path, so no shipped client needs the key | **2026-10-31** | step 2 |
| 2 | **Rotate the key** (§4) | **2026-11-07** | — |
| 3 | **Stage 2**: the app gets a per-customer credential for mode 2 | 2026-12-15 | — |

**The dates are the point.** A rotation blocked on a precondition with no date is a rotation
that never happens, and the key is public in the meantime. These are proposals — change them,
but do not remove them.

Step 1 is not a detour to enable step 2: it *is* the mode-1 end state already approved
(access-control plan decision 11 — ERP server-to-server only, no direct app path). The rotation
comes free with work that was happening anyway, and nothing breaks in Krk.

### Precondition, stated plainly

> **§4 must not be executed until no shipped client depends on the key.**
>
> Verify, do not assume: watch the backend log for `/api/nfc/scan` requests and confirm they
> originate from ERP's address and not from phones. Until that is true, rotating breaks
> customer charging.

---

## 4. The rotation procedure

Ten minutes, reversible, and the marina keeps working throughout **if the precondition holds**.

### 4.1 Before

```bash
ssh <nuc>
sudo grep -c ERP_API_KEY /opt/cloud-iot/backend/.env      # expect 1
sudo journalctl -u cloud-iot-backend --since "24 hours ago" \
  | grep -c "POST /api/nfc/scan"
```

**STOP** if scans are still arriving from phones rather than ERP — the precondition in §3 has
not been met.

### 4.2 Generate

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
```

48 bytes, URL-safe. It is compared with `hmac.compare_digest`
(`backend/app/auth/erp_api_key.py:28`), so length costs nothing.

### 4.3 Coordinate — do this before changing anything

Give the new key to the ERP side and agree a cutover minute. The key authenticates **both**
directions (§1.3), so ERP needs it for two things: sending `X-API-Key` to us, and validating
the header we send them. Changing one side only breaks that side.

### 4.4 Apply

```bash
sudo cp /opt/cloud-iot/backend/.env ~/env_backup_$(date +%F_%H%M).txt   # rollback
sudo sed -i 's/^ERP_API_KEY=.*/ERP_API_KEY=<NEW KEY>/' /opt/cloud-iot/backend/.env
sudo grep ERP_API_KEY /opt/cloud-iot/backend/.env       # confirm, then:
sudo systemctl restart cloud-iot-backend
```

### 4.5 Verify — all four, and the old key must fail

```bash
# the new key is accepted (404 is fine; 401 is not)
curl -s -o /dev/null -w "new key -> %{http_code}\n" \
  -H "X-API-Key: <NEW KEY>" localhost:8000/api/nfc/session/999999

# the OLD key is refused — this is the assertion that matters
curl -s -o /dev/null -w "old key -> %{http_code}\n" \
  -H "X-API-Key: <OLD KEY>" localhost:8000/api/nfc/session/999999
```

Expect `new key -> 404` and **`old key -> 401`**. A 404 for the old key means the restart did
not pick up the change.

Then confirm the outbound direction, which §1.3 is about:

```bash
sudo journalctl -u cloud-iot-backend --since "10 min ago" | grep -i "ERP webhook"
```

**No `delivery failed` lines.** If ERP now rejects our header, that is what appears here — and
it means step 4.3 was not completed on their side.

### 4.6 Rollback

```bash
sudo cp ~/env_backup_<stamp>.txt /opt/cloud-iot/backend/.env
sudo systemctl restart cloud-iot-backend
```

The old key works again immediately. Nothing else is touched — no schema change, no data.

---

## 5. After rotation

- Delete the old key from wherever it is written down. It stays compromised for ever.
- `mobile/.env` should no longer contain `EXPO_PUBLIC_ERP_API_KEY` at all. Until Stage 2 lands,
  `mobile/scripts/setup-env.js` still preserves that variable across runs, so **remove it there
  too** or the next developer setup silently reintroduces a dead key and a confusing 401.
- Consider whether the two directions should share a secret at all. An inbound key and an
  outbound key are different credentials with different exposure; one value for both is what
  turned a leaked inbound gate into a forgeable outbound identity. Splitting them is a small
  change and the right end state.
