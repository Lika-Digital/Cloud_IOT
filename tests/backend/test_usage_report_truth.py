"""TC-REP-01..08 — the monthly report says what it measured, and nothing it did not (2026-10-14).

The report printed `energy_kwh or 0.0`: an unmeasured session read "0.000 kWh", was added into the
subtotal as zero, and no line said which figures were meter readings. A download mid-month, or
the 00:xx run on the 1st, froze an incomplete month in a file that was never regenerated.

  TC-REP-01  unknown prints "—", never 0, and a figure without provenance is not reported
  TC-REP-02  a total with ANY unmeasured session prints NO total figure — not a sum with a note
  TC-REP-03  an estimate is labelled, and the total says how much of it is estimated
  TC-REP-04  the staff file has no customer column; staff cannot reach the admin file
  TC-REP-05  a month not over, or with open sessions, is PROVISIONAL and regenerated
  TC-REP-06  a FINAL file is not rewritten; a legacy file (no Status line) is never touched
  TC-REP-07  the monthly job says what it did even when it wrote nothing
  TC-REP-08  each figure is printed beside the two register readings it comes from
"""
from __future__ import annotations

import logging
import re
from datetime import datetime

import pytest

from tests.backend.test_usage_history import (  # same pedestal, same seeding, same reset
    PID, _S, _seed_session, _monitor_headers, _isolate,  # noqa: F401  (_isolate is autouse)
)

QTY = re.compile(r"\d+\.\d+ (kWh|L)\b")


def _text(year=2026, month=5, audience="admin", now=datetime(2026, 7, 1)):
    from app.services import usage_report_service as svc
    db = _S()
    try:
        return svc.build_report_text(db, PID, year, month, audience, now=now)
    finally:
        db.close()


def test_tc_rep_01_unknown_is_a_dash_never_zero():
    _seed_session(1, "electricity", datetime(2026, 5, 3, 9), datetime(2026, 5, 3, 10),
                  kwh=None, source="unknown")
    # A figure WITHOUT provenance (pre-stamp row): not reported as if it had one.
    _seed_session(2, "electricity", datetime(2026, 5, 4, 9), datetime(2026, 5, 4, 10),
                  kwh=7.5, source=None)
    _seed_session(1, "water", datetime(2026, 5, 5, 9), datetime(2026, 5, 5, 10),
                  liters=None, source="unknown")
    t = _text()
    assert "0.000 kWh" not in t and "0.0 L" not in t, t
    assert "7.500 kWh" not in t, "a figure with no consumption_source was reported as measured"
    rows = [l for l in t.splitlines() if re.match(r"\d{4}-\d{2}-\d{2} ", l)]   # session rows only
    assert len(rows) == 3, rows
    assert sum("[not measured]" in l for l in rows) == 2, rows
    assert sum("[not measured (no provenance recorded)]" in l for l in rows) == 1, rows
    assert all("—" in l for l in rows), rows


def test_tc_rep_02_partial_total_prints_no_figure():
    """The owner's condition: "partial" must not be text beside a correct-looking sum.

    Checked two ways, because a mutant can cheat either: no Subtotal/TOTAL line marked PARTIAL
    carries a quantity, AND no line other than a session row carries one — so the sum is not
    smuggled onto a separate "measured so far" line either.
    """
    _seed_session(1, "electricity", datetime(2026, 5, 3, 9), datetime(2026, 5, 3, 10),
                  kwh=2.0, source="register", reg_start=10.0, reg_end=12.0)
    _seed_session(1, "electricity", datetime(2026, 5, 6, 9), datetime(2026, 5, 6, 10),
                  kwh=None, source="unknown")
    t = _text()
    totals = [l for l in t.splitlines() if l.lstrip().startswith(("Subtotal", "TOTAL electricity"))]
    assert len(totals) == 2, totals
    for line in totals:
        assert "PARTIAL - 1 of 2 session(s) not measured" in line, line
        assert not QTY.search(line), f"a figure printed on a PARTIAL total: {line!r}"
    stray = [l for l in t.splitlines()
             if not re.match(r"\d{4}-\d{2}-\d{2} ", l) and QTY.search(l)]
    assert not stray, (
        "a quantity outside the session rows of a PARTIAL report — a partial sum is being "
        f"presented: {stray}")


def test_tc_rep_03_estimate_is_labelled_and_counted():
    _seed_session(1, "electricity", datetime(2026, 5, 3, 9), datetime(2026, 5, 3, 10),
                  kwh=1.0, source="register", reg_start=5.0, reg_end=6.0)
    _seed_session(1, "electricity", datetime(2026, 5, 4, 9), datetime(2026, 5, 4, 10),
                  kwh=0.5, source="integrated_legacy")
    t = _text()
    assert "[estimate - meter not available]  no register reading" in t, t
    assert "TOTAL electricity: 2 session(s), 1.500 kWh (of which 0.500 kWh estimated" in t, t


def test_tc_rep_04_staff_file_has_no_customer_and_staff_cannot_reach_admin(client):
    _seed_session(1, "electricity", datetime(2026, 5, 3, 9), datetime(2026, 5, 3, 10),
                  kwh=1.0, source="register", reg_start=1.0, reg_end=2.0, customer_id=4242)
    staff = _text(audience="staff")
    admin = _text(audience="admin")
    assert "customer" not in staff.lower().replace("no customer column", ""), staff
    assert "4242" not in staff
    assert "customer #4242" in admin

    mon = _monitor_headers()
    r = client.get(f"/api/pedestals/{PID}/usage/staff-reports/2026-05", headers=mon)
    assert r.status_code == 200, r.text
    assert "4242" not in r.text and "STAFF VERSION" in r.text
    assert 'filename="pedestal-%d_2026-05.staff.txt"' % PID in r.headers["content-disposition"]
    assert client.get(f"/api/pedestals/{PID}/usage/reports/2026-05", headers=mon).status_code == 403
    listed = client.get(f"/api/pedestals/{PID}/usage/staff-reports", headers=mon).json()
    assert [x["month"] for x in listed] == ["2026-05"], listed


def test_tc_rep_05_unfinished_month_or_open_session_is_provisional_and_regenerated():
    from app.services import usage_report_service as svc
    _seed_session(1, "electricity", datetime(2026, 8, 3, 9), datetime(2026, 8, 3, 10),
                  kwh=1.0, source="register", reg_start=1.0, reg_end=2.0)
    db = _S()
    try:
        # 24 August: the month is not over (this is how pedestal-1_2026-08.txt was frozen).
        p = svc.get_or_generate(db, PID, 2026, 8, now=datetime(2026, 8, 24, 12))
        first = p.read_text(encoding="utf-8")
        assert "Status: PROVISIONAL - the month was not over" in first
        assert svc.is_provisional(p)
        _seed_session(2, "electricity", datetime(2026, 8, 28, 9), datetime(2026, 8, 28, 10),
                      kwh=3.0, source="register", reg_start=7.0, reg_end=10.0)
        # 1 September 00:05 with a session that started in August still OPEN.
        _seed_session(3, "electricity", datetime(2026, 8, 31, 22), None, kwh=None, status="active")
        p = svc.get_or_generate(db, PID, 2026, 8, now=datetime(2026, 9, 1, 0, 5))
        second = p.read_text(encoding="utf-8")
        assert "3.000 kWh" in second, "a provisional file was served instead of regenerated"
        assert "Status: PROVISIONAL - 1 session(s) that started this month were still open" in second
    finally:
        db.close()


def test_tc_rep_06_final_is_kept_and_legacy_is_never_touched():
    from app.services import usage_report_service as svc
    db = _S()
    try:
        p = svc.get_or_generate(db, PID, 2026, 5, now=datetime(2026, 6, 2))
        assert "Status: FINAL" in p.read_text(encoding="utf-8")
        p.write_text(p.read_text(encoding="utf-8") + "MARK\n", encoding="utf-8")
        assert svc.get_or_generate(db, PID, 2026, 5).read_text(encoding="utf-8").endswith("MARK\n")

        legacy = svc.report_path(PID, 2026, 4)
        legacy.write_text("USAGE REPORT — old\nMonth: 2026-04\nNo completed sessions for this month.\n",
                          encoding="utf-8")
        before = legacy.read_bytes()
        svc.get_or_generate(db, PID, 2026, 4)
        svc.generate_due_reports(db, now=datetime(2026, 5, 2))   # previous month = April
        assert legacy.read_bytes() == before, "a legacy report was regenerated"
    finally:
        db.close()


def test_tc_rep_07_monthly_job_announces_itself_even_when_idle(caplog):
    from app.services import usage_report_service as svc
    db = _S()
    try:
        with caplog.at_level(logging.INFO, logger=svc.logger.name):
            assert svc.generate_due_reports(db, now=datetime(2026, 6, 2)) >= 2   # admin + staff
            caplog.clear()
            assert svc.generate_due_reports(db, now=datetime(2026, 6, 2)) == 0
    finally:
        db.close()
    assert "monthly reports: 0 file(s) written for 2026-05" in caplog.text, caplog.text


def test_tc_rep_08_figure_beside_both_readings():
    _seed_session(3, "water", datetime(2026, 5, 3, 9), datetime(2026, 5, 3, 10),
                  liters=42.0, source="register", reg_start=1000.0, reg_end=1042.0)
    t = _text()
    assert "42.0 L  [meter reading]  register 1000.0 L -> 1042.0 L" in t, t
