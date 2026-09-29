"""
NFC object-level authorisation (v3.43)
=====================================

The defect these cover, stated once so the tests are readable as a rule rather than a list:

**Authentication answers "who is this". It never answers "may this caller touch this record".**
Four NFC endpoints checked the X-API-Key and then acted on whatever session id or `user_id` the
request named. A valid key is not a claim to a particular record.

It matters more than an ordinary access bug because of what the records are:

* **MODE 2** (`nfc_direct_client_mode`, marinas with no ERP) — **the pedestal is the billing
  system.** Our session rows are the only record of what anyone owes, so reading or stopping
  someone else's session is tampering with a financial record, not merely seeing data.
* **MODE 1** (with ERP) — ERP bills, and reconciles against `sessions.nfc_user_id`. A forged
  identifier corrupts reconciliation *silently*, because the two systems compare totals.

And the credential is not a secret: the mobile app ships it as `EXPO_PUBLIC_ERP_API_KEY`, which
Expo compiles into the bundle. A boundary is only as good as who holds the credential.

The fix needed no app release, because the right principal was already on the wire — the app's
axios interceptor attaches `Authorization: Bearer <customer JWT>` to every request
(`mobile/src/api/client.ts:19-20`) and the backend was discarding it in favour of the body.

  TC-NFCA-01  scan: a forged user_id is refused, not silently accepted
  TC-NFCA-02  scan: the stored attribution comes from the principal, not the body
  TC-NFCA-03  scan: ERP with no customer token is unaffected (MODE 1 server-to-server)
  TC-NFCA-04  read: a customer cannot read another customer's session
  TC-NFCA-05  read: a customer CAN read their own
  TC-NFCA-06  stop: a customer cannot stop another customer's session — and it keeps running
  TC-NFCA-07  stop: ownership is checked BEFORE the already-ended check (no state probing)
  TC-NFCA-08  by-user: a customer cannot list another user's sessions
  TC-NFCA-09  MODE 2: the bare machine key is refused — the checks are not bypassable
  TC-NFCA-10  an expired/invalid customer token is 401, never a silent downgrade to anonymous
"""
from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

TEST_DB = "sqlite:///./tests/test_pedestal.db"
_engine = create_engine(TEST_DB, connect_args={"check_same_thread": False})
_S = sessionmaker(autocommit=False, autoflush=False, bind=_engine)

ERP_KEY = "test-erp-key-v343"
CAB = "TST_AUTHZ_CAB"


@pytest.fixture(autouse=True)
def _erp_key():
    from app.config import settings
    prev = settings.erp_api_key
    settings.erp_api_key = ERP_KEY
    yield
    settings.erp_api_key = prev


@pytest.fixture(autouse=True)
def _mode_1_by_default():
    """Default every test to MODE 1; TC-NFCA-09 opts into MODE 2 explicitly."""
    from app.config import settings
    prev = settings.nfc_direct_client_mode
    settings.nfc_direct_client_mode = False
    yield
    settings.nfc_direct_client_mode = prev


def _erp() -> dict:
    return {"X-API-Key": ERP_KEY}


def _both(token: str) -> dict:
    """What the mobile app actually sends: the machine key AND a customer token.

    Worth spelling out, because it is the crux — the app has always sent both, so the server
    had a usable principal available and ignored it.
    """
    return {"X-API-Key": ERP_KEY, "Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def authz_pid(client, auth_headers):
    """A real pedestal with a cabinet id and four socket rows.

    Seeded directly rather than through the config endpoint, matching `test_nfc.py`'s
    `nfc_pid` — the NFC tag lookup resolves `cabinet_id` via `PedestalConfig.opta_client_id`,
    and a scan 404s without it.
    """
    from app.models.pedestal_config import PedestalConfig
    from app.models.socket_config import SocketConfig

    r = client.post("/api/pedestals/", json={
        "name": "AuthZ Test Pedestal", "location": "AuthZ Dock", "data_mode": "real",
    }, headers=auth_headers)
    assert r.status_code in (200, 201), r.text
    pid = r.json()["id"]

    db = _S()
    try:
        cfg = db.query(PedestalConfig).filter(
            PedestalConfig.pedestal_id == pid).first()
        if cfg is None:
            cfg = PedestalConfig(pedestal_id=pid)
            db.add(cfg)
        cfg.opta_client_id = CAB
        cfg.berth_ref = "VEZ_Z9"
        cfg.provisioning_mode = "qr"
        for sid in (1, 2, 3, 4):
            if db.query(SocketConfig).filter(
                    SocketConfig.pedestal_id == pid,
                    SocketConfig.socket_id == sid).first() is None:
                db.add(SocketConfig(pedestal_id=pid, socket_id=sid, auto_activate=True))
        db.commit()
    finally:
        db.close()
    return pid


@pytest.fixture(scope="module")
def two_customers(client):
    """Two real customers with real tokens. Ownership is meaningless with only one."""
    out = []
    for n in (1, 2):
        email = f"authz{n}@example.com"
        client.post("/api/customer/auth/register", json={
            "email": email, "password": "customer1234",
            "name": f"AuthZ {n}", "ship_name": f"Vessel {n}",
        })
        r = client.post("/api/customer/auth/login",
                        json={"email": email, "password": "customer1234"})
        assert r.status_code == 200, r.text
        me = client.get("/api/customer/auth/me",
                        headers={"Authorization": f"Bearer {r.json()['access_token']}"})
        out.append({
            "email": email,
            "token": r.json()["access_token"],
            "id": me.json()["id"],
        })
    return out


def _seed_session(pid: int, socket_id: int, nfc_user_id: str, *,
                  status: str = "active", customer_id: int | None = None) -> int:
    from app.models.session import Session

    db = _S()
    try:
        s = Session(
            pedestal_id=pid, socket_id=socket_id, type="electricity",
            status=status, started_at=datetime.utcnow(),
            nfc_user_id=nfc_user_id, customer_id=customer_id,
        )
        db.add(s)
        db.commit()
        return s.id
    finally:
        db.close()


def _session_status(session_id: int) -> str:
    from app.models.session import Session

    db = _S()
    try:
        return db.get(Session, session_id).status
    finally:
        db.close()


def _provision(client, auth_headers, tag: str, socket: str = "Q1") -> None:
    client.post("/api/nfc/tags", headers=auth_headers,
                json={"cabinet_id": CAB, "socket_id": socket, "nfc_tag_id": tag})


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


# ─── scan: attribution ───────────────────────────────────────────────────────

def test_tc_nfca_01_forged_user_id_is_refused(client, auth_headers, authz_pid,
                                              two_customers):
    """Customer A signs in and claims to be customer B. Refused, loudly.

    This is the endpoint that decides who pays. Accepting a body value the caller simply
    asserted is how one customer's charge lands on another's account — and in MODE 2 there is
    no second record that would ever disagree.
    """
    _clear(authz_pid)
    _provision(client, auth_headers, "TAG-A1")
    a, b = two_customers

    r = client.post("/api/nfc/scan", headers=_both(a["token"]),
                    json={"nfc_tag_id": "TAG-A1", "user_id": b["email"]})
    assert r.status_code == 403, \
        f"a forged user_id was accepted with {r.status_code}: {r.text}"
    assert "does not match" in r.json()["detail"].lower()


def test_tc_nfca_02_attribution_comes_from_the_principal(client, auth_headers,
                                                         authz_pid, two_customers):
    """What gets stored is the authenticated identity, not the spelling the client sent."""
    from app.models.nfc_pending_session import NfcPendingSession

    _clear(authz_pid)
    _provision(client, auth_headers, "TAG-A2")
    a, _b = two_customers

    # The customer's own id, in the other accepted spelling.
    r = client.post("/api/nfc/scan", headers=_both(a["token"]),
                    json={"nfc_tag_id": "TAG-A2", "user_id": str(a["id"])})
    assert r.status_code == 200, r.text

    db = _S()
    try:
        rec = db.query(NfcPendingSession).order_by(
            NfcPendingSession.id.desc()).first()
        assert rec is not None
        assert rec.user_id == a["email"], (
            f"attribution stored as {rec.user_id!r}; it must normalise to the authenticated "
            f"identity so reconciliation is stable regardless of client spelling"
        )
    finally:
        db.close()


def test_tc_nfca_03_erp_server_to_server_is_unaffected(client, auth_headers, authz_pid):
    """MODE 1: ERP calls with the key and no customer token, and asserts its own user ids.

    ERP is the authority on its own identifiers, so this path must keep working exactly as
    before — the fix must not turn a supported topology into a 403.
    """
    _clear(authz_pid)
    _provision(client, auth_headers, "TAG-A3")

    r = client.post("/api/nfc/scan", headers=_erp(),
                    json={"nfc_tag_id": "TAG-A3", "user_id": "erp-user-999"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "pending"


# ─── read ────────────────────────────────────────────────────────────────────

def test_tc_nfca_04_cannot_read_another_customers_session(client, authz_pid,
                                                          two_customers):
    """404, not 403 — a distinct refusal would confirm the session exists.

    The payload carries energy, duration and estimated cost. Session ids are sequential
    integers, so anything that distinguishes "not yours" from "not there" is enough to walk
    the table.
    """
    _clear(authz_pid)
    a, b = two_customers
    sid = _seed_session(authz_pid, 1, b["email"])

    r = client.get(f"/api/nfc/session/{sid}", headers=_both(a["token"]))
    assert r.status_code == 404, \
        f"customer A read customer B's session: {r.status_code} {r.text}"
    assert "not found" in r.json()["detail"].lower(), \
        "the refusal must not distinguish 'not yours' from 'not there'"


def test_tc_nfca_05_can_read_own_session(client, authz_pid, two_customers):
    """The check must not lock customers out of their own data."""
    _clear(authz_pid)
    a, _b = two_customers
    sid = _seed_session(authz_pid, 1, a["email"])

    r = client.get(f"/api/nfc/session/{sid}", headers=_both(a["token"]))
    assert r.status_code == 200, r.text
    assert r.json()["session_id"] == sid

    # And by the customer_id link, for a session claimed through the app rather than NFC.
    sid2 = _seed_session(authz_pid, 2, "someone-elses-string",
                         customer_id=a["id"])
    r2 = client.get(f"/api/nfc/session/{sid2}", headers=_both(a["token"]))
    assert r2.status_code == 200, \
        f"ownership via customer_id was not honoured: {r2.text}"


# ─── stop ────────────────────────────────────────────────────────────────────

def test_tc_nfca_06_cannot_stop_another_customers_session(client, authz_pid,
                                                          two_customers):
    """The check with a physical consequence: cutting power to another berth mid-charge."""
    _clear(authz_pid)
    a, b = two_customers
    sid = _seed_session(authz_pid, 1, b["email"], status="active")

    r = client.post(f"/api/nfc/session/{sid}/stop", headers=_both(a["token"]))
    assert r.status_code == 404, \
        f"customer A stopped customer B's session: {r.status_code} {r.text}"

    # The assertion that actually matters: it is still running.
    assert _session_status(sid) == "active", \
        "the session was stopped despite the request being refused"


def test_tc_nfca_07_ownership_is_checked_before_state(client, authz_pid, two_customers):
    """Order matters. A 409 'already ended' would confirm the session exists.

    Same reasoning as the 404 above: the response must not differ based on a record the caller
    has no right to observe.
    """
    _clear(authz_pid)
    a, b = two_customers
    ended = _seed_session(authz_pid, 1, b["email"], status="completed")

    r = client.post(f"/api/nfc/session/{ended}/stop", headers=_both(a["token"]))
    assert r.status_code == 404, (
        f"got {r.status_code} — ownership must be checked before the already-ended check, "
        f"or the response leaks the session's state to a stranger"
    )


# ─── by-user ─────────────────────────────────────────────────────────────────

def test_tc_nfca_08_cannot_list_another_users_sessions(client, authz_pid, two_customers):
    """403 here, and deliberately: the user_id was supplied by the caller.

    Refusing it plainly leaks nothing they did not type, whereas a silent empty list would read
    as "you have no sessions" when the truth is "that is not you".
    """
    _clear(authz_pid)
    a, b = two_customers
    _seed_session(authz_pid, 1, b["email"])

    r = client.get(f"/api/nfc/sessions/by-user/{b['email']}",
                   headers=_both(a["token"]))
    assert r.status_code == 403, \
        f"customer A listed customer B's sessions: {r.status_code} {r.text}"

    own = client.get(f"/api/nfc/sessions/by-user/{a['email']}",
                     headers=_both(a["token"]))
    assert own.status_code == 200, f"a customer must still list their own: {own.text}"


# ─── the bypass, and the mode that closes it ─────────────────────────────────

def test_tc_nfca_09_mode_2_refuses_the_bare_machine_key(client, authz_pid,
                                                        two_customers):
    """A check an attacker opts out of by sending FEWER headers is not a check.

    Every test above presents a customer token. Omit it and the caller falls back to being
    "the ERP" — with a key that is compiled into the mobile app bundle and must be assumed
    known. In MODE 2, where our rows ARE the billing record, that fallback is closed: a
    per-customer principal is required, because a shared machine key cannot express "this
    customer, this session".

    MODE 1 still accepts the bare key, because there the caller really is ERP's server. The
    remaining exposure there is the app holding the key at all, which is a separate change plus
    a key rotation — and this test documents that boundary rather than pretending it is shut.
    """
    from app.config import settings

    _clear(authz_pid)
    a, b = two_customers
    sid = _seed_session(authz_pid, 1, b["email"], status="active")

    # MODE 1: the bare key is accepted — ERP's legitimate path, and the known gap.
    assert client.get(f"/api/nfc/session/{sid}", headers=_erp()).status_code == 200

    settings.nfc_direct_client_mode = True

    assert client.get(f"/api/nfc/session/{sid}", headers=_erp()).status_code == 401
    assert client.post(f"/api/nfc/session/{sid}/stop",
                       headers=_erp()).status_code == 401
    assert client.get(f"/api/nfc/sessions/by-user/{b['email']}",
                      headers=_erp()).status_code == 401
    assert _session_status(sid) == "active", "the refused stop still ran"

    # ...and a signed-in customer still works in MODE 2.
    own = _seed_session(authz_pid, 2, a["email"], status="active")
    assert client.get(f"/api/nfc/session/{own}",
                      headers=_both(a["token"])).status_code == 200


def test_tc_nfca_10_invalid_customer_token_is_401_not_anonymous(client, authz_pid,
                                                                two_customers):
    """A bad token must not silently downgrade to "no principal".

    Otherwise an expired session quietly loses its ownership checks and falls back to the
    machine-key path — the failure mode would be indistinguishable from working correctly.
    """
    _clear(authz_pid)
    _a, b = two_customers
    sid = _seed_session(authz_pid, 1, b["email"])

    r = client.get(f"/api/nfc/session/{sid}",
                   headers={"X-API-Key": ERP_KEY,
                            "Authorization": "Bearer not-a-real-token"})
    assert r.status_code == 401, (
        f"an invalid token produced {r.status_code}; it must not be treated as anonymous, "
        f"which would fall through to the machine-key path and read another's session"
    )
