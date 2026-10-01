"""
The six-tag model — water is provisioned and scanned exactly like electricity (v3.43)
=====================================================================================

A cabinet with 4 sockets and 2 water outlets carries **six** NFC tags, one per outlet. The
customer scans the tag on the outlet they are about to use, and the session belongs to whoever
scanned. Attribution is by scanned tag — never by berth, for water any more than for
electricity.

The code supported four. Three separate places assumed it:

| Was | Consequence |
|---|---|
| `_VALID_SOCKETS = {Q1..Q4}` on provisioning, bulk and delete | a `V1` tag was rejected at the door with 400 — the two water tags were **unprovisionable** |
| `/scan` hardcoded `session_type="electricity"` | had a valve tag existed, its litres would have been recorded as an electricity session on socket N — a customer billed for kWh on an outlet they never touched |
| no `outlet_type` on the tag | unrecoverable by inference: both inbound name vocabularies accept bare digits, so `"1"` cannot distinguish socket 1 from valve 1 |

The third is why the type is a stored dimension rather than something derived at read time.
`_socket_name_to_id("V1")` returned **1** before the resolver was tightened, so a water tag
would have silently energised electricity socket 1.

**The numeric collision is deliberate and is asserted here.** A water session on V1 and an
electricity session on Q1 are both `socket_id=1`, told apart by `Session.type`. TC-SIX-06
requires that one does not block the other — the previous unfiltered lookup would have said
"this socket is already in use" to a customer standing at a different outlet.

  TC-SIX-01  a valve tag provisions, and stores its type
  TC-SIX-02  a mismatch is REFUSED, not silently corrected (V1 declared as a socket)
  TC-SIX-03  a mismatch is refused in the other direction too (Q3 declared as a valve)
  TC-SIX-04  a name this hardware does not have is refused (WTR-1, E2, bare digits)
  TC-SIX-05  scanning a valve tag opens a WATER session, not an electricity one
  TC-SIX-06  a water session on V1 does not block an electricity scan on Q1
  TC-SIX-07  an active session on the SAME outlet still blocks, and says which kind
  TC-SIX-08  all six outlets provision in one bulk call
  TC-SIX-09  a valve tag can be removed (the delete path rejected V-names with 400)
  TC-SIX-10  /outlets falls back to the canonical six and SAYS it is a fallback
  TC-SIX-11  /outlets reports the cabinet's own account, ratings and all, once it has spoken
  TC-SIX-12  a truncated hardware config does not erase the valves it could not carry
  TC-SIX-13  the ERP payload for a water session reports V-names and litres, not Q-names and kWh
  TC-SIX-14  a water tag is refused on a mode-2 site until the app has shipped
  TC-SIX-15  valve state is persisted, is never read from the socket table, and expires
"""
from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

TEST_DB = "sqlite:///./tests/test_pedestal.db"
_engine = create_engine(TEST_DB, connect_args={"check_same_thread": False})
_S = sessionmaker(autocommit=False, autoflush=False, bind=_engine)

ERP_KEY = "test-erp-key-six-tag"
CAB = "TST_SIXTAG_CAB"


@pytest.fixture(autouse=True)
def _erp_key():
    from app.config import settings
    prev = settings.erp_api_key
    settings.erp_api_key = ERP_KEY
    yield
    settings.erp_api_key = prev


def _erp() -> dict:
    return {"X-API-Key": ERP_KEY}


@pytest.fixture(scope="module")
def six_pid(client, auth_headers):
    from app.models.pedestal_config import PedestalConfig
    from app.models.socket_config import SocketConfig
    from app.models.valve_config import ValveConfig

    r = client.post("/api/pedestals/", json={
        "name": "Six Tag Pedestal", "location": "Six Dock", "data_mode": "real",
    }, headers=auth_headers)
    pid = r.json()["id"]
    db = _S()
    try:
        cfg = db.query(PedestalConfig).filter(PedestalConfig.pedestal_id == pid).first()
        if cfg is None:
            cfg = PedestalConfig(pedestal_id=pid)
            db.add(cfg)
        cfg.opta_client_id = CAB
        cfg.provisioning_mode = "nfc"
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
    return pid


@pytest.fixture(autouse=True)
def _alive_and_smart(six_pid):
    from app.services.mqtt_handlers import last_heartbeat

    last_heartbeat[six_pid] = datetime.utcnow()
    yield
    last_heartbeat.pop(six_pid, None)


def _clear(pid: int) -> None:
    from app.models.nfc_pending_session import NfcPendingSession
    from app.models.nfc_tag import NfcTag
    from app.models.session import Session

    db = _S()
    try:
        db.query(NfcPendingSession).delete()
        db.query(NfcTag).filter(NfcTag.cabinet_id == CAB).delete()
        db.query(Session).filter(Session.pedestal_id == pid).delete()
        db.commit()
    finally:
        db.close()


def _provision(client, auth_headers, tag: str, outlet: str, kind: str = "socket"):
    return client.post("/api/nfc/tags", headers=auth_headers, json={
        "cabinet_id": CAB, "socket_id": outlet, "nfc_tag_id": tag, "outlet_type": kind,
    })


def _scan(client, tag: str, user: str = "erp-six-tag"):
    return client.post("/api/nfc/scan", headers=_erp(),
                       json={"nfc_tag_id": tag, "user_id": user})


# ═══ TC-SIX-01 ════════════════════════════════════════════════════════════════

def test_tc_six_01_valve_tag_provisions_with_its_type(client, auth_headers, six_pid):
    """A water outlet gets a tag, and the tag remembers that it is a water outlet.

    Both halves matter. Before v3.43 the request was refused outright; storing it without the
    type would have made it indistinguishable from an electricity tag at scan time.
    """
    _clear(six_pid)

    r = _provision(client, auth_headers, "SIX-V1-TAG", "V1", "valve")
    assert r.status_code == 200, r.text

    body = r.json()
    assert body["socket_id"] == "V1"
    assert body["outlet_type"] == "valve"
    assert body["session_type"] == "water", (
        "the tag must carry the session type it produces; deriving it at scan time from the "
        "name is what the bare-digit ambiguity makes impossible"
    )

    from app.models.nfc_tag import NfcTag
    db = _S()
    try:
        row = db.query(NfcTag).filter(NfcTag.nfc_tag_id == "SIX-V1-TAG").first()
        assert row is not None
        assert row.outlet_type == "valve", "the type must be persisted, not just echoed"
    finally:
        db.close()


# ═══ TC-SIX-02 / TC-SIX-03 ════════════════════════════════════════════════════

def test_tc_six_02_valve_name_declared_as_socket_is_refused(client, auth_headers, six_pid):
    """`V1` with `outlet_type="socket"` must fail, not be quietly corrected to a valve.

    Correcting it would hide which half of the request was wrong — the name or the type — and
    this decides whether a customer's tap energises an electricity socket.
    """
    _clear(six_pid)

    r = _provision(client, auth_headers, "SIX-MISMATCH-A", "V1", "socket")
    assert r.status_code == 400, (
        f"declaring V1 a socket returned {r.status_code}; a silent correction here writes a "
        f"mapping nobody asked for"
    )
    detail = r.json()["detail"].lower()
    assert "valve" in detail and "socket" in detail, (
        f"the message must name both the actual and the claimed kind; got {r.json()['detail']!r}"
    )

    from app.models.nfc_tag import NfcTag
    db = _S()
    try:
        assert db.query(NfcTag).filter(
            NfcTag.nfc_tag_id == "SIX-MISMATCH-A").first() is None, (
            "a refused provision must write nothing"
        )
    finally:
        db.close()


def test_tc_six_03_socket_name_declared_as_valve_is_refused(client, auth_headers, six_pid):
    """The reverse: `Q3` with `outlet_type="valve"`. Symmetry is the point."""
    _clear(six_pid)

    r = _provision(client, auth_headers, "SIX-MISMATCH-B", "Q3", "valve")
    assert r.status_code == 400, r.text


# ═══ TC-SIX-04 ════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("outlet", ["WTR-1", "E2", "1", "V3", "Q5", "V0", "q1"])
def test_tc_six_04_names_this_hardware_does_not_have_are_refused(
        client, auth_headers, six_pid, outlet):
    """Only Q1..Q4 and V1/V2 exist.

    `WTR-1` is in this list on purpose: it sat in the MQTT resolver's allowlist for months,
    seeded from a docstring rather than a capture, and real traffic has never contained it
    (`docs/engineering_notes.md`, rule 6). A tag we write ourselves has no excuse for using a
    spelling the hardware does not.

    `V3` and `Q5` are in range-shaped but out of range; `q1` catches case-insensitivity, which
    would let two spellings of one outlet hold two different tags.
    """
    _clear(six_pid)

    for kind in ("socket", "valve"):
        r = _provision(client, auth_headers, f"SIX-BAD-{outlet}-{kind}", outlet, kind)
        assert r.status_code in (400, 422), (
            f"outlet {outlet!r} declared as {kind} returned {r.status_code}, not a refusal"
        )


# ═══ TC-SIX-05 ════════════════════════════════════════════════════════════════

def test_tc_six_05_scanning_a_valve_tag_opens_a_water_session(client, auth_headers, six_pid):
    """The defect this whole item exists to close.

    `/scan` hardcoded `session_type="electricity"`. A valve tag would have produced an
    electricity session against socket N — wrong outlet, wrong units, wrong customer.
    """
    _clear(six_pid)
    _provision(client, auth_headers, "SIX-SCAN-V2", "V2", "valve")

    r = _scan(client, "SIX-SCAN-V2")
    assert r.status_code == 200, r.text

    body = r.json()
    assert body["socket_id"] == "V2"
    assert body["outlet_type"] == "valve"
    assert body["session_type"] == "water", (
        f"a valve scan reported session_type={body.get('session_type')!r}; litres recorded as "
        f"an electricity session is a billing fault, not a labelling one"
    )
    assert "tap" in body["message"].lower(), (
        f"the instruction must match the outlet; got {body['message']!r} — telling someone at "
        f"a water outlet to plug in their charger is the same class of defect as the "
        f"'pending, plug in' message on a dead cabinet"
    )


# ═══ TC-SIX-06 ════════════════════════════════════════════════════════════════

def test_tc_six_06_water_session_on_v1_does_not_block_electricity_on_q1(
        client, auth_headers, six_pid):
    """The numeric collision, asserted.

    V1 and Q1 are both `socket_id=1`. The availability lookup used to filter on
    `session_type="electricity"` regardless of what was scanned, so an active WATER session on
    V1 was invisible to it — and, symmetrically, once `/scan` derived the type, an unfiltered
    lookup would have reported Q1 busy to someone standing at V1.
    """
    _clear(six_pid)
    _provision(client, auth_headers, "SIX-COLLIDE-V1", "V1", "valve")
    _provision(client, auth_headers, "SIX-COLLIDE-Q1", "Q1", "socket")

    from app.models.session import Session
    db = _S()
    try:
        db.add(Session(pedestal_id=six_pid, socket_id=1, type="water",
                       status="active", started_at=datetime.utcnow()))
        db.commit()
    finally:
        db.close()

    elec = _scan(client, "SIX-COLLIDE-Q1")
    assert elec.status_code == 200, (
        f"an active WATER session on V1 blocked an electricity scan on Q1 "
        f"({elec.status_code}: {elec.text}); they are different outlets that share a number"
    )

    water = _scan(client, "SIX-COLLIDE-V1")
    assert water.status_code == 409, (
        f"the active water session on V1 must block a second V1 scan; got {water.status_code}"
    )
    assert "water outlet" in water.json()["detail"].lower(), (
        f"the refusal must name the outlet kind; got {water.json()['detail']!r}"
    )


# ═══ TC-SIX-07 ════════════════════════════════════════════════════════════════

def test_tc_six_07_same_outlet_in_use_still_blocks(client, auth_headers, six_pid):
    """The pre-existing guard must survive the change, worded for the outlet in question."""
    _clear(six_pid)
    _provision(client, auth_headers, "SIX-BUSY-Q2", "Q2", "socket")

    from app.models.session import Session
    db = _S()
    try:
        db.add(Session(pedestal_id=six_pid, socket_id=2, type="electricity",
                       status="active", started_at=datetime.utcnow()))
        db.commit()
    finally:
        db.close()

    r = _scan(client, "SIX-BUSY-Q2")
    assert r.status_code == 409, r.text
    detail = r.json()["detail"].lower()
    assert "socket" in detail and "water" not in detail, (
        f"an electricity refusal must not talk about water; got {r.json()['detail']!r}"
    )


# ═══ TC-SIX-08 ════════════════════════════════════════════════════════════════

def test_tc_six_08_all_six_outlets_provision_in_one_call(client, auth_headers, six_pid):
    """Save All, with the real cabinet's outlet list.

    The bulk path carried its own copy of the four-socket check, so it had to be fixed in its
    own right — a single-item fix would have left the UI's actual save path broken.
    """
    _clear(six_pid)

    items = [{"socket_id": n, "nfc_tag_id": f"SIX-BULK-{n}", "outlet_type": "socket"}
             for n in ("Q1", "Q2", "Q3", "Q4")]
    items += [{"socket_id": n, "nfc_tag_id": f"SIX-BULK-{n}", "outlet_type": "valve"}
              for n in ("V1", "V2")]

    r = client.post("/api/nfc/tags/bulk", headers=auth_headers,
                    json={"cabinet_id": CAB, "items": items})
    assert r.status_code == 200, r.text

    tags = r.json()["tags"]
    assert len(tags) == 6, f"expected six tags, got {len(tags)}"
    by_name = {t["socket_id"]: t for t in tags}
    assert by_name["V1"]["outlet_type"] == "valve"
    assert by_name["V2"]["session_type"] == "water"
    assert by_name["Q1"]["outlet_type"] == "socket"


def test_tc_six_08b_bulk_mismatch_aborts_before_writing_anything(
        client, auth_headers, six_pid):
    """One bad item must not leave the good ones half-applied.

    Validation is a pre-pass for exactly this reason, and the mismatch check has to happen in
    that pre-pass rather than inside the per-item loop.
    """
    _clear(six_pid)

    r = client.post("/api/nfc/tags/bulk", headers=auth_headers, json={
        "cabinet_id": CAB,
        "items": [
            {"socket_id": "Q1", "nfc_tag_id": "SIX-ABORT-1", "outlet_type": "socket"},
            {"socket_id": "WTR-9", "nfc_tag_id": "SIX-ABORT-2", "outlet_type": "valve"},
        ],
    })
    assert r.status_code in (400, 422), r.text

    from app.models.nfc_tag import NfcTag
    db = _S()
    try:
        assert db.query(NfcTag).filter(
            NfcTag.nfc_tag_id == "SIX-ABORT-1").first() is None, (
            "the valid item was committed before the batch was rejected"
        )
    finally:
        db.close()


# ═══ TC-SIX-09 ════════════════════════════════════════════════════════════════

def test_tc_six_09_a_valve_tag_can_be_removed(client, auth_headers, six_pid):
    """The delete path had the same four-socket check, so a water tag could not be un-pointed.

    Worth its own case: a tag that can be created but not removed is the worse half of the
    defect — it is the destructive act that has to stay available when a tag is peeled off a
    housing and stuck somewhere else.
    """
    _clear(six_pid)
    _provision(client, auth_headers, "SIX-DEL-V1", "V1", "valve")

    r = client.delete(f"/api/nfc/tags/{CAB}/V1", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["removed"] is True

    from app.models.nfc_tag import NfcTag
    db = _S()
    try:
        row = db.query(NfcTag).filter(NfcTag.nfc_tag_id == "SIX-DEL-V1").first()
        assert row.is_active is False
        assert row.removed_by, "the removal audit trail must cover valve tags too"
    finally:
        db.close()


# ═══ TC-SIX-10 / TC-SIX-11 ════════════════════════════════════════════════════

async def _apply_hw_config(payload: dict) -> None:
    """Feed `opta/config/hardware` to the handler against the TEST database.

    `SessionLocal` must be patched: the handler opens its own session rather than receiving
    one, so an unpatched call resolves the cabinet in the production DB, finds nothing, and
    returns early — writing nothing and raising nothing. That failure mode is worth naming
    because it looks exactly like "the handler ignored my payload".
    """
    import json
    from unittest.mock import patch, AsyncMock
    from app.services.mqtt_handlers import _handle_opta_hardware_config

    with (
        patch("app.services.mqtt_handlers.SessionLocal", _S),
        patch("app.services.mqtt_handlers.ws_manager.broadcast", new=AsyncMock()),
    ):
        await _handle_opta_hardware_config(json.dumps(payload))


def _clear_hw_config(pid: int) -> None:
    from app.models.socket_config import SocketConfig
    from app.models.valve_config import ValveConfig

    db = _S()
    try:
        for r in db.query(SocketConfig).filter(SocketConfig.pedestal_id == pid).all():
            r.hw_config_received_at = None
            r.phases = None
            r.rated_amps = None
        for r in db.query(ValveConfig).filter(ValveConfig.pedestal_id == pid).all():
            r.rated_liters_per_min = None
        db.commit()
    finally:
        db.close()


def test_tc_six_10_outlets_falls_back_to_six_and_says_so(client, auth_headers, six_pid):
    """A cabinet that has never published its hardware config.

    The fallback is the canonical six — printed tags are on the housing whether or not the
    cabinet has spoken since the last restart — but `reported=False` must say which it is. A
    UI that renders "never heard from this cabinet" identically to "this cabinet has no water
    outlets" cannot tell an admin what they are looking at.
    """
    _clear_hw_config(six_pid)

    r = client.get(f"/api/nfc/outlets/{CAB}", headers=auth_headers)
    assert r.status_code == 200, r.text

    body = r.json()
    assert body["reported"] is False, "an unreported cabinet must not claim to be reported"
    names = [o["outlet_name"] for o in body["outlets"]]
    assert names == ["Q1", "Q2", "Q3", "Q4", "V1", "V2"], names
    kinds = {o["outlet_name"]: o["outlet_type"] for o in body["outlets"]}
    assert kinds["V1"] == "valve" and kinds["Q4"] == "socket"


@pytest.mark.asyncio
async def test_tc_six_11_outlets_reports_the_cabinets_own_account(
        client, auth_headers, six_pid):
    """Once `opta/config/hardware` arrives, /outlets reflects it — ratings and all.

    The capture from MAR_KRK_ORM_01 has Q1 three-phase at 32 A and Q3/Q4 at 16 A. The old UI
    rendered four identical rows, which is a real difference staff see: "this berth is on a
    16 A socket and the customer wants 32 A" is an answerable question only if the cabinet's
    own numbers reach the screen.
    """
    _clear_hw_config(six_pid)

    await _apply_hw_config({
        "cabinetId": CAB,
        "firmwareVersion": "3.1.0",
        "sockets": [
            {"socketId": "Q1", "meterType": "ABB D13 15-M 65", "phases": 3,
             "ratedAmps": 32, "modbusAddress": 1},
            {"socketId": "Q2", "meterType": "ABB D11 15-M 40", "phases": 1,
             "ratedAmps": 32, "modbusAddress": 2},
            {"socketId": "Q3", "meterType": "ABB D11 15-M 40", "phases": 1,
             "ratedAmps": 16, "modbusAddress": 3},
            {"socketId": "Q4", "meterType": "ABB D11 15-M 40", "phases": 1,
             "ratedAmps": 16, "modbusAddress": 4},
        ],
        "valves": [
            {"valveId": "V1", "ratedLitersPerMin": 20},
            {"valveId": "V2", "ratedLitersPerMin": 20},
        ],
    })

    r = client.get(f"/api/nfc/outlets/{CAB}", headers=auth_headers)
    assert r.status_code == 200, r.text

    body = r.json()
    assert body["reported"] is True, "the cabinet has spoken; /outlets must say so"
    outlets = {o["outlet_name"]: o for o in body["outlets"]}

    assert outlets["Q1"]["phases"] == 3, "three-phase Q1 must not render as single-phase"
    assert outlets["Q1"]["rated_amps"] == 32
    assert outlets["Q3"]["rated_amps"] == 16, (
        "the sockets are NOT identical; a hardcoded rating would have shown 32 A here"
    )
    assert outlets["V1"]["rated_liters_per_min"] == 20, (
        "the valves array was parsed, broadcast and discarded before v3.43"
    )
    assert outlets["V2"]["outlet_type"] == "valve"


# ═══ TC-SIX-12 ════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_tc_six_12_truncated_config_does_not_erase_the_valves(
        client, auth_headers, six_pid):
    """The firmware truncates this message at 502 bytes, severing the valves array.

    The recovery path reconstructs only the sockets, so on a truncated publish the `valves`
    key is ABSENT. Absent must mean "no news". Treating it as "this cabinet has no valves"
    would let one truncated message erase the water half of the cabinet's provisioning — and
    the erasure would look like a successful update, because the sockets did apply.
    """
    from app.models.valve_config import ValveConfig

    # Establish the valves first.
    await _apply_hw_config({
        "cabinetId": CAB, "firmwareVersion": "3.1.0",
        "sockets": [{"socketId": "Q1", "phases": 1, "ratedAmps": 32}],
        "valves": [{"valveId": "V1", "ratedLitersPerMin": 20},
                   {"valveId": "V2", "ratedLitersPerMin": 20}],
    })

    # Now a message with no valves key at all — what truncation recovery produces.
    await _apply_hw_config({
        "cabinetId": CAB, "firmwareVersion": "3.1.0",
        "sockets": [{"socketId": "Q1", "phases": 1, "ratedAmps": 32}],
    })

    db = _S()
    try:
        rows = db.query(ValveConfig).filter(
            ValveConfig.pedestal_id == six_pid).order_by(ValveConfig.valve_id).all()
        rated = {r.valve_id: r.rated_liters_per_min for r in rows}
    finally:
        db.close()

    assert rated.get(1) == 20 and rated.get(2) == 20, (
        f"a truncated config erased the valve ratings: {rated}. Absent and empty are "
        f"different, the same way zero and unknown are"
    )


# ═══ TC-SIX-13 ════════════════════════════════════════════════════════════════

def test_tc_six_13_erp_payload_for_a_water_session(client, auth_headers, six_pid):
    """What we send ERP for a water session, and what we must NOT send.

    `build_session_payload` assumed electricity in three places. Because V1 and Q1 are both
    `socket_id=1`, each one silently returned the other outlet's data:

      * the outlet was reported as `"Q1"` — an outlet the customer never touched, and one that
        may have its own session running at the same moment;
      * `energy_kwh` fell back to socket 1's cumulative ELECTRICITY register, so ERP received a
        plausible kWh figure for a session that drew litres;
      * `estimated_cost` priced those borrowed kWh at the electricity tariff.

    Unreachable before, because water tags could not be provisioned. Enabling the six-tag
    model is what made it reachable.

    The litres/kWh separation is asserted as `is None`, not as falsy: 0.0 means a register that
    did not move, which is a measurement. None means this outlet does not measure that
    quantity at all. Conflating them is the mistake the register work was built to prevent.
    """
    from app.models.session import Session
    from app.models.socket_config import SocketConfig
    from app.models.valve_config import ValveConfig

    _clear(six_pid)

    db = _S()
    try:
        # Socket 1's electricity register holds a large number. Valve 1's holds a small one.
        # If the payload reads the wrong one, the figures say which.
        sc = db.query(SocketConfig).filter(
            SocketConfig.pedestal_id == six_pid, SocketConfig.socket_id == 1).first()
        sc.meter_energy_kwh = 987.6
        sc.meter_power_kw = 3.3
        vc = db.query(ValveConfig).filter(
            ValveConfig.pedestal_id == six_pid, ValveConfig.valve_id == 1).first()
        vc.meter_total_l = 42.5

        ses = Session(pedestal_id=six_pid, socket_id=1, type="water", status="active",
                      started_at=datetime.utcnow(), nfc_user_id="erp-six-water")
        db.add(ses)
        db.commit()
        sid = ses.id
    finally:
        db.close()

    r = client.get(f"/api/nfc/session/{sid}", headers=_erp())
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["socket_id"] == "V1", (
        f"a water session was reported to ERP as outlet {body['socket_id']!r}; ERP reconciles "
        f"on this string, so Q1 attributes the litres to an electricity socket"
    )
    assert body["session_type"] == "water"
    assert body["water_liters"] == 42.5, (
        f"expected the valve's register, got {body.get('water_liters')!r}"
    )
    assert body["energy_kwh"] is None, (
        f"a water session reported energy_kwh={body['energy_kwh']!r} — socket 1's electricity "
        f"register (987.6) leaking into a water session is a billing fault. None, not 0.0: "
        f"this outlet does not measure kWh, which is different from measuring zero"
    )
    assert body["estimated_cost"] is None, (
        "a euro figure priced from the kWh tariff must not be attached to litres"
    )


def test_tc_six_13b_erp_payload_for_an_electricity_session_is_unchanged(
        client, auth_headers, six_pid):
    """The electricity path must be untouched by the water fix.

    Paired with TC-SIX-13 deliberately: a fix that got water right by breaking electricity
    would pass the case above on its own.
    """
    from app.models.session import Session
    from app.models.socket_config import SocketConfig

    _clear(six_pid)

    db = _S()
    try:
        sc = db.query(SocketConfig).filter(
            SocketConfig.pedestal_id == six_pid, SocketConfig.socket_id == 2).first()
        sc.meter_energy_kwh = 12.25
        sc.meter_power_kw = 2.0
        ses = Session(pedestal_id=six_pid, socket_id=2, type="electricity", status="active",
                      started_at=datetime.utcnow(), nfc_user_id="erp-six-elec")
        db.add(ses)
        db.commit()
        sid = ses.id
    finally:
        db.close()

    r = client.get(f"/api/nfc/session/{sid}", headers=_erp())
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["socket_id"] == "Q2"
    assert body["session_type"] == "electricity"
    assert body["energy_kwh"] == 12.25
    assert body["power_kw_current"] == 2.0
    assert body["water_liters"] is None, (
        "an electricity session must not carry a litre figure, not even 0.0"
    )


# ═══ TC-SIX-14 ════════════════════════════════════════════════════════════════
#
# The app-version gate. A procedure that depends on remembering will eventually be forgotten,
# so the dependency is enforced rather than written down: whoever provisions tags at a new
# site will not have read the commit that introduced them.
#
# What it prevents: an app build from before v3.43 cannot resolve a "V1" outlet label, and its
# session-adoption check treats an unresolved outlet as "matches anything". A customer who
# scans a water tag therefore adopts the next electricity session broadcast under their user
# id. In MODE 2 the pedestal IS the billing system, so that is another customer's consumption
# on their invoice — a wrong charge, not a degraded experience.

import contextlib


@contextlib.contextmanager
def _site_mode(direct_client: bool, app_ready: bool):
    from app.config import settings
    prev = (settings.nfc_direct_client_mode, settings.mobile_app_supports_water_nfc)
    settings.nfc_direct_client_mode = direct_client
    settings.mobile_app_supports_water_nfc = app_ready
    try:
        yield
    finally:
        settings.nfc_direct_client_mode, settings.mobile_app_supports_water_nfc = prev


def test_tc_six_14_water_tag_refused_in_mode_2_before_the_app_ships(
        client, auth_headers, six_pid):
    """MODE 2, app not updated: a valve tag is refused, and the reason is actionable."""
    _clear(six_pid)

    with _site_mode(direct_client=True, app_ready=False):
        r = _provision(client, auth_headers, "SIX-GATE-V1", "V1", "valve")

    assert r.status_code == 409, (
        f"a water tag was provisioned on a mode-2 site with an un-updated app "
        f"({r.status_code}); the next customer to scan it gets someone else's charge"
    )
    detail = r.json()["detail"]
    assert "MOBILE_APP_SUPPORTS_WATER_NFC" in detail, (
        f"the refusal must name the flag to set — an installer cannot act on 'not permitted'; "
        f"got {detail!r}"
    )

    from app.models.nfc_tag import NfcTag
    db = _S()
    try:
        assert db.query(NfcTag).filter(NfcTag.nfc_tag_id == "SIX-GATE-V1").first() is None
    finally:
        db.close()


def test_tc_six_14b_electricity_is_never_gated(client, auth_headers, six_pid):
    """The gate is about water only. Blocking Q1-Q4 would make it a site-wide outage.

    Worth asserting rather than assuming: a guard placed one line too early — before the
    outlet kind is known — would refuse everything, and the symptom would be "NFC stopped
    working at this marina" with nothing pointing at a water flag.
    """
    _clear(six_pid)

    with _site_mode(direct_client=True, app_ready=False):
        r = _provision(client, auth_headers, "SIX-GATE-Q1", "Q1", "socket")

    assert r.status_code == 200, r.text


def test_tc_six_14c_mode_1_is_exempt_without_setting_the_flag(client, auth_headers, six_pid):
    """MODE 1 needs no flag: the ERP resolves the tag and calls /scan itself.

    The order of the two checks matters. If the flag were tested first, every mode-1 site
    would have to set a flag about a dependency it does not have — and a flag you set to make
    an error go away stops meaning anything.
    """
    _clear(six_pid)

    with _site_mode(direct_client=False, app_ready=False):
        r = _provision(client, auth_headers, "SIX-GATE-M1", "V1", "valve")

    assert r.status_code == 200, (
        f"mode 1 was gated on an app version that is not in its path: {r.text}"
    )


def test_tc_six_14d_flag_lifts_the_gate(client, auth_headers, six_pid):
    """Once the app is deployed, water provisioning proceeds."""
    _clear(six_pid)

    with _site_mode(direct_client=True, app_ready=True):
        r = _provision(client, auth_headers, "SIX-GATE-OK", "V2", "valve")

    assert r.status_code == 200, r.text
    assert r.json()["outlet_type"] == "valve"


def test_tc_six_14e_bulk_is_gated_in_the_prepass_not_mid_loop(
        client, auth_headers, six_pid):
    """A batch with a water tag must fail before any of its electricity tags commit.

    Each provision commits individually, so a gate discovered inside the write loop would
    leave the tags before it applied and the ones after it not — a half-provisioned cabinet
    reported as a single failure.
    """
    _clear(six_pid)

    with _site_mode(direct_client=True, app_ready=False):
        r = client.post("/api/nfc/tags/bulk", headers=auth_headers, json={
            "cabinet_id": CAB,
            "items": [
                {"socket_id": "Q1", "nfc_tag_id": "SIX-GATE-B1", "outlet_type": "socket"},
                {"socket_id": "V1", "nfc_tag_id": "SIX-GATE-B2", "outlet_type": "valve"},
            ],
        })

    assert r.status_code == 409, r.text

    from app.models.nfc_tag import NfcTag
    db = _S()
    try:
        assert db.query(NfcTag).filter(NfcTag.nfc_tag_id == "SIX-GATE-B1").first() is None, (
            "the electricity tag committed before the batch was refused"
        )
    finally:
        db.close()


def test_tc_six_14f_the_gate_lives_at_the_write_site(six_pid):
    """Calling the service directly must be gated too, not just the HTTP routes.

    A route-level check protects the routes that existed when it was written. This asserts the
    guard is where the row is created, so a future endpoint, a script, or a migration helper
    cannot bypass it by not knowing about it.
    """
    from app.services import nfc_service
    from app.services.nfc_service import WaterTagBlockedByAppVersion

    _clear(six_pid)
    db = _S()
    try:
        with _site_mode(direct_client=True, app_ready=False):
            with pytest.raises(WaterTagBlockedByAppVersion):
                nfc_service.provision_tag(db, "SIX-GATE-DIRECT", CAB, "V1",
                                          provisioned_by="test@local", outlet_type="valve")
    finally:
        db.close()

# ═══ TC-SIX-15 ════════════════════════════════════════════════════════════════
#
# Valve state, persisted — and the correction that produced it.
#
# I claimed the firmware publishes no valve state, and wrote that into code comments and two
# documents. It was WRONG. `opta/water/V{n}/status` has always carried `state` and
# `hw_status`; the real payload is
#     {"id":"V1","state":"idle","hw_status":"off","ts":…,"total_l":…,"session_l":…}
# The handler broadcast both over the websocket and stored NEITHER, so anything not listening
# at that instant had nowhere to ask — and both the QR landing and the session-live endpoint
# fell back to `socket_states`, which is keyed by outlet number alone and therefore answered
# with the ELECTRICITY socket sharing the valve's number.
#
# That is the failure worth testing: not a missing answer but a plausible WRONG one. "Cable
# detected" on a tap, or "idle" while water ran.


def test_tc_six_15_valve_status_message_is_persisted(six_pid):
    """The state and hw_status in the payload reach the database."""
    import asyncio
    import json
    from unittest.mock import patch, AsyncMock
    from app.services.mqtt_handlers import _handle_marina_water
    from app.models.valve_config import ValveConfig

    with (
        patch("app.services.mqtt_handlers.SessionLocal", _S),
        patch("app.services.mqtt_handlers.ws_manager.broadcast", new=AsyncMock()),
    ):
        asyncio.run(_handle_marina_water(CAB, "V1", json.dumps({
            "id": "V1", "state": "idle", "hw_status": "off",
            "ts": 118475996, "total_l": 12.5, "session_l": 0, "session": None,
        })))

    db = _S()
    try:
        vc = db.query(ValveConfig).filter(
            ValveConfig.pedestal_id == six_pid, ValveConfig.valve_id == 1).first()
        assert vc is not None
        assert vc.last_state == "idle", (
            f"got {vc.last_state!r}. The firmware sent it; broadcasting it and keeping "
            f"nothing is what forced every later reader onto the socket table"
        )
        assert vc.last_hw_status == "off"
        assert vc.state_updated_at is not None, (
            "the age is what says whether the stored state is still worth believing"
        )
    finally:
        db.close()


def test_tc_six_15b_a_valve_never_reports_the_socket_state(client, cust_headers, six_pid):
    """The defect itself: V1 must not be answered from socket 1's plug-in signal.

    Socket 1 is marked physically connected, which makes the electricity answer "pending".
    V1 is given its own stored state of "idle". A reader that consults `socket_states` by
    number returns "pending" — "cable detected" on a water outlet.
    """
    from datetime import timedelta
    from app.models.pedestal_config import SocketState
    from app.models.valve_config import ValveConfig
    from app.routers.mobile import _outlet_state_str
    from app.services.nfc_service import OUTLET_SOCKET, OUTLET_VALVE

    _clear(six_pid)
    db = _S()
    try:
        row = db.query(SocketState).filter(
            SocketState.pedestal_id == six_pid, SocketState.socket_id == 1).first()
        if row is None:
            row = SocketState(pedestal_id=six_pid, socket_id=1)
            db.add(row)
        row.connected = True

        vc = db.query(ValveConfig).filter(
            ValveConfig.pedestal_id == six_pid, ValveConfig.valve_id == 1).first()
        vc.last_state = "idle"
        vc.last_hw_status = "off"
        vc.state_updated_at = datetime.utcnow()
        db.commit()

        assert _outlet_state_str(db, six_pid, 1, OUTLET_SOCKET) == "pending"
        valve_state = _outlet_state_str(db, six_pid, 1, OUTLET_VALVE)
    finally:
        db.close()

    assert valve_state == "idle", (
        f"V1 reported {valve_state!r} while socket 1 was 'pending'. A valve answered from the "
        f"socket table is a plausible wrong answer, which is worse than no answer"
    )


def test_tc_six_15c_a_stale_valve_state_is_unknown_not_idle(six_pid):
    """A state from before the cabinet went quiet is not a current reading.

    Same rule as a retained MQTT replay: a value that merely exists is not evidence of now.
    Reporting the last thing V1 said three days ago as "idle" would tell a customer the outlet
    is free when nothing has been heard from the cabinet since.
    """
    from datetime import timedelta
    from app.models.valve_config import ValveConfig
    from app.routers.mobile import _outlet_state_str, VALVE_STATE_MAX_AGE_S
    from app.services.nfc_service import OUTLET_VALVE

    _clear(six_pid)
    db = _S()
    try:
        vc = db.query(ValveConfig).filter(
            ValveConfig.pedestal_id == six_pid, ValveConfig.valve_id == 2).first()
        vc.last_state = "idle"
        vc.state_updated_at = datetime.utcnow() - timedelta(seconds=VALVE_STATE_MAX_AGE_S + 5)
        db.commit()
        stale = _outlet_state_str(db, six_pid, 2, OUTLET_VALVE)

        vc.state_updated_at = datetime.utcnow()
        db.commit()
        fresh = _outlet_state_str(db, six_pid, 2, OUTLET_VALVE)
    finally:
        db.close()

    assert stale == "unknown", f"a {VALVE_STATE_MAX_AGE_S + 5}s-old state reported as {stale!r}"
    assert fresh == "idle", "a fresh state must be reported as itself, not suppressed"


def test_tc_six_15d_never_reported_is_unknown(six_pid):
    """A valve the cabinet has never described is unknown, not idle.

    Zero and unknown are different values (rule 8); so are "reported idle" and "never
    reported". A customer told "free" about an outlet we know nothing about will walk to it.
    """
    from app.models.valve_config import ValveConfig
    from app.routers.mobile import _outlet_state_str
    from app.services.nfc_service import OUTLET_VALVE

    _clear(six_pid)
    db = _S()
    try:
        vc = db.query(ValveConfig).filter(
            ValveConfig.pedestal_id == six_pid, ValveConfig.valve_id == 2).first()
        vc.last_state = None
        vc.last_hw_status = None
        vc.state_updated_at = None
        db.commit()
        state = _outlet_state_str(db, six_pid, 2, OUTLET_VALVE)
    finally:
        db.close()

    assert state == "unknown", f"an undescribed valve reported {state!r}"

def test_tc_six_15e_outlets_endpoint_carries_the_valve_state(client, auth_headers, six_pid):
    """/outlets exposes valve state so the provisioning table stops showing a dash.

    The dash was a workaround for this bug, not a hardware limitation. Also asserts the
    asymmetry deliberately: an electricity socket's `state` is **null** here, which is not
    "unknown" — socket state lives in the websocket store the UI already subscribes to,
    because plug-in changes must appear without a refetch. A stale "idle" on a socket someone
    just plugged into is the first thing an operator notices.
    """
    from app.models.valve_config import ValveConfig

    _clear(six_pid)
    db = _S()
    try:
        vc = db.query(ValveConfig).filter(
            ValveConfig.pedestal_id == six_pid, ValveConfig.valve_id == 1).first()
        vc.last_state = "idle"
        vc.state_updated_at = datetime.utcnow()
        db.commit()
    finally:
        db.close()

    r = client.get(f"/api/nfc/outlets/{CAB}", headers=auth_headers)
    assert r.status_code == 200, r.text
    outlets = {o["outlet_name"]: o for o in r.json()["outlets"]}

    assert outlets["V1"]["state"] == "idle", (
        f"got {outlets['V1']['state']!r}; the table cannot render a state the endpoint does "
        f"not send, which is why it showed a dash"
    )
    assert outlets["Q1"]["state"] is None, (
        "an electricity socket must send null, not a state: null means 'read the live store'. "
        "Sending a snapshot here would put a second, slower opinion of socket state on screen"
    )
