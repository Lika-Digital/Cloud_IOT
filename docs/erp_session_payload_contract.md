# ERP session payload — contract

**Version:** v3.47 · **Date:** 2026-10-11 · **Cabinet:** MAR_KRK_ORM_01 and every cabinet on `main`

This is the contract for the per-session payload the pedestal sends to the ERP. Hand it to
whoever is building the ERP side.

**Endpoints that return it**

| | |
|---|---|
| `GET /api/nfc/session/{id}` | one session |
| `GET /api/nfc/sessions/by-user/{user_id}` | that user's sessions, newest first |
| ERP webhook (`session_created` / `session_updated` / `session_completed`) | pushed, when `webhook_url` is configured |

All three are built by one function, `nfc_service.build_session_payload`, so they cannot
disagree.

---

## The one rule

> **The cabinet sends a consumption figure, the two meter readings it is the difference of,
> and a label saying how it was derived. It never substitutes a different number when the
> figure is unavailable, and it never prices anything.**

Everything below follows from that.

---

## The 16 keys

| key | type | notes |
|---|---|---|
| `session_id` | int | our primary key; stable |
| `cabinet_id` | string \| null | e.g. `MAR_KRK_ORM_01` — the `opta_client_id` |
| `socket_id` | string \| null | **`Q1`–`Q4`** for electricity, **`V1`–`V2`** for water. Reconcile on this string, never on the bare number — `V1` and `Q1` are both `socket_id = 1` internally and the prefix is the only thing that distinguishes them |
| `session_type` | `"electricity"` \| `"water"` | so you need not parse the outlet name |
| `customer_id` | string \| null | **your** `user_id`, as supplied to `POST /api/nfc/scan`. Stored as `nfc_user_id` |
| `status` | `"active"` \| `"ended"` | |
| `activated_at` | ISO 8601 Z | |
| `duration_minutes` | float | |
| **`energy_kwh`** | **float \| null** | kWh for this session. Electricity sessions only; always `null` on water |
| **`water_liters`** | **float \| null** | litres for this session. Water sessions only; always `null` on electricity |
| `meter_energy_start_kwh` | float \| null | the meter's cumulative register when the session opened |
| `meter_energy_end_kwh` | float \| null | …and when it closed |
| `meter_water_start_l` | float \| null | the valve's cumulative register when the session opened |
| `meter_water_end_l` | float \| null | …and when it closed |
| **`consumption_source`** | string \| null | how the figure was derived — see below |
| **`power_kw_current`** | **float \| null** | instantaneous power, live reading, not a session total |

There is no `estimated_cost` and no price of any kind. See *Why there is no price*.

---

## The five nullable fields, and what you must do with them

`energy_kwh` · `water_liters` · `meter_*` registers · `consumption_source` · `power_kw_current`

### A null consumption figure means DO NOT BILL THIS SESSION

It does **not** mean zero.

```js
// WRONG — and dangerous, because it is silent
const cost = session.energy_kwh * tariff;     // null * 0.30 === 0 in JavaScript

// RIGHT
if (session.energy_kwh === null) {
    flagForReview(session);                   // not billable from meter data
} else {
    const cost = session.energy_kwh * tariff;
}
```

JavaScript coerces `null` to `0` in arithmetic, so an unvalidated consumer turns an honest
"we do not know" into a confident charge of zero. Python raises `TypeError` instead, which is
noisier and therefore safer. **Validate; do not multiply.**

This matters because on a cabinet whose register path has not yet produced a figure, **most
sessions carry null**. That is the honest state, not an error.

### `null` and `"unknown"` are different, and both are meaningful

| `consumption_source` | meaning |
|---|---|
| `"register"` | the figure is `end − start` of the meter's own cumulative register. Normal, and checkable — recompute it from the two `meter_*` fields |
| `"integrated_legacy"` | the old power × time integral. **Closed-ended**: only sessions already running when v3.43 deployed, which therefore have no opening reading. Never issued for a session started after the cutoff. Treat as approximate |
| `"unknown"` | **we tried and could not derive it.** A register was unreadable at one boundary. The figure is `null` and cannot be billed from meter data |
| `null` | **nothing has derived it yet.** Either the session is still open, or it predates the field. Not a failure — an absence |

The distinction is operational: `"unknown"` is terminal and should be investigated;
`null` on an active session simply resolves when the session closes.

### `power_kw_current: null` is not an idle socket

`null` means the pedestal **refused** the meter's power reading as physically impossible — the
meter reported more real power than voltage × current permits, so the value was discarded
rather than passed on. `0.0` means the socket genuinely measured no draw. Do not render them
the same way.

This is live today on cabinet 1: two of four sockets report power 35–88× above their apparent
power bound, and their readings are refused at source.

---

## Recompute our figures — please

Both boundary readings are in the payload so you do not have to trust ours:

```
energy_kwh   should equal   meter_energy_end_kwh − meter_energy_start_kwh
water_liters should equal   meter_water_end_l   − meter_water_start_l
```

When `consumption_source == "register"` those hold by construction. **If they ever disagree,
that is a fault worth raising with us** — two independent records of the same fact are worth
far more than one, and a record only one side holds is not a check on anything.

The same property is on the cabinet's weekly consumption report: every figure is printed
beside the two readings it derives from, so it can be recomputed by hand.

---

## Why there is no price

Billing is the ERP's job and always has been. The pedestal measures and reports; it does not
price. The cabinet's own tariff configuration survives only from an earlier mobile-app phase
that does not talk to the cabinet any more.

The payload used to carry `estimated_cost`. It was removed in v3.47 rather than made nullable,
because the defect that prompted this entire contract **was a price**: when a session had no
derivable figure, the payload substituted the outlet's *lifetime cumulative register* into the
per-session field and then priced it. On socket 1 of cabinet 1 that would have reported
**481.76 kWh** as one session's consumption, with a cost to match, and the payload carried no
start register for anyone to check it against.

A nullable price field would invite that dependency back. Send us consumption; price it
yourselves.

---

## What changed in v3.47, for an existing consumer

| field | before | after |
|---|---|---|
| `energy_kwh` | a number — **possibly the socket's lifetime total** | the session delta, or `null` |
| `water_liters` | a number — **possibly the valve's lifetime total** | the session delta, or `null` |
| `power_kw_current` | `0.0` when the reading was refused | `null` when refused |
| `estimated_cost` | a number | **removed** |
| `meter_energy_start_kwh` / `_end_kwh` | — | **new** |
| `meter_water_start_l` / `_end_l` | — | **new** |
| `consumption_source` | — | **new** |

`session.py:87` has described `consumption_source` as *"part of the ERP contract,
permanently"* since v3.43. Until v3.47 the payload did not carry it, so the comment described
a contract the code did not keep. Adding it closes that gap.

The key set is pinned by `tests/backend/test_nfc_six_tag_model.py::test_tc_six_13g_the_payload_key_set_is_exactly_the_documented_contract`.
If that test fails, this document is updated in the same commit.

---

## Authentication

`X-API-Key` on the `/api/nfc/*` endpoints. This is a separate channel from the API Gateway's
Bearer token — do not mix them. The Gateway (`/api/ext/*`) is for the catalogued read and
control endpoints; NFC session data has its own path.
