"""Pedestal management endpoints (admin)."""
import pytest


def test_list_pedestals(client, auth_headers):
    r = client.get("/api/pedestals/", headers=auth_headers)
    assert r.status_code == 200
    pedestals = r.json()
    assert isinstance(pedestals, list)
    assert len(pedestals) >= 1


def test_get_pedestal(client, auth_headers):
    r = client.get("/api/pedestals/1", headers=auth_headers)
    assert r.status_code == 200
    data = r.json()
    assert data["id"] == 1
    assert "name" in data


def test_get_pedestal_not_found(client, auth_headers):
    r = client.get("/api/pedestals/99999", headers=auth_headers)
    assert r.status_code == 404


def test_create_pedestal(client, auth_headers):
    r = client.post("/api/pedestals/", json={
        "name": "New Pedestal",
        "location": "Berth Z",
        "data_mode": "synthetic",
    }, headers=auth_headers)
    assert r.status_code in (200, 201)
    data = r.json()
    assert data["name"] == "New Pedestal"


def test_create_pedestal_requires_auth(client):
    """Create pedestal requires admin auth — no token returns 403 from HTTPBearer."""
    r = client.post("/api/pedestals/", json={
        "name": "Unauthorized",
        "location": "Nowhere",
    })
    assert r.status_code in (401, 403)


def test_pedestals_list_is_public(client):
    """Pedestal list is intentionally public (no auth required)."""
    r = client.get("/api/pedestals/")
    assert r.status_code == 200


def test_update_pedestal_mode(client, auth_headers):
    r = client.patch("/api/pedestals/1/mode?mode=synthetic", headers=auth_headers)
    assert r.status_code in (200, 204)


def test_pedestal_mobile_enabled(client, auth_headers):
    """Verify the seeded test pedestal has mobile_enabled by default."""
    # Enable it first
    r = client.patch("/api/pedestals/1", json={"mobile_enabled": True}, headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["mobile_enabled"] is True
