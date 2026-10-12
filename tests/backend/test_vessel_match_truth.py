"""`vessel_matches` says "does not match" only when the analysis SAID so — block 3, 2026-10-12.

`berths.match_ok_bit` defaults to 0, and 0 was read as "the boat does not match the photo".
But the analyzer (services/berth_analyzer.py) leaves it 0 in five situations, and only ONE of
them is a mismatch:

  never analysed           last_analyzed NULL
  the analysis failed      snapshot error / thermal suspension: everything 0, error set
  the berth is empty       no boat — nothing to match
  no reference embedding   a boat, state_code 1, but no score to compare
  a real mismatch          state_code 2 (score below threshold)            → False

The marina saw "does not match the photo" for a berth nobody had looked at — an untrue sentence
to a person who acts on it (the owner, 2026-10-12). Now: True only when match_ok_bit is 1,
False only when state_code is 2, null — NOT KNOWN — otherwise.

  TC-VMT-01  each of the five situations, plus a real match, through the HTTP detail route

The not-known cases FAIL on the code before this change (shown 2026-10-12).
"""
from __future__ import annotations

from datetime import datetime

import pytest

from conftest import TestSession as _S, TestUserSession as _US


@pytest.fixture(scope="module")
def berth(client, auth_headers):
    from app.models.pedestal_config import PedestalConfig
    from app.auth.berth_models import Berth
    r = client.post("/api/pedestals/", json={"name": "VMT Pedestal", "location": "Dock V",
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
    udb = _US()
    try:
        b = Berth(name="VMT 1", pedestal_id=pid, berth_number=1, reference_image="ref.jpg")
        udb.add(b)
        udb.commit()
        return b.id
    finally:
        udb.close()


def _set(bid, **fields):
    from app.auth.berth_models import Berth
    udb = _US()
    try:
        b = udb.get(Berth, bid)
        for k, v in fields.items():
            setattr(b, k, v)
        udb.commit()
    finally:
        udb.close()


NOW = datetime(2026, 10, 12, 12, 0)
CASES = [
    ("never analysed", dict(last_analyzed=None, occupied_bit=0, match_ok_bit=0, state_code=0,
                            match_score=None, analysis_error=None), None),
    ("analysis failed", dict(last_analyzed=NOW, occupied_bit=0, match_ok_bit=0, state_code=0,
                             match_score=None, analysis_error="Snapshot failed: timeout"), None),
    ("berth empty", dict(last_analyzed=NOW, occupied_bit=0, match_ok_bit=0, state_code=0,
                         match_score=None, analysis_error=None), None),
    ("boat, no reference embedding", dict(last_analyzed=NOW, occupied_bit=1, match_ok_bit=0,
                                          state_code=1, match_score=None, analysis_error=None), None),
    ("real mismatch", dict(last_analyzed=NOW, occupied_bit=1, match_ok_bit=0, state_code=2,
                           match_score=0.21, analysis_error=None), False),
    ("real match", dict(last_analyzed=NOW, occupied_bit=1, match_ok_bit=1, state_code=1,
                        match_score=0.83, analysis_error=None), True),
]


@pytest.mark.parametrize("label,fields,expected", CASES, ids=[c[0] for c in CASES])
def test_tc_vmt_01_vessel_matches_only_says_what_was_measured(client, auth_headers, berth,
                                                              label, fields, expected):
    _set(berth, **fields)
    r = client.get(f"/api/marina/berths/{berth}", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["vessel_matches"] is expected, f"{label}: got {r.json()['vessel_matches']!r}"
