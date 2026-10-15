"""TC-L3-01..02 — the rows L3 history renders carry their provenance (block 4, 2026-10-15).

L3 history (berth detail -> History) reads `/api/pedestals/{id}/usage/history`, which returned
`energy_kwh` / `water_liters` with no `consumption_source` and no register readings: a figure on
a screen with nothing saying whether the meter measured it. The monthly report was fixed for
exactly that (TC-REP-01..08); the screen must say the same thing about the same session.
Session rows, not interval rows — the §4.4 exception, for the same reason as the report.

  TC-L3-01  each row carries consumption_source and both register readings of its resource
  TC-L3-02  staff get them too, and still no identity
"""
from __future__ import annotations

from datetime import datetime

from tests.backend.test_usage_history import (  # same pedestal, same seeding, same reset
    PID, _seed_session, _monitor_headers, _isolate,  # noqa: F401  (_isolate is autouse)
)


def _rows(client, headers, **params):
    r = client.get(f"/api/pedestals/{PID}/usage/history", params=params, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def test_tc_l3_01_rows_carry_provenance_and_readings(client, auth_headers):
    e = _seed_session(3, "electricity", datetime(2026, 9, 3, 9), datetime(2026, 9, 3, 10),
                      kwh=1.25, source="register", reg_start=100.0, reg_end=101.25)
    w = _seed_session(1, "water", datetime(2026, 9, 4, 9), datetime(2026, 9, 4, 10),
                      liters=None, source="unknown")
    rows = {r["session_id"]: r for r in _rows(client, auth_headers)}
    assert rows[e]["consumption_source"] == "register"
    assert (rows[e]["register_start"], rows[e]["register_end"]) == (100.0, 101.25)
    assert rows[w]["consumption_source"] == "unknown"
    assert (rows[w]["register_start"], rows[w]["register_end"]) == (None, None)


def test_tc_l3_02_staff_get_provenance_not_identity(client):
    _seed_session(3, "electricity", datetime(2026, 9, 3, 9), datetime(2026, 9, 3, 10),
                  kwh=1.25, source="register", reg_start=100.0, reg_end=101.25,
                  customer_id=4242, nfc_user_id="TAG-1")
    (row,) = _rows(client, _monitor_headers(), resource="electricity", socket_id=3)
    assert row["consumption_source"] == "register" and row["register_end"] == 101.25
    assert not {"customer_id", "customer_name", "nfc_user_id", "erp_ref"} & set(row), row
