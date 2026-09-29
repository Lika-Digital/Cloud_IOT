"""
ERP reconciliation — divergence, and silence that means something (v3.43)
=======================================================================

Decision 10. Our records could drift from ERP's **silently**: each side kept its own totals and
nothing asserted they agreed. `by-user` existed so ERP *could* reconcile, but nothing required it
to and nothing noticed if it stopped.

**The tests that matter most are TC-ERPR-04 and TC-ERPR-05**, because they are about whether the
alarm survives contact with a real marina. "ERP has not reconciled in seven days" has two
completely different causes:

* **ERP stopped reconciling** while charges piled up — the integration is down, the marina is
  billing nothing, someone must act today.
* **Nothing happened worth reconciling** — a marina that is quiet in winter. Correct and
  expected.

One alarm for both gets muted within a month, and then the first cause goes unnoticed too. So
there are three states and only one of them alarms.

  TC-ERPR-01  an ERP read stamps last_reconciled_at; a CUSTOMER read does not
  TC-ERPR-02  by-user stamps every session it returns — that is the reconciliation event
  TC-ERPR-03  the divergence list is oldest-first and excludes live sessions
  TC-ERPR-04  backlog + silence alarms, and the message says what it MEANS
  TC-ERPR-05  quiet marina with nothing waiting does NOT alarm
  TC-ERPR-06  recent reconciliation with a backlog does not alarm
  TC-ERPR-07  MODE 2 never alarms — there is no ERP to be silent
  TC-ERPR-08  an in-progress session is not a backlog item
"""
from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

TEST_DB = "sqlite:///./tests/test_pedestal.db"
_engine = create_engine(TEST_DB, connect_args={"check_same_thread": False})
_S = sessionmaker(autocommit=False, autoflush=False, bind=_engine)

ERP_KEY = "test-erp-key-recon"
CAB = "TST_RECON_CAB"


@pytest.fixture(autouse=True)
def _erp_key():
    from app.config import settings
    prev = settings.erp_api_key
    prev_mode = settings.nfc_direct_client_mode
    settings.erp_api_key = ERP_KEY
    settings.nfc_direct_client_mode = False
    yield
    settings.erp_api_key = prev
    settings.nfc_direct_client_mode = prev_mode


def _erp() -> dict:
    return {"X-API-Key": ERP_KEY}


@pytest.fixture(scope="module")
def recon_pid(client, auth_headers):
    from app.models.pedestal_config import PedestalConfig

    r = client.post("/api/pedestals/", json={
        "name": "Reconciliation Pedestal", "location": "Recon Dock", "data_mode": "real",
    }, headers=auth_headers)
    pid = r.json()["id"]
    db = _S()
    try:
        cfg = db.query(PedestalConfig).filter(PedestalConfig.pedestal_id == pid).first()
        if cfg is None:
            cfg = PedestalConfig(pedestal_id=pid)
            db.add(cfg)
        cfg.opta_client_id = CAB
        cfg.smart_mode = True
        db.commit()
    finally:
        db.close()
    return pid


@pytest.fixture(autouse=True)
def _clean(recon_pid):
    from app.models.active_alarm import ActiveAlarm
    from app.models.session import Session
    from app.services.erp_reconciliation import ALARM_TYPE

    db = _S()
    try:
        db.query(Session).filter(Session.pedestal_id == recon_pid).delete()
        db.query(ActiveAlarm).filter(ActiveAlarm.alarm_type == ALARM_TYPE).delete()
        db.commit()
    finally:
        db.close()
    yield


def _session(pid: int, *, user: str = "erp-recon-user", status: str = "completed",
             started_days_ago: float = 1.0, energy: float = 5.0,
             reconciled_days_ago: float | None = None, socket_id: int = 1) -> int:
    from app.models.session import Session

    db = _S()
    try:
        s = Session(
            pedestal_id=pid, socket_id=socket_id, type="electricity", status=status,
            started_at=datetime.utcnow() - timedelta(days=started_days_ago),
            ended_at=None if status == "active"
            else datetime.utcnow() - timedelta(days=started_days_ago - 0.01),
            energy_kwh=energy, nfc_user_id=user,
            last_reconciled_at=None if reconciled_days_ago is None
            else datetime.utcnow() - timedelta(days=reconciled_days_ago),
        )
        db.add(s)
        db.commit()
        return s.id
    finally:
        db.close()


def _reconciled_at(session_id: int):
    from app.models.session import Session

    db = _S()
    try:
        return db.get(Session, session_id).last_reconciled_at
    finally:
        db.close()


def _states(pid: int):
    from app.services.erp_reconciliation import status_by_pedestal

    db = _S()
    try:
        return {s.pedestal_id: s for s in status_by_pedestal(db)}.get(pid)
    finally:
        db.close()


def _alarms():
    from app.models.active_alarm import ActiveAlarm
    from app.services.erp_reconciliation import ALARM_TYPE

    db = _S()
    try:
        return db.query(ActiveAlarm).filter(ActiveAlarm.alarm_type == ALARM_TYPE).all()
    finally:
        db.close()


async def _run_check():
    from app.services.erp_reconciliation import check_reconciliation_silence

    with patch("app.database.SessionLocal", _S), \
         patch("app.services.alarm_service.SessionLocal", _S):
        await check_reconciliation_silence()


# ═══ TC-ERPR-01 ══════════════════════════════════════════════════════════════

def test_tc_erpr_01_erp_read_stamps_but_customer_read_does_not(client, recon_pid):
    """The distinction the whole detector rests on.

    A customer opening the app to check their charge is not the billing system reconciling.
    Stamping both would silence the silence detector every time anyone looked at their own
    session — the alarm would then only fire at marinas with no app users.
    """
    sid = _session(recon_pid)
    assert _reconciled_at(sid) is None

    # Machine caller — this IS reconciliation.
    r = client.get(f"/api/nfc/session/{sid}", headers=_erp())
    assert r.status_code == 200, r.text
    stamped = _reconciled_at(sid)
    assert stamped is not None, "an ERP read did not record that reconciliation happened"

    # Now a customer reading the same session must NOT move the timestamp. The customer is
    # created here rather than borrowed from whatever the session has seeded: this negative
    # half is the more important one, and a skip because no customer happened to exist would
    # leave the actual claim unverified.
    email = "recon-customer@example.com"
    client.post("/api/customer/auth/register", json={
        "email": email, "password": "customer1234",
        "name": "Recon Customer", "ship_name": "Recon Vessel",
    })
    login = client.post("/api/customer/auth/login",
                        json={"email": email, "password": "customer1234"})
    assert login.status_code == 200, login.text
    token = login.json()["access_token"]
    me = client.get("/api/customer/auth/me",
                    headers={"Authorization": f"Bearer {token}"})
    customer_id = me.json()["id"]

    # Attach the session to that customer so the ownership check lets the read through.
    from app.models.session import Session
    db = _S()
    try:
        db.get(Session, sid).customer_id = customer_id
        db.commit()
    finally:
        db.close()
    r2 = client.get(f"/api/nfc/session/{sid}",
                    headers={**_erp(), "Authorization": f"Bearer {token}"})
    assert r2.status_code == 200, r2.text
    assert _reconciled_at(sid) == stamped, (
        "a customer reading their own session advanced last_reconciled_at, which would mute "
        "the silence detector whenever someone opened the app"
    )


# ═══ TC-ERPR-02 ══════════════════════════════════════════════════════════════

def test_tc_erpr_02_by_user_stamps_everything_it_returns(client, recon_pid):
    """This endpoint exists so ERP can reconcile, so a machine read of it IS the event."""
    ids = [_session(recon_pid, user="erp-bulk", socket_id=i) for i in (1, 2, 3)]
    assert all(_reconciled_at(i) is None for i in ids)

    r = client.get("/api/nfc/sessions/by-user/erp-bulk", headers=_erp())
    assert r.status_code == 200, r.text
    assert r.json()["count"] == 3
    assert all(_reconciled_at(i) is not None for i in ids), \
        "by-user returned sessions without recording that ERP had seen them"


# ═══ TC-ERPR-03 ══════════════════════════════════════════════════════════════

def test_tc_erpr_03_divergence_is_oldest_first_and_excludes_live(client, auth_headers,
                                                                recon_pid):
    """Oldest first, because the oldest unreconciled charge is the one likely to be written
    off, and a newest-first list buries it."""
    _session(recon_pid, started_days_ago=10, socket_id=1)
    _session(recon_pid, started_days_ago=2, socket_id=2)
    _session(recon_pid, started_days_ago=5, status="active", socket_id=3)

    r = client.get("/api/nfc/reconciliation/divergence", headers=auth_headers)
    assert r.status_code == 200, r.text
    rows = [s for s in r.json()["sessions"] if s["pedestal_id"] == recon_pid]

    assert len(rows) == 2, (
        f"expected the two finished sessions, got {len(rows)} — an in-progress session has "
        f"nothing final to reconcile and must not appear"
    )
    assert rows[0]["started_at"] < rows[1]["started_at"], \
        f"not oldest-first: {[r['started_at'] for r in rows]}"


# ═══ TC-ERPR-04 — the alarm that matters ═════════════════════════════════════

@pytest.mark.asyncio
async def test_tc_erpr_04_backlog_plus_silence_alarms_and_explains(recon_pid):
    """Charges waiting and ERP not looking: the integration is down.

    The message is asserted, not just the alarm's existence. "ERP has not reconciled this
    pedestal since X" is actionable; a generic staleness warning is what gets muted.
    """
    from app.config import settings

    _session(recon_pid, started_days_ago=20, energy=12.5)
    _session(recon_pid, started_days_ago=15, energy=7.5, socket_id=2,
             reconciled_days_ago=settings.erp_reconciliation_silence_days + 5)

    state = _states(recon_pid)
    assert state.state == "silent_with_backlog", f"got {state.state}"

    await _run_check()

    alarms = _alarms()
    assert len(alarms) == 1, f"expected one alarm, got {len(alarms)}"
    msg = alarms[0].message
    assert "has not reconciled this pedestal since" in msg, (
        f"the message must name what has not happened and since when, or it reads as generic "
        f"staleness and gets muted: {msg}"
    )
    assert "waiting to be billed" in msg, \
        f"the consequence — unbilled charges — must be in the message: {msg}"
    assert "12.5" in msg or "20.0" in msg or "kWh" in msg, \
        f"the size of the backlog should be visible: {msg}"
    assert alarms[0].pedestal_id == recon_pid


# ═══ TC-ERPR-05 — the alarm that must NOT fire ═══════════════════════════════

@pytest.mark.asyncio
async def test_tc_erpr_05_quiet_marina_does_not_alarm(recon_pid):
    """A marina quiet in winter reconciles nothing and is not broken.

    This is the test that keeps the alarm credible. If it fired here, it would fire at every
    quiet marina every week, be muted, and then fail to be noticed when the integration really
    did stop.
    """
    # Everything that exists has already been reconciled — nothing is waiting.
    _session(recon_pid, started_days_ago=200, reconciled_days_ago=199)

    state = _states(recon_pid)
    assert state.state == "idle", f"got {state.state}: {state.as_dict()}"
    assert "not a fault" in state.as_dict()["explanation"].lower(), (
        "the idle explanation must say plainly that this is not a fault, or an operator "
        "reading the view will treat it as one"
    )

    await _run_check()
    assert _alarms() == [], (
        "a quiet pedestal raised a reconciliation alarm. This is how the alarm gets muted, "
        "after which the real failure goes unnoticed too."
    )


# ═══ TC-ERPR-06 / 07 / 08 ════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_tc_erpr_06_recent_reconciliation_with_backlog_does_not_alarm(recon_pid):
    """A backlog is normal while ERP is actively working through it."""
    _session(recon_pid, started_days_ago=3)                      # waiting
    _session(recon_pid, started_days_ago=4, socket_id=2,
             reconciled_days_ago=0.5)                            # ERP read something yesterday

    assert _states(recon_pid).state == "reconciling"
    await _run_check()
    assert _alarms() == []


@pytest.mark.asyncio
async def test_tc_erpr_07_mode_2_never_alarms(recon_pid):
    """There is no ERP in MODE 2, so ERP silence is not a fault — it is the topology."""
    from app.config import settings

    _session(recon_pid, started_days_ago=30)
    assert _states(recon_pid).state == "silent_with_backlog"

    settings.nfc_direct_client_mode = True
    await _run_check()
    assert _alarms() == [], (
        "an ERP-silence alarm fired at a marina with no ERP — noise about a system that does "
        "not exist"
    )


def test_tc_erpr_08_active_session_is_not_a_backlog_item(recon_pid):
    """A customer still plugged in is not an unbilled charge.

    Counting live sessions would alarm on a busy marina rather than a broken integration, which
    is the opposite of the intent.
    """
    _session(recon_pid, started_days_ago=30, status="active")
    state = _states(recon_pid)
    assert state.unreconciled_count == 0, \
        f"a live session was counted as a backlog item: {state.as_dict()}"
    assert state.state == "idle"


def test_tc_erpr_09_status_endpoint_says_when_it_is_not_applicable(client, auth_headers):
    """MODE 2 must not return empty lists that read as "all healthy"."""
    from app.config import settings

    settings.nfc_direct_client_mode = True
    body = client.get("/api/nfc/reconciliation", headers=auth_headers).json()
    assert body["applicable"] is False, \
        "MODE 2 reported as applicable; empty lists would read as a clean bill of health"
    assert body["mode"] == "direct"
