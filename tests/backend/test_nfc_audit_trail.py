"""
NFC audit trail + billing-authority visibility (v3.43)
=====================================================

Rule 2 of the access-control plan, and decision 8.

**The audit trail gap.** A tag's row survives removal (`is_active=False`), so the history was
there — but nothing recorded *who* un-pointed it or *when*. Creation was attributable and
removal was not, which made the one destructive act in a tag's life the only untraceable one.
For a control that decides which socket a customer's tap energises, that is the wrong way round.

**`provisioned_by` is now required**, not defaulted. A caller with no actor has a bug, and
writing "(unknown)" would hide it — so the service raises instead. The column stays nullable
for rows written before v3.43, because backfilling a guess is worse than an honest NULL.

**Billing authority is visible.** A pedestal must know whether it bills or merely measures, and
so must whoever is looking at a disputed charge. Explicit configuration, never inferred: the
tempting signal ("is erp_api_key set?") is set in BOTH topologies today.

  TC-NFCT-01  removing a tag records who and when
  TC-NFCT-02  provisioning without an actor is refused, not silently attributed
  TC-NFCT-03  the trail is visible through the API, not only in the database
  TC-NFCT-04  re-provisioning the same socket leaves the old row attributable
  TC-NFCT-05  health reports the billing authority, and it follows the mode
  TC-NFCT-06  the authority is configuration, not inferred from erp_api_key
"""
from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

TEST_DB = "sqlite:///./tests/test_pedestal.db"
_engine = create_engine(TEST_DB, connect_args={"check_same_thread": False})
_S = sessionmaker(autocommit=False, autoflush=False, bind=_engine)

CAB = "TST_AUDIT_CAB"


@pytest.fixture(scope="module")
def audit_pid(client, auth_headers):
    from app.models.pedestal_config import PedestalConfig

    r = client.post("/api/pedestals/", json={
        "name": "Audit Trail Pedestal", "location": "Audit Dock", "data_mode": "real",
    }, headers=auth_headers)
    pid = r.json()["id"]
    db = _S()
    try:
        cfg = db.query(PedestalConfig).filter(PedestalConfig.pedestal_id == pid).first()
        if cfg is None:
            cfg = PedestalConfig(pedestal_id=pid)
            db.add(cfg)
        cfg.opta_client_id = CAB
        db.commit()
    finally:
        db.close()
    return pid


@pytest.fixture(autouse=True)
def _clear_tags():
    from app.models.nfc_tag import NfcTag

    db = _S()
    try:
        db.query(NfcTag).filter(NfcTag.cabinet_id == CAB).delete()
        db.commit()
    finally:
        db.close()
    yield


def _tags(active_only: bool = False) -> list:
    from app.models.nfc_tag import NfcTag

    db = _S()
    try:
        q = db.query(NfcTag).filter(NfcTag.cabinet_id == CAB)
        if active_only:
            q = q.filter(NfcTag.is_active.is_(True))
        return q.all()
    finally:
        db.close()


# ═══ TC-NFCT-01 ══════════════════════════════════════════════════════════════

def test_tc_nfct_01_removal_records_who_and_when(client, auth_headers, audit_pid):
    """Removal is now as attributable as creation."""
    client.post("/api/nfc/tags", headers=auth_headers,
                json={"cabinet_id": CAB, "socket_id": "Q1", "nfc_tag_id": "AUDIT-1"})
    before = datetime.utcnow()

    r = client.delete(f"/api/nfc/tags/{CAB}/Q1", headers=auth_headers)
    assert r.status_code == 200, r.text

    rows = _tags()
    assert len(rows) == 1, "the row must survive removal — history is the point"
    tag = rows[0]
    assert tag.is_active is False
    assert tag.removed_by, "nothing recorded WHO removed the tag"
    assert "@" in tag.removed_by, f"expected an admin email, got {tag.removed_by!r}"
    assert tag.removed_at is not None, "nothing recorded WHEN the tag was removed"
    assert tag.removed_at >= before.replace(microsecond=0), \
        "removed_at is not the time of this removal"


# ═══ TC-NFCT-02 ══════════════════════════════════════════════════════════════

def test_tc_nfct_02_provisioning_without_an_actor_is_refused(audit_pid):
    """A ValueError, not a silent "(unknown)".

    Every HTTP path supplies the admin's email, so this guards the service layer against a
    future caller — a script, a migration, a bulk import — that does not. An unattributed
    mapping decides who pays and cannot be traced.
    """
    from app.services import nfc_service

    db = _S()
    try:
        for actor in (None, "", "   "):
            with pytest.raises(ValueError) as exc:
                nfc_service.provision_tag(db, "AUDIT-NOACTOR", CAB, "Q2",
                                          provisioned_by=actor)
            assert "provisioned_by" in str(exc.value)
        assert _tags() == [], "a refused provision must write nothing"
    finally:
        db.close()


# ═══ TC-NFCT-03 ══════════════════════════════════════════════════════════════

def test_tc_nfct_03_trail_is_visible_through_the_api(client, auth_headers, audit_pid):
    """A trail only readable with sqlite3 is a trail nobody consults during an incident."""
    client.post("/api/nfc/tags", headers=auth_headers,
                json={"cabinet_id": CAB, "socket_id": "Q3", "nfc_tag_id": "AUDIT-3"})

    listed = client.get(f"/api/nfc/tags/{CAB}", headers=auth_headers).json()
    active = [t for t in listed if t["nfc_tag_id"] == "AUDIT-3"]
    assert active, f"provisioned tag missing from the listing: {listed}"
    assert active[0]["provisioned_by"], "provisioned_by is not surfaced"
    assert active[0]["removed_at"] is None, "an active tag must not look removed"
    assert active[0]["removed_by"] is None


# ═══ TC-NFCT-04 ══════════════════════════════════════════════════════════════

def test_tc_nfct_04_replacing_a_tag_leaves_the_old_row_attributable(
        client, auth_headers, audit_pid):
    """Re-pointing a socket to a different tag is the case the trail exists for.

    The old row is deactivated rather than deleted, so after a dispute you can still see which
    tag used to energise this socket and who provisioned it.
    """
    client.post("/api/nfc/tags", headers=auth_headers,
                json={"cabinet_id": CAB, "socket_id": "Q4", "nfc_tag_id": "AUDIT-OLD"})
    client.post("/api/nfc/tags", headers=auth_headers,
                json={"cabinet_id": CAB, "socket_id": "Q4", "nfc_tag_id": "AUDIT-NEW"})

    rows = {t.nfc_tag_id: t for t in _tags()}
    assert set(rows) == {"AUDIT-OLD", "AUDIT-NEW"}, \
        f"history was not kept: {sorted(rows)}"
    assert rows["AUDIT-OLD"].is_active is False
    assert rows["AUDIT-NEW"].is_active is True
    assert rows["AUDIT-OLD"].provisioned_by, \
        "the superseded mapping lost its attribution, which is what a dispute needs"


# ═══ TC-NFCT-05 / 06 — billing authority ═════════════════════════════════════

def test_tc_nfct_05_health_reports_the_billing_authority(client, auth_headers):
    """Whoever looks at a disputed charge can see which system owns the number."""
    from app.config import settings

    prev = settings.nfc_direct_client_mode
    try:
        settings.nfc_direct_client_mode = False
        erp = client.get("/api/system/health", headers=auth_headers).json()
        assert erp["billing_authority"]["mode"] == "erp"
        assert erp["billing_authority"]["bills"] == "ERP"
        assert "reconciliation" in erp["billing_authority"]["description"].lower()

        settings.nfc_direct_client_mode = True
        direct = client.get("/api/system/health", headers=auth_headers).json()
        auth = direct["billing_authority"]
        assert auth["mode"] == "direct"
        assert auth["bills"] == "this pedestal"
        assert "only record" in auth["description"].lower(), (
            "the direct-mode description must say our rows are the only record — that is the "
            f"whole consequence of the mode: {auth['description']}"
        )
        # Decision 9: point at the ledger, so nobody builds billing off sessions later.
        assert "energy_intervals" in auth["record_of_truth"]
    finally:
        settings.nfc_direct_client_mode = prev


def test_tc_nfct_06_authority_is_configuration_not_inferred(client, auth_headers):
    """It must not be derived from whether an ERP key happens to be set.

    That signal is present in BOTH topologies today — the mobile app uses the key in mode 2 —
    so inferring from it would report the wrong billing authority, and a system that guesses
    whether it is the billing authority guesses wrong exactly once.
    """
    from app.config import settings

    prev_mode = settings.nfc_direct_client_mode
    prev_key = settings.erp_api_key
    try:
        # An ERP key set while the marina is in direct mode must NOT flip the answer.
        settings.nfc_direct_client_mode = True
        settings.erp_api_key = "a-key-is-present-anyway"
        body = client.get("/api/system/health", headers=auth_headers).json()
        assert body["billing_authority"]["mode"] == "direct", (
            "the billing authority followed erp_api_key rather than the configured mode"
        )

        # And no key in ERP mode must not flip it either.
        settings.nfc_direct_client_mode = False
        settings.erp_api_key = None
        body2 = client.get("/api/system/health", headers=auth_headers).json()
        assert body2["billing_authority"]["mode"] == "erp"
    finally:
        settings.nfc_direct_client_mode = prev_mode
        settings.erp_api_key = prev_key
