"""Vessel matching is "configured" when the berth has a photo to match against — 2026-10-15.

FOUND while building wizard step 3 (block 4): the marina screens decided
`vessel_match_configured` from `berths.reference_image`. Nothing that uploads a photo writes
that column — not the admin upload (`POST /api/admin/berths/{id}/reference-images`), not the
ERP push (`/api/ext/.../reference-image`); both write FILES, and the matcher
(`compute_match_score`) compares against those files. Only the first-start seed sets the
column ("Full_Berth.jpg" on berth 1). So the screen said "matched against a photo" for a berth
with no photo, and "no reference photo is set" for a berth that had one and was being checked.

  TC-VMC-01  the column alone, with no photo: NOT configured (and no match verdict)
  TC-VMC-02  a photo uploaded through the admin endpoint: configured, on L1 and L2;
             removed again: not configured

Both FAIL on the code before this change (shown 2026-10-15).
"""
from __future__ import annotations

import pytest

from conftest import TestSession as _S, TestUserSession as _US


@pytest.fixture(scope="module")
def pedestal(client, auth_headers):
    from app.models.pedestal_config import PedestalConfig
    r = client.post("/api/pedestals/", json={"name": "VMC Pedestal", "location": "Dock M",
                                              "data_mode": "real"}, headers=auth_headers)
    assert r.status_code in (200, 201), r.text
    pid = r.json()["id"]
    db = _S()
    try:
        if db.query(PedestalConfig).filter(PedestalConfig.pedestal_id == pid).first() is None:
            db.add(PedestalConfig(pedestal_id=pid))
            db.commit()
    finally:
        db.close()
    return pid


def _berth(pid: int, number: int, **cols) -> int:
    from app.auth.berth_models import Berth
    udb = _US()
    try:
        b = Berth(name=f"VMC {number}", pedestal_id=pid, berth_number=number, **cols)
        udb.add(b)
        udb.commit()
        return b.id
    finally:
        udb.close()


def _core_row(client, headers, bid):
    r = client.get("/api/marina/berths", headers=headers)
    assert r.status_code == 200, r.text
    rows = [b for p in r.json()["pedestals"] for b in p["berths"] if b["berth_id"] == bid]
    assert len(rows) == 1, f"berth {bid} not in the core payload"
    return rows[0]


def _detail(client, headers, bid):
    r = client.get(f"/api/marina/berths/{bid}", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def test_tc_vmc_01_the_column_alone_is_not_a_photo(client, auth_headers, pedestal):
    # What the seed does to berth 1: the column names a file, and there is no file.
    bid = _berth(pedestal, 1, reference_image="Full_Berth.jpg", state_code=2, occupied_bit=1)
    for where, row in (("L1", _core_row(client, auth_headers, bid)),
                       ("L2", _detail(client, auth_headers, bid))):
        assert row["vessel_match_configured"] is False, \
            f"{where}: 'configured' with no photo to match against"
        assert row["vessel_matches"] is None, f"{where}: a match verdict with no photo"


def test_tc_vmc_02_an_uploaded_photo_configures_matching(client, auth_headers, pedestal):
    bid = _berth(pedestal, 2)
    assert _detail(client, auth_headers, bid)["vessel_match_configured"] is False

    r = client.post(f"/api/admin/berths/{bid}/reference-images", headers=auth_headers,
                    files={"files": ("boat.jpg", b"\xff\xd8\xff\xe0 jpeg", "image/jpeg")})
    assert r.status_code == 200 and r.json()["count"] == 1, r.text
    name = r.json()["saved"][0]
    assert _core_row(client, auth_headers, bid)["vessel_match_configured"] is True, \
        "L1: a berth with a photo reads as not configured"
    assert _detail(client, auth_headers, bid)["vessel_match_configured"] is True, \
        "L2: a berth with a photo reads 'No reference photo is set'"

    r = client.delete(f"/api/admin/berths/{bid}/reference-images/{name}", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert _detail(client, auth_headers, bid)["vessel_match_configured"] is False, \
        "the last photo removed, still configured"
