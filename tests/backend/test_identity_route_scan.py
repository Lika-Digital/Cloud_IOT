"""No operator route hands a non-admin a customer identity key — the systematic scan, 2026-10-12.

WHY THIS EXISTS. Three times on 2026-10-12 a route that gave marina staff customer data turned up
OUTSIDE the agreed scope (Customers/Contracts, the report files, then reviews/service orders/
berth calendar). The owner asked for one systematic pass over EVERY operator route, by search
rather than by anyone's list — and for it to stay a test, so a fourth one fails the gate.

TWO SIGNALS, because neither alone is enough:
  static   the declared response_model, walked recursively, names a key from
           auth/identity_redaction.IDENTITY_KEYS
  dynamic  a GET as a monitor, over seeded data that HAS identity on it, returns one at any depth
           (many routes return a plain dict with no response_model)

A non-admin route that shows a key must be either in REDACTED_IN_HANDLER (declares the keys but
strips them — proven by the dynamic signal being empty) or in AWAITING_OWNER with a reason. Every
other hit fails. Admin-only, customer-only and ERP-key routes are out of scope: the first is the
owner's line, the other two are not marina staff.

Not covered, said so: bodies that are not JSON (images, video, PDFs) and GETs that cannot answer
200 here (no camera file, no trained model) — they get only the static signal.

TC-IDR-09 FAILS on the code before the three locks of 2026-10-12 (shown).
"""
from __future__ import annotations

import re
import typing
from datetime import datetime, timedelta

from conftest import TestSession as _S, TestUserSession as _US
from test_rest_auth import _identity_names
from test_identity_redaction import KEYS, _h, _keys_anywhere

OUT_OF_SCOPE_DEPS = {"require_admin", "require_customer", "require_erp_api_key"}

# Declares identity keys in its response model, strips them for non-admin in the handler (part B).
REDACTED_IN_HANDLER = {
    ("GET", "/api/sessions"),
    ("GET", "/api/sessions/active"),
    ("GET", "/api/sessions/pending"),
    ("GET", "/api/sessions/{session_id}"),
}

# Found by this scan, NOT yet decided. Each line is an open door with its reason.
AWAITING_OWNER: dict[tuple[str, str], str] = {
    ("POST", "/api/controls/{session_id}/allow"):
        "action reply is the full SessionResponse (customer_id, nfc_user_id, erp_ref) to monitor_control",
    ("POST", "/api/controls/{session_id}/deny"): "same as allow",
    ("POST", "/api/controls/{session_id}/stop"): "same as allow",
    ("POST", "/api/controls/sockets/{pedestal_id}/{socket_id}/approve"): "same as allow",
}

PARAMS = {"pedestal_id": "1", "socket_id": "1", "valve_id": "1", "socket_name": "Q1",
          "valve_name": "V1", "cabinet_id": "IDR09_CAB", "filename": "x.jpg", "alarm_id": "1",
          "camera_id": "1", "event_id": "1", "detection_id": "1", "marina_id": "1",
          "path": "pedestals"}
QUERY = {"/api/predictions/electricity": "?duration_minutes=60",
         "/api/predictions/water": "?duration_minutes=60",
         "/api/berths/availability": "?check_in=2026-10-12&check_out=2026-10-20"}


def _model_keys(tp, seen=None) -> set[str]:
    seen = set() if seen is None else seen
    found: set[str] = set()
    for a in typing.get_args(tp) or ():
        found |= _model_keys(a, seen)
    fields = getattr(tp, "model_fields", None)
    if fields and tp not in seen:
        seen.add(tp)
        for name, f in fields.items():
            if name in KEYS:
                found.add(name)
            found |= _model_keys(f.annotation, seen)
    return found


def _seed() -> tuple[int, int]:
    """Identity on every kind of row an operator route might show."""
    from app.models.session import Session
    from app.models.pedestal_config import PedestalConfig
    from app.auth.berth_models import Berth, BerthReservation
    db = _S()
    try:
        s = Session(pedestal_id=1, socket_id=1, type="electricity", status="active",
                    started_at=datetime.utcnow() - timedelta(hours=1), energy_kwh=1.0,
                    customer_id=1, nfc_user_id="IDR09-NFC", erp_ref="IDR09-ERP")
        db.add(s)
        cfg = db.query(PedestalConfig).filter(PedestalConfig.pedestal_id == 1).first()
        if cfg is None:
            cfg = PedestalConfig(pedestal_id=1)
            db.add(cfg)
        cfg.opta_client_id = cfg.opta_client_id or "IDR09_CAB"
        PARAMS["cabinet_id"] = cfg.opta_client_id
        db.commit()
        sid = s.id
    finally:
        db.close()
    udb = _US()
    try:
        b = Berth(name="IDR09-B", pedestal_id=1)
        udb.add(b)
        udb.commit()
        udb.add(BerthReservation(berth_id=b.id, customer_id=1,
                                 check_in_date=datetime.utcnow().date(),
                                 check_out_date=(datetime.utcnow() + timedelta(days=2)).date(),
                                 status="confirmed"))
        udb.commit()
        bid = b.id
    finally:
        udb.close()
    return sid, bid


def _scan(client) -> list[tuple[str, str, set[str], set[str]]]:
    from app.main import app
    sid, bid = _seed()
    hdr = _h("monitor")
    out = []
    for r in app.routes:
        path = getattr(r, "path", "")
        if not path.startswith("/api") or _identity_names(r) & OUT_OF_SCOPE_DEPS:
            continue
        for m in sorted(getattr(r, "methods", []) or []):
            if m in ("HEAD", "OPTIONS"):
                continue
            static = _model_keys(getattr(r, "response_model", None))
            dynamic: set[str] = set()
            if m == "GET":
                url = re.sub(r"\{([^}:]+)(:[^}]*)?\}",
                             lambda x: {"session_id": str(sid), "berth_id": str(bid)}.get(
                                 x.group(1), PARAMS.get(x.group(1), "1")), path) + QUERY.get(path, "")
                resp = client.get(url, headers=hdr)
                if "json" in resp.headers.get("content-type", ""):
                    dynamic = _keys_anywhere(resp.json())
            out.append((m, path, static, dynamic))
    return out


def test_tc_idr_09_no_operator_route_gives_staff_identity(client):
    rows = _scan(client)
    assert len(rows) > 100, f"the scan saw only {len(rows)} routes — it is not looking"
    bad = []
    for m, path, static, dynamic in rows:
        key = (m, path)
        if key in REDACTED_IN_HANDLER:
            if dynamic:
                bad.append(f"{m} {path}: listed as redacted but a monitor got {sorted(dynamic)}")
            continue
        if (static or dynamic) and key not in AWAITING_OWNER:
            bad.append(f"{m} {path}: static={sorted(static)} dynamic={sorted(dynamic)}")
    assert not bad, ("Non-admin operator routes that give customer identity (rule 13):\n  "
                     + "\n  ".join(bad))


def test_tc_idr_09b_the_lists_have_no_stale_entries(client):
    from app.main import app
    live = {(m, getattr(r, "path", "")) for r in app.routes for m in (getattr(r, "methods", []) or [])}
    stale = sorted(k for k in set(AWAITING_OWNER) | REDACTED_IN_HANDLER if k not in live)
    assert not stale, f"listed routes that no longer exist: {stale}"
