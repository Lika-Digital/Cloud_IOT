"""/scan returns the REAL berth id, and the cabinet label under its own name — 2026-10-12.

OWNER'S DECISION (breaking change for the ERP, item 2 of the ERP list): `/scan` answered
`berth_id` with `pedestal_configs.berth_ref` — ONE free-text label per cabinet, the same for all
four berths. A wrong value under a right-looking name is worse than a break, because the ERP gets
data that looks correct. The occupancy webhook already sends `berth_id` as the real `berths.id`,
so the same field name meant two things in one integration.

  TC-SBI-01  a socket assigned to a berth: `berth_id` is that berth's id (int)
  TC-SBI-02  an unassigned socket: `berth_id` is null — not known, never the label
  TC-SBI-03  a water outlet: `berth_id` is null — water has no berth (decision 3)
  TC-SBI-04  the cabinet label is still there, under `cabinet_label`; `berth_ref` is not a field
  TC-SBI-05  the admin export carries `energy_intervals.berth_id`, as the LAST CSV column

All five FAIL on the code before this change (shown 2026-10-12): it returned the label as
`berth_id` for every outlet, water included.
The ERP key is generated here, never written down.
"""
from __future__ import annotations

import csv
import io
import secrets
import zipfile
from datetime import datetime

import pytest

from conftest import TestSession as _S

CAB = "MAR_SBI_TEST_01"
LABEL = "PIER-S LABEL"
BERTH = 7171
KEY = secrets.token_hex(16)


@pytest.fixture(autouse=True)
def _erp_key():
    from app.config import settings
    prev = settings.erp_api_key
    settings.erp_api_key = KEY
    yield
    settings.erp_api_key = prev


@pytest.fixture(scope="module")
def pid(client, auth_headers):
    from app.models.pedestal_config import PedestalConfig
    from app.models.socket_config import SocketConfig
    from app.models.berth_assignment import BerthAssignment
    r = client.post("/api/pedestals/", json={"name": "SBI Pedestal", "location": "Dock S",
                                              "data_mode": "real"}, headers=auth_headers)
    assert r.status_code in (200, 201), r.text
    p = r.json()["id"]
    db = _S()
    try:
        cfg = db.query(PedestalConfig).filter(PedestalConfig.pedestal_id == p).first()
        if cfg is None:
            cfg = PedestalConfig(pedestal_id=p)
            db.add(cfg)
        cfg.opta_client_id, cfg.smart_mode, cfg.provisioning_mode = CAB, True, "nfc"
        cfg.berth_ref = LABEL
        for sid in (1, 2, 3, 4):
            if db.query(SocketConfig).filter(SocketConfig.pedestal_id == p,
                                             SocketConfig.socket_id == sid).first() is None:
                db.add(SocketConfig(pedestal_id=p, socket_id=sid, auto_activate=False))
        db.add(BerthAssignment(berth_id=BERTH, pedestal_id=p, socket_id=2,
                               assigned_by="test@test.local"))
        db.commit()
    finally:
        db.close()
    return p


@pytest.fixture(autouse=True)
def _alive_and_clear(pid):
    from app.services.mqtt_handlers import last_heartbeat
    from app.models.nfc_pending_session import NfcPendingSession
    last_heartbeat[pid] = datetime.utcnow()
    db = _S()
    try:
        db.query(NfcPendingSession).filter(NfcPendingSession.cabinet_id == CAB).delete()
        db.commit()
    finally:
        db.close()
    yield
    last_heartbeat.pop(pid, None)


def _scan(client, outlet):
    r = client.post("/api/nfc/scan", headers={"X-API-Key": KEY},
                    json={"cabinet_id": CAB, "outlet": outlet, "erp_ref": f"SBI-{outlet}"})
    assert r.status_code == 200, r.text
    return r.json()


def test_tc_sbi_01_assigned_socket_returns_the_berth_id(client):
    body = _scan(client, "Q2")
    assert body["berth_id"] == BERTH and isinstance(body["berth_id"], int), body


def test_tc_sbi_02_unassigned_socket_returns_null(client):
    assert _scan(client, "Q3")["berth_id"] is None


def test_tc_sbi_03_water_returns_null(client):
    assert _scan(client, "V1")["berth_id"] is None


def test_tc_sbi_04_the_cabinet_label_under_its_own_name(client):
    body = _scan(client, "Q2")
    assert body.get("cabinet_label") == LABEL, body
    assert "berth_ref" not in body, "the label must not be called a berth reference again"


def test_tc_sbi_05_export_carries_berth_id_last(client, auth_headers, pid):
    from app.models.energy_interval import EnergyInterval
    db = _S()
    try:
        db.add(EnergyInterval(pedestal_id=pid, socket_id=2, origin="nfc", berth_ref=LABEL,
                              berth_id=BERTH, interval_start=datetime(2026, 10, 5, 10, 0),
                              interval_end=datetime(2026, 10, 5, 10, 15), kwh=0.4))
        db.commit()
    finally:
        db.close()
    j = client.get("/api/admin/export/usage?date_from=2026-10-05&date_to=2026-10-05",
                   headers=auth_headers)
    assert j.status_code == 200, j.text
    rows = [r for r in j.json()["energy_intervals"] if r.get("berth_ref") == LABEL]
    assert rows and rows[0]["berth_id"] == BERTH, rows
    z = client.get("/api/admin/export/usage?format=csv&date_from=2026-10-05&date_to=2026-10-05",
                   headers=auth_headers)
    assert z.status_code == 200
    with zipfile.ZipFile(io.BytesIO(z.content)) as zf:
        name = next(n for n in zf.namelist() if "interval" in n)
        header = next(csv.reader(io.StringIO(zf.read(name).decode("utf-8-sig"))))
    assert header[-1] == "berth_id", f"berth_id must be the LAST column, header is {header}"
