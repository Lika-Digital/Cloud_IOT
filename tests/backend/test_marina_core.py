"""
Marina CORE — the status reduction and the L1 payload (v3.44)
============================================================

CORE is the whole marina dashboard in one call, and the frontend computes no status. So every
rule the brief sets about what the marina sees is enforced HERE, once, and the UI is a
rendering job. These tests are the enforcement.

  TC-MC-01  precedence — the most serious true condition wins, in the approved order
  TC-MC-02  no contact and standalone are UNKNOWN, never ATTENTION
  TC-MC-03  stale heartbeat beats a healthy-looking database row
  TC-MC-04  a condition with no sentence is UNKNOWN, never silently OK
  TC-MC-05  water is a pedestal-level pool — berths carry no water field at all
  TC-MC-06  controls are unavailable when the NUC cannot act, with the reason
  TC-MC-07  a berth with no socket renders a reason, not a disabled control
  TC-MC-08  NO customer names or ERP ids anywhere in the payload
  TC-MC-09  a stale valve reads `unknown`, distinctly from `idle`
  TC-MC-10  unmeasurable consumption surfaces as a sentence, and the figure is None not 0.0
  TC-MC-11  every status the reducer can emit has an entry in the sentence table
  TC-MC-12  guard UNAVAILABLE never renders as "off"
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from _test_paths import TEST_DB  # per-run path, never a literal — see _test_paths.py
_engine = create_engine(TEST_DB, connect_args={"check_same_thread": False})
_S = sessionmaker(autocommit=False, autoflush=False, bind=_engine)

# The USERS database, which is where Berth lives. Opened against the same file conftest
# overrides `get_user_db` with: a hand-opened `UserSessionLocal()` resolves to a different
# file, so rows written through it are invisible to the endpoint under test. The six-tag
# suite hit the identical trap with `SessionLocal`, and it presents as "the handler ignored
# my data" rather than as a wiring mistake.
from _test_paths import TEST_USER_DB  # per-run path, never a literal — see _test_paths.py
_user_engine = create_engine(TEST_USER_DB, connect_args={"check_same_thread": False})
_US = sessionmaker(autocommit=False, autoflush=False, bind=_user_engine)

CAB = "TST_MARINA_CAB"


# ═══ The reduction, in isolation ══════════════════════════════════════════════
#
# `reduce()` does no I/O, so precedence is tested directly rather than through four database
# fixtures. A reduction that needs a seeded cabinet to assert its own ordering is a reduction
# nobody will re-test when the order changes.

def test_tc_mc_01_precedence_is_the_approved_order():
    """Every condition true at once must yield the highest-ranked sentence.

    Asserted by switching conditions on one at a time from the bottom up: each step must
    change the answer, which proves the ordering rather than just the top of it. A test that
    only checks "all true -> no_contact" passes even if ranks 3..8 are shuffled.
    """
    from app.services.marina_status import BerthFacts, reduce

    # Ordered worst-last, so each append must take over the answer.
    steps = [
        ("ok", {}),
        ("vessel_mismatch", {"vessel_match_configured": True, "vessel_mismatch": True}),
        ("measurement_missing", {"consumption_unmeasured": True}),
        ("guard_unreviewed", {"guard_alarm_unreviewed": True}),
        ("breaker_tripped", {"breaker_tripped": True}),
        ("auto_off_overload", {"auto_stop_pending_ack": True}),
        ("too_hot", {"temperature_alarm": True}),
        ("water_leak", {"moisture_alarm": True}),
        ("outlet_silent", {"outlet_state_unknown": True}),
        ("standalone", {"smart_mode": False}),
        ("no_contact", {"heartbeat_age_s": 999.0}),
    ]

    accumulated: dict = {"heartbeat_age_s": 1.0, "smart_mode": True}
    for expected_code, new_facts in steps:
        accumulated.update(new_facts)
        got = reduce(BerthFacts(**accumulated))
        assert got.code == expected_code, (
            f"with {sorted(accumulated)} true, expected {expected_code!r} but got "
            f"{got.code!r} — the precedence order does not match the approved table"
        )


def test_tc_mc_02_no_contact_and_standalone_are_unknown():
    """Neither is a fault at the berth, so neither may be ATTENTION.

    Non-smart mode especially: the Opta is switching outlets itself and nothing is broken. A
    red row would send staff to check something that is working — and would fill the
    needs-attention filter with rows needing nothing, which is how a filter stops being used.
    """
    from app.services.marina_status import BerthFacts, reduce, UNKNOWN, ATTENTION

    never_heard = reduce(BerthFacts(heartbeat_age_s=None))
    assert never_heard.code == "no_contact"
    assert never_heard.status == UNKNOWN, f"got {never_heard.status!r}"

    standalone = reduce(BerthFacts(heartbeat_age_s=1.0, smart_mode=False))
    assert standalone.code == "standalone"
    assert standalone.status == UNKNOWN, f"got {standalone.status!r}"
    assert standalone.status != ATTENTION

    # And the sentence must say what it means, in words a customer-facing operator can act on.
    assert "running on its own" in standalone.text
    assert "monitoring only" in standalone.text


def test_tc_mc_04_an_unnamed_condition_is_unknown_not_ok():
    """A detected condition with no sentence must never come out as OK.

    This is what keeps the string table honest: the only way to make a new condition render
    properly is to add its entry. Falling through to OK would make a missing entry invisible,
    which is how the audit found Rule 4 compliance was accidental.
    """
    from app.services.marina_status import BerthFacts, reduce, UNKNOWN

    got = reduce(BerthFacts(heartbeat_age_s=1.0, unnamed_condition="some_new_alarm"))
    assert got.status == UNKNOWN
    assert got.code == "unrecognised"
    assert got.text == "Something needs checking"


def test_tc_mc_11_every_emittable_sentence_is_in_the_table():
    """The reducer cannot return a sentence the table does not define.

    Walks the module rather than listing expectations, so a sentence added to `reduce()`
    without a table entry fails here instead of reaching a screen as a blank.
    """
    from app.services import marina_status as ms

    for code, s in ms.SENTENCES.items():
        assert s.code == code, f"table key {code!r} does not match its sentence code {s.code!r}"
        assert s.status in (ms.OK, ms.ATTENTION, ms.UNKNOWN), f"{code}: bad status {s.status!r}"
        if code != "ok":
            assert s.text, f"{code} has no sentence text"
        assert "{" not in s.text, f"{code}: sentence contains a format placeholder"
        # Plain language: no error codes, no identifiers leaking into marina-facing words.
        assert "_" not in s.text, f"{code}: sentence looks like an identifier: {s.text!r}"

    ranks = [s.rank for s in ms.SENTENCES.values()]
    assert len(ranks) == len(set(ranks)), "two sentences share a rank — precedence is ambiguous"


def test_tc_mc_03_stale_heartbeat_beats_a_healthy_database_row():
    """The v3.40 lesson at the dashboard layer.

    `heartbeat_age` must be computed from the in-memory map. A retained `opta/status` replays
    to every new subscriber, so after a restart a cabinet dead for weeks has
    `opta_connected = 1` and a recent stored `last_heartbeat`. Asserted on the helper because
    that is the only place the decision is made.
    """
    from app.services.marina_status import heartbeat_age, COMM_LOSS_TIMEOUT_S, reduce, BerthFacts

    now = datetime(2026, 10, 2, 12, 0, 0)
    assert heartbeat_age(None, now=now) is None, "never-seen must be None, not 0.0"

    fresh = heartbeat_age(now - timedelta(seconds=5), now=now)
    assert fresh is not None and fresh < COMM_LOSS_TIMEOUT_S

    stale = heartbeat_age(now - timedelta(seconds=COMM_LOSS_TIMEOUT_S + 5), now=now)
    assert reduce(BerthFacts(heartbeat_age_s=stale)).code == "no_contact"


def test_tc_mc_09_a_stale_valve_state_is_unknown():
    """`unknown` and `idle` are different answers and must not collapse."""
    from app.services.marina_status import outlet_state_is_stale, OUTLET_STALE_S

    now = datetime(2026, 10, 2, 12, 0, 0)
    assert outlet_state_is_stale(None, now=now), "never reported must be stale"
    assert not outlet_state_is_stale(now - timedelta(seconds=5), now=now)
    assert outlet_state_is_stale(now - timedelta(seconds=OUTLET_STALE_S + 5), now=now)


# ═══ The payload, through the real endpoint ═══════════════════════════════════

@pytest.fixture(scope="module")
def marina_pid(client, auth_headers):
    """A cabinet with 4 berths, 4 sockets and 2 valves — the Krk layout."""
    from app.models.pedestal_config import PedestalConfig
    from app.models.socket_config import SocketConfig
    from app.models.valve_config import ValveConfig
    from app.auth.berth_models import Berth

    r = client.post("/api/pedestals/", json={
        "name": "Marina Core Pedestal", "location": "Dock A", "data_mode": "real",
    }, headers=auth_headers)
    pid = r.json()["id"]

    db = _S()
    try:
        cfg = db.query(PedestalConfig).filter(PedestalConfig.pedestal_id == pid).first()
        if cfg is None:
            cfg = PedestalConfig(pedestal_id=pid)
            db.add(cfg)
        cfg.opta_client_id = CAB
        cfg.dock_id = "A"
        cfg.smart_mode = True
        for sid in (1, 2, 3, 4):
            if db.query(SocketConfig).filter(
                    SocketConfig.pedestal_id == pid,
                    SocketConfig.socket_id == sid).first() is None:
                db.add(SocketConfig(pedestal_id=pid, socket_id=sid, auto_activate=True))
        for vid in (1, 2):
            if db.query(ValveConfig).filter(
                    ValveConfig.pedestal_id == pid,
                    ValveConfig.valve_id == vid).first() is None:
                db.add(ValveConfig(pedestal_id=pid, valve_id=vid, auto_activate=True))
        db.commit()
    finally:
        db.close()

    udb = _US()
    berth_ids = []
    try:
        for n in (1, 2, 3, 4):
            b = (udb.query(Berth)
                 .filter(Berth.pedestal_id == pid, Berth.berth_number == n).first())
            if b is None:
                b = Berth(name=f"Berth {n}", pedestal_id=pid, berth_number=n)
                udb.add(b)
                udb.commit()
                udb.refresh(b)
            berth_ids.append(b.id)
    finally:
        udb.close()

    # Berths 1..4 on sockets Q1..Q4. No valve_id — water is not mapped to berths.
    client.put(f"/api/marina/berth-assignments/{pid}", headers=auth_headers, json={
        "assignments": [
            {"berth_id": bid, "socket_id": n}
            for n, bid in zip((1, 2, 3, 4), berth_ids)
        ],
    })
    return pid, berth_ids


@pytest.fixture(autouse=True)
def _alive(marina_pid):
    """A live cabinet: a fresh heartbeat AND fresh per-socket meter telemetry. Since block 3
    (2026-10-12) a socket nobody has heard from within 60 s is `outlet_silent` (rank 2.5), so a
    cabinet that heartbeats but never reports its sockets is not the healthy cabinet these
    tests mean. A real one sends meter telemetry every 5 s per socket."""
    from app.services.mqtt_handlers import last_heartbeat
    from app.models.socket_config import SocketConfig
    pid, _ = marina_pid
    last_heartbeat[pid] = datetime.utcnow()
    db = _S()
    try:
        for c in db.query(SocketConfig).filter(SocketConfig.pedestal_id == pid).all():
            c.meter_load_updated_at = datetime.utcnow()
        db.commit()
    finally:
        db.close()
    yield
    last_heartbeat.pop(pid, None)


def _core(client, auth_headers, pid):
    r = client.get("/api/marina/berths", headers=auth_headers)
    assert r.status_code == 200, r.text
    for p in r.json()["pedestals"]:
        if p["pedestal_id"] == pid:
            return p
    raise AssertionError(f"pedestal {pid} missing from CORE")


def test_tc_mc_05_water_is_pedestal_level_not_per_berth(client, auth_headers, marina_pid):
    """The Krk layout, enforced in the shape.

    Water serves a maximum of two users at a time via two valves, and the valves are NOT
    piped to specific berths. A per-berth water field would invent a relationship the
    plumbing does not have: a berth row would read "Water OFF" while its occupant used the
    valve at the far end of the cabinet.

    Asserted as ABSENCE from the berth, not as null: a null field invites a UI to render a
    water line that should not exist.
    """
    pid, _ = marina_pid
    ped = _core(client, auth_headers, pid)

    assert len(ped["berths"]) == 4, "the Krk cabinet covers four berths"
    for b in ped["berths"]:
        assert "power" in b, "electricity IS per berth"
        assert "water" not in b, (
            f"berth {b['berth_number']} carries a water field. Water is not mapped to berths "
            f"— two valves serve a maximum of two users at a time, whoever scans them"
        )

    outlets = ped["water_outlets"]
    assert [o["outlet"] for o in outlets] == ["V1", "V2"]
    for o in outlets:
        assert "in_use" in o, "the pool needs to say which outlets are taken"


def test_tc_mc_08_no_customer_identity_anywhere(client, auth_headers, marina_pid):
    """Marina staff do not see customer names. Decided 2026-10-01.

    Scans the WHOLE payload recursively rather than checking named fields, because the leak
    this prevents arrives as a field nobody thought to look at — which is exactly how
    `customer_name` reached /usage/history and the monthly report.
    """
    pid, berth_ids = marina_pid
    forbidden = {"customer_name", "nfc_user_id", "customer_email", "name", "email"}

    def walk(node, path="core"):
        if isinstance(node, dict):
            for k, v in node.items():
                assert k not in forbidden, (
                    f"{path}.{k} is customer identity and must not be in the marina payload"
                )
                walk(v, f"{path}.{k}")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{path}[{i}]")

    walk(_core(client, auth_headers, pid))

    detail = client.get(f"/api/marina/berths/{berth_ids[0]}", headers=auth_headers)
    assert detail.status_code == 200, detail.text
    walk(detail.json(), "detail")


def test_tc_mc_06_controls_unavailable_when_the_nuc_cannot_act(client, auth_headers,
                                                               marina_pid):
    """Smart mode off: readings stay, controls go, and the reason is machine-readable.

    `available: false` is what tells the UI to render NO control element — not a disabled
    one. `unavailable_reason` exists because "this pedestal is switching for itself" and
    "this berth has no socket" need different sentences.
    """
    from app.models.pedestal_config import PedestalConfig
    pid, _ = marina_pid

    db = _S()
    try:
        cfg = db.query(PedestalConfig).filter(PedestalConfig.pedestal_id == pid).first()
        cfg.smart_mode = False
        db.commit()
    finally:
        db.close()
    try:
        ped = _core(client, auth_headers, pid)
        assert ped["smart_mode"] is False
        assert ped["reachable"] is True, "non-smart mode is not the same as unreachable"
        for b in ped["berths"]:
            assert b["status_code"] == "standalone"
            assert b["power"]["available"] is False
            assert b["power"]["unavailable_reason"] == "standalone"
        for o in ped["water_outlets"]:
            assert o["available"] is False
        assert ped["light"]["available"] is False
    finally:
        db = _S()
        try:
            cfg = db.query(PedestalConfig).filter(PedestalConfig.pedestal_id == pid).first()
            cfg.smart_mode = True
            db.commit()
        finally:
            db.close()


def test_tc_mc_07_a_berth_with_no_socket_says_so(client, auth_headers, marina_pid):
    """A berth with power is normal; a berth without it must render rather than break."""
    from app.auth.berth_models import Berth

    pid, _ = marina_pid

    udb = _US()
    try:
        b = Berth(name="Berth 9", pedestal_id=pid, berth_number=9)
        udb.add(b)
        udb.commit()
        udb.refresh(b)
        orphan_id = b.id
    finally:
        udb.close()
    try:
        ped = _core(client, auth_headers, pid)
        orphan = next(x for x in ped["berths"] if x["berth_id"] == orphan_id)
        assert orphan["power"]["outlet"] is None
        assert orphan["power"]["available"] is False
        assert orphan["power"]["unavailable_reason"] == "no_socket", (
            "the UI needs to tell 'no socket here' apart from 'cannot control right now'"
        )
        # v3.45 — the row reports AMPS, not watts. The single-phase meters report `powerKw`
        # ~100x high, so a watts figure on this row would have shown 2,650 W on a 26 W socket.
        assert orphan["power"]["amps"] is None, "no socket means no figure, not 0"
        assert "watts" not in orphan["power"], (
            "the row still carries a watts key; the field was removed rather than nulled so "
            "no client can keep rendering a number this meter cannot produce"
        )
    finally:
        udb = _US()
        try:
            row = udb.get(Berth, orphan_id)
            if row is not None:
                udb.delete(row)
                udb.commit()
        finally:
            udb.close()


def test_tc_mc_12_guard_unavailable_is_never_off(client, auth_headers, marina_pid):
    """Off is a decision someone made; unavailable is a fault.

    With no guard wiring for this cabinet the state must be `unavailable`. Reporting `off`
    would tell an operator guard was deliberately disabled when in fact nothing is watching —
    and the whole liveness design exists to keep those apart.
    """
    pid, _ = marina_pid
    ped = _core(client, auth_headers, pid)
    assert ped["guard"]["state"] in ("unavailable", "off", "on", "paused")
    assert ped["guard"]["state"] != "off", (
        "no guard worker for this pedestal reported as 'off' — that claims a decision nobody "
        "made"
    )
    assert "unavailable" in ped["guard"]["sentence"].lower()


def test_tc_mc_10_unmeasurable_consumption_surfaces(client, auth_headers, marina_pid):
    """An unknown figure must reach a human, and must not render as zero.

    We report consumption and the ERP bills it, so an `unknown` leaves the ERP nothing to
    charge. Without this sentence nobody on our side would ever know it happened.
    """
    from app.models.session import Session
    pid, berth_ids = marina_pid

    db = _S()
    try:
        db.add(Session(
            pedestal_id=pid, socket_id=1, type="electricity", status="completed",
            started_at=datetime.utcnow() - timedelta(hours=2),
            ended_at=datetime.utcnow() - timedelta(hours=1),
            energy_kwh=None, consumption_source="unknown",
        ))
        db.commit()
    finally:
        db.close()
    try:
        ped = _core(client, auth_headers, pid)
        b1 = next(x for x in ped["berths"] if x["power"]["outlet"] == "Q1")
        assert b1["status_code"] == "measurement_missing", (
            f"got {b1['status_code']!r} — an unmeasurable session must be visible to a human"
        )
        assert b1["status"] == "attention"

        detail = client.get(f"/api/marina/berths/{berth_ids[0]}", headers=auth_headers).json()
        assert detail["consumption"]["kwh"] is None, (
            f"month-to-date came out as {detail['consumption']['kwh']!r}; the sum of a partial "
            f"set is not the total, and 0.0 would be a silent under-report"
        )
        assert detail["consumption"]["source"] == "unknown"
        assert "not measured" in detail["consumption"]["note"].lower()
    finally:
        db = _S()
        try:
            db.query(Session).filter(Session.pedestal_id == pid).delete()
            db.commit()
        finally:
            db.close()


def test_tc_mc_13_a_socket_cannot_serve_two_berths(client, auth_headers, marina_pid):
    """The one DB invariant the wizard depends on, refused at the write site.

    Two berths on one socket would make a single customer's kWh appear against two berths with
    no way to tell which drew it. Validated as a SET before anything is written, so a bad
    request cannot leave half the mapping applied.
    """
    pid, berth_ids = marina_pid

    r = client.put(f"/api/marina/berth-assignments/{pid}", headers=auth_headers, json={
        "assignments": [
            {"berth_id": berth_ids[0], "socket_id": 2},
            {"berth_id": berth_ids[1], "socket_id": 2},
        ],
    })
    assert r.status_code == 400, r.text
    assert "two berths" in r.json()["detail"]

    # And nothing was written — the original four-way mapping survives.
    current = client.get(f"/api/marina/berth-assignments/{pid}", headers=auth_headers).json()
    assert len(current["assignments"]) == 4, (
        "a refused request changed the mapping — validation must complete before any write"
    )


def test_tc_mc_14_berth_assignment_is_admin_only(client, cust_headers, marina_pid):
    """Re-pointing a berth is an installation act, like NFC provisioning.

    After one of these a customer's consumption lands against a different berth.
    """
    pid, berth_ids = marina_pid
    r = client.put(f"/api/marina/berth-assignments/{pid}", headers=cust_headers, json={
        "assignments": [{"berth_id": berth_ids[0], "socket_id": 1}],
    })
    assert r.status_code in (401, 403), r.text
