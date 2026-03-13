"""Health and system endpoint tests."""


def test_health_ok(client):
    r = client.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert "mqtt_connected" in data
    assert "simulator_running" in data


def test_system_health(client, auth_headers):
    r = client.get("/api/system/health", headers=auth_headers)
    assert r.status_code == 200


def test_health_no_auth_required(client):
    """Health endpoint is public."""
    r = client.get("/health")
    assert r.status_code == 200
