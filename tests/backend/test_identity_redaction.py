"""Marina staff never see customer identity — part B, 2026-10-12.

OWNER'S DECISION, binding: MARINA STAFF MUST NOT SEE CUSTOMER DATA. The customer's identity lives
in the ERP; the cabinet shows the session and the consumption, not the customer's name or
identifier. Only admin sees more.

ONE list of identity keys (app.auth.identity_redaction.IDENTITY_KEYS — customer_id,
customer_name, nfc_user_id, erp_ref), applied at the boundary to every client:

  TC-IDR-01  every websocket event in the backend's catalogue reaches a non-admin operator with
             no identity key at ANY depth — and reaches an admin intact (paired)
  TC-IDR-02  GET /api/sessions: monitor sees no identity key; admin does (paired)
  TC-IDR-03  usage history: monitor sees none of the four; admin sees them (the D2 pair — the
             old test asserted only `!= 403`, which cannot tell "redacted" from "present but
             null")
  TC-IDR-04  reconciliation divergence: monitor sees no erp_ref; admin does (paired)
  TC-IDR-05  billing and export are LOCKED to admin, not filtered: the cabinet does not bill —
             the ERP does — and those routes are legacy
  TC-IDR-06  the list itself is the one the owner named

Each refusal/redaction test FAILS on the code before this change (shown 2026-10-12).
Tokens are minted here from the test secret.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from conftest import TestSession as _S, TestUserSession as _US

KEYS = {"customer_id", "customer_name", "nfc_user_id", "erp_ref"}
BACKEND = Path(__file__).resolve().parents[2] / "backend" / "app"


def _keys_anywhere(obj) -> set[str]:
    found: set[str] = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in KEYS:
                found.add(k)
            found |= _keys_anywhere(v)
    elif isinstance(obj, list):
        for x in obj:
            found |= _keys_anywhere(x)
    return found


def _user(role: str) -> tuple[int, str]:
    from app.auth.models import User
    from app.auth.password import hash_password
    email = f"idr-{role}@test.local"
    db = _US()
    try:
        u = db.query(User).filter(User.email == email).first()
        if u is None:
            u = User(email=email, password_hash=hash_password("x-not-used-x"), role=role,
                     is_active=True)
            db.add(u)
            db.commit()
        return u.id, u.email
    finally:
        db.close()


def _token(role: str) -> str:
    from app.auth.tokens import create_access_token
    uid, email = _user(role)
    return create_access_token(uid, email, role)


def _h(role: str) -> dict:
    return {"Authorization": f"Bearer {_token(role)}"}


def _catalogue() -> list[str]:
    """Every literal `"event": "<name>"` the backend emits."""
    names: set[str] = set()
    for p in BACKEND.rglob("*.py"):
        names |= set(re.findall(r'"event":\s*"([a-z_]+)"', p.read_text(encoding="utf-8")))
    assert len(names) > 20, f"the catalogue scan found too little: {sorted(names)}"
    return sorted(names)


# ═══ TC-IDR-01 — the broadcast ════════════════════════════════════════════════

def test_tc_idr_01_every_event_reaches_staff_without_identity_and_admin_intact(client):
    from app.services.websocket_manager import ws_manager
    events = _catalogue()
    payload_for = lambda ev: {  # noqa: E731
        "event": ev,
        "data": {"customer_id": 7, "keep": 1,
                 "nested": {"erp_ref": "ERP-X", "rows": [{"nfc_user_id": "u@x", "customer_name": "N",
                                                          "kwh": 1.5}]}},
    }
    with client.websocket_connect("/ws", subprotocols=["bearer", _token("monitor")]) as mon, \
         client.websocket_connect("/ws", subprotocols=["bearer", _token("admin")]) as adm:
        for ev in events:
            client.portal.call(ws_manager.broadcast, payload_for(ev))
            got_m = mon.receive_json()
            got_a = adm.receive_json()
            assert got_m["event"] == ev and got_a["event"] == ev
            leaked = _keys_anywhere(got_m)
            assert not leaked, f"event {ev!r} delivered {sorted(leaked)} to a monitor"
            assert got_m["data"]["keep"] == 1 and got_m["data"]["nested"]["rows"][0]["kwh"] == 1.5, (
                "redaction removed data that is not identity")
            assert _keys_anywhere(got_a) == KEYS, f"event {ev!r}: admin lost identity keys"


# ═══ REST fixtures ════════════════════════════════════════════════════════════

@pytest.fixture
def seeded_session():
    from app.models.session import Session
    db = _S()
    try:
        s = Session(pedestal_id=1, socket_id=4, type="electricity", status="completed",
                    started_at=datetime.utcnow() - timedelta(hours=3),
                    ended_at=datetime.utcnow() - timedelta(hours=2),
                    energy_kwh=2.5, customer_id=None, nfc_user_id="idr-nfc-user",
                    erp_ref="IDR-ERP-REF")
        db.add(s)
        db.commit()
        sid = s.id
    finally:
        db.close()
    yield sid
    db = _S()
    try:
        db.query(Session).filter(Session.id == sid).delete()
        db.commit()
    finally:
        db.close()


# ═══ TC-IDR-02 — /api/sessions ════════════════════════════════════════════════

def test_tc_idr_02_sessions_list_is_redacted_for_staff(client, seeded_session):
    for path in ("/api/sessions", f"/api/sessions/{seeded_session}"):
        mon = client.get(path, headers=_h("monitor"))
        adm = client.get(path, headers=_h("admin"))
        assert mon.status_code == 200 and adm.status_code == 200, (mon.text, adm.text)
        assert not _keys_anywhere(mon.json()), f"{path} gave a monitor {_keys_anywhere(mon.json())}"
        assert {"nfc_user_id", "erp_ref"} <= _keys_anywhere(adm.json()), f"{path}: admin lost them"


# ═══ TC-IDR-03 — usage history (the D2 pair) ══════════════════════════════════

def test_tc_idr_03_usage_history_d2_pair(client, seeded_session):
    url = "/api/pedestals/1/usage/history?socket_id=4"
    mon = client.get(url, headers=_h("monitor")).json()
    adm = client.get(url, headers=_h("admin")).json()
    assert mon and adm, "the seeded session is missing from history"
    assert not _keys_anywhere(mon), f"a monitor got {_keys_anywhere(mon)} — present-but-null is not redacted"
    assert {"customer_id", "customer_name", "nfc_user_id"} <= _keys_anywhere(adm), (
        "admin rows must carry the identity fields")


# ═══ TC-IDR-04 — reconciliation divergence ════════════════════════════════════

def test_tc_idr_04_divergence_is_redacted_for_staff(client, seeded_session):
    mon = client.get("/api/nfc/reconciliation/divergence", headers=_h("monitor"))
    adm = client.get("/api/nfc/reconciliation/divergence", headers=_h("admin"))
    assert mon.status_code == 200 and adm.status_code == 200
    assert not _keys_anywhere(mon.json()), f"a monitor got {_keys_anywhere(mon.json())}"
    assert "erp_ref" in _keys_anywhere(adm.json())


# ═══ TC-IDR-05 — billing and export locked ════════════════════════════════════

LOCKED = ["/api/billing/config", "/api/billing/daily", "/api/billing/spending",
          "/api/billing/spending/detail", "/api/billing/customers", "/api/admin/export/usage"]


@pytest.mark.parametrize("url", LOCKED)
@pytest.mark.parametrize("role", ["monitor", "monitor_control"])
def test_tc_idr_05_billing_and_export_are_admin_only(client, url, role):
    assert client.get(url, headers=_h(role)).status_code == 403, f"{role} reached {url}"


@pytest.mark.parametrize("url", LOCKED)
def test_tc_idr_05b_admin_still_reaches_them(client, url):
    assert client.get(url, headers=_h("admin")).status_code != 403


@pytest.mark.parametrize("role", ["monitor", "monitor_control"])
def test_tc_idr_05c_the_billing_write_is_admin_only_too(client, role):
    body = {"kwh_price_eur": 0.5, "liter_price_eur": 0.01}
    assert client.put("/api/billing/config", json=body, headers=_h(role)).status_code == 403


# ═══ TC-IDR-06 ════════════════════════════════════════════════════════════════

def test_tc_idr_06_the_list_is_the_owners(client):
    from app.auth.identity_redaction import IDENTITY_KEYS
    assert set(IDENTITY_KEYS) == KEYS
