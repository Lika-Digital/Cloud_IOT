"""Regression guard for v3.15 multi-sector berths.

Several berth "sectors" can share one camera/pedestal, each with its own
detection zone. GET /api/berths must return ALL of them (no de-dup by
pedestal_id). This locks in the fix to list_berths' old "one per pedestal"
collapse.
"""
from __future__ import annotations

import pytest

PEDESTAL_ID = 1  # seeded by conftest


@pytest.fixture
def created_berths(client, auth_headers):
    """Create two sectors on the same camera; clean them up afterwards."""
    ids = []
    for name in ("Sector A", "Sector B"):
        r = client.post("/api/admin/berths",
                        json={"name": name, "pedestal_id": PEDESTAL_ID, "berth_type": "transit"},
                        headers=auth_headers)
        assert r.status_code == 200, r.text
        ids.append(r.json()["id"])
    yield ids
    for bid in ids:
        client.delete(f"/api/admin/berths/{bid}", headers=auth_headers)


def test_multiple_sectors_same_camera_all_listed(client, auth_headers, created_berths):
    id_a, id_b = created_berths
    listed = client.get("/api/berths", headers=auth_headers).json()
    ids_for_camera = [b["id"] for b in listed if b["pedestal_id"] == PEDESTAL_ID]
    # Both sectors must appear (the old code returned only the first per pedestal).
    assert id_a in ids_for_camera, "first sector missing from /api/berths"
    assert id_b in ids_for_camera, "second sector on same camera was dropped (dedup regression)"
    assert len(ids_for_camera) >= 2


def test_availability_lists_sibling_sectors(client, auth_headers, created_berths):
    id_a, id_b = created_berths
    r = client.get("/api/berths/availability",
                   params={"check_in": "2099-01-01", "check_out": "2099-01-05"},
                   headers=auth_headers)
    assert r.status_code == 200, r.text
    free_ids = {b["id"] for b in r.json()}
    # Both free sibling sectors should be offered, not just one.
    assert {id_a, id_b}.issubset(free_ids)
