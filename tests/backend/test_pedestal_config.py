"""
Functional tests for pedestal configuration settings.

Covers the full settings workflow an operator would use:
  1. Read default config (auto-created on first access)
  2. Update camera connection settings
  3. Update MQTT / Arduino settings
  4. Update temperature sensor settings
  5. Sensor CRUD: add, list, update, delete custom MQTT sensors
  6. Pedestal feature toggles: mobile_enabled, ai_enabled
  7. Access control: config endpoints require admin
  8. Health status endpoint (public)
  9. mobile_enabled=False hides pedestal from customer app
"""
import pytest


# ─── Config GET / PUT ─────────────────────────────────────────────────────────

def test_get_config_auto_creates(client, auth_headers):
    """GET config for a pedestal that has no config row creates one."""
    r = client.get("/api/admin/pedestal/1/config", headers=auth_headers)
    assert r.status_code == 200
    data = r.json()
    assert data["pedestal_id"] == 1
    # Default fields present
    assert "camera_stream_url" in data
    assert "camera_reachable" in data
    assert "opta_connected" in data
    assert "sensors" in data
    assert isinstance(data["sensors"], list)


def test_get_config_requires_admin(client):
    """Config endpoint must reject unauthenticated requests."""
    r = client.get("/api/admin/pedestal/1/config")
    assert r.status_code in (401, 403)


def test_get_config_unknown_pedestal(client, auth_headers):
    """404 for a pedestal that doesn't exist."""
    r = client.get("/api/admin/pedestal/99999/config", headers=auth_headers)
    assert r.status_code == 404


def test_update_camera_settings(client, auth_headers):
    """Operator sets camera stream URL and credentials — credentials are auto-injected into URL."""
    payload = {
        "camera_stream_url": "rtsp://192.168.1.200:554/live",
        "camera_username": "admin",
        "camera_password": "secret",
        "camera_fqdn": "cam.marina.local",
    }
    r = client.put("/api/admin/pedestal/1/config", json=payload, headers=auth_headers)
    assert r.status_code == 200
    data = r.json()
    # Credentials are auto-injected into the stream URL
    assert data["camera_stream_url"] == "rtsp://admin:secret@192.168.1.200:554/live"
    assert data["camera_username"] == "admin"
    assert data["camera_fqdn"] == "cam.marina.local"
    # Password must be masked in response — never returned in plaintext
    assert data["camera_password"] == "***"

    # Verify it persisted
    r2 = client.get("/api/admin/pedestal/1/config", headers=auth_headers)
    assert r2.status_code == 200
    assert r2.json()["camera_stream_url"] == "rtsp://admin:secret@192.168.1.200:554/live"
    assert r2.json()["camera_password"] == "***"


def test_update_camera_url_cleared(client, auth_headers):
    """Camera URL persists across partial updates; non-camera fields don't affect it."""
    # First set URL + credentials (credentials get injected into URL)
    client.put("/api/admin/pedestal/1/config",
               json={"camera_stream_url": "rtsp://192.168.1.200:554/live",
                     "camera_username": "admin", "camera_password": "secret"},
               headers=auth_headers)
    # Then update an unrelated field — camera_stream_url should remain
    r = client.put("/api/admin/pedestal/1/config",
                   json={"site_id": "marina-a"},
                   headers=auth_headers)
    assert r.status_code == 200
    data = r.json()
    assert data["site_id"] == "marina-a"
    # URL still has injected credentials from the prior save
    assert data["camera_stream_url"] == "rtsp://admin:secret@192.168.1.200:554/live"


def test_update_mqtt_settings(client, auth_headers):
    """Operator configures MQTT credentials and Arduino OPTA client ID."""
    payload = {
        "mqtt_username": "iotuser",
        "mqtt_password": "iotpass",
        "opta_client_id": "opta-berth-3",
    }
    r = client.put("/api/admin/pedestal/1/config", json=payload, headers=auth_headers)
    assert r.status_code == 200
    data = r.json()
    assert data["mqtt_username"] == "iotuser"
    assert data["opta_client_id"] == "opta-berth-3"
    # MQTT password must be masked in response
    assert data["mqtt_password"] == "***"


def test_update_temp_sensor_settings(client, auth_headers):
    """Operator configures Papouch TME temperature sensor IP and port."""
    payload = {
        "temp_sensor_ip": "192.168.1.150",
        "temp_sensor_port": 80,
        "temp_sensor_protocol": "http",
    }
    r = client.put("/api/admin/pedestal/1/config", json=payload, headers=auth_headers)
    assert r.status_code == 200
    data = r.json()
    assert data["temp_sensor_ip"] == "192.168.1.150"
    assert data["temp_sensor_port"] == 80
    assert data["temp_sensor_protocol"] == "http"


def test_update_site_identifiers(client, auth_headers):
    """Operator sets marina-specific site/dock/berth identifiers."""
    payload = {
        "site_id": "marina-north",
        "dock_id": "dock-b",
        "berth_ref": "B-07",
        "pedestal_uid": "PED-2024-007",
        "pedestal_model": "Marina Pro 400",
    }
    r = client.put("/api/admin/pedestal/1/config", json=payload, headers=auth_headers)
    assert r.status_code == 200
    data = r.json()
    assert data["site_id"] == "marina-north"
    assert data["berth_ref"] == "B-07"
    assert data["pedestal_model"] == "Marina Pro 400"


def test_update_config_requires_admin(client):
    """PUT config without auth is rejected."""
    r = client.put("/api/admin/pedestal/1/config",
                   json={"camera_stream_url": "rtsp://x"})
    assert r.status_code in (401, 403)


# ─── Sensor CRUD ──────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def sensor_id(client, auth_headers):
    """Create a custom MQTT sensor and return its id."""
    r = client.post("/api/admin/pedestal/1/sensors", json={
        "sensor_name": "voltage_l1",
        "sensor_type": "voltage",
        "mqtt_topic": "pedestal/1/sensors/voltage_l1",
        "unit": "V",
        "min_alarm": 180.0,
        "max_alarm": 250.0,
        "is_active": True,
    }, headers=auth_headers)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_add_sensor(sensor_id):
    """Fixture asserts 200 — sensor id is a positive int."""
    assert isinstance(sensor_id, int)
    assert sensor_id > 0


def test_list_sensors_includes_new(client, auth_headers, sensor_id):
    """GET sensors list includes the newly created sensor."""
    r = client.get("/api/admin/pedestal/1/sensors", headers=auth_headers)
    assert r.status_code == 200
    ids = [s["id"] for s in r.json()]
    assert sensor_id in ids


def test_sensor_fields_correct(client, auth_headers, sensor_id):
    """Sensor is stored with correct type, topic, and alarm thresholds."""
    r = client.get("/api/admin/pedestal/1/sensors", headers=auth_headers)
    sensor = next(s for s in r.json() if s["id"] == sensor_id)
    assert sensor["sensor_name"] == "voltage_l1"
    assert sensor["sensor_type"] == "voltage"
    assert sensor["mqtt_topic"] == "pedestal/1/sensors/voltage_l1"
    assert sensor["unit"] == "V"
    assert sensor["min_alarm"] == 180.0
    assert sensor["max_alarm"] == 250.0
    assert sensor["source"] == "manual"


def test_delete_sensor(client, auth_headers, sensor_id):
    """Deleting a sensor removes it from the list."""
    r = client.delete(f"/api/admin/pedestal/sensors/{sensor_id}",
                      headers=auth_headers)
    assert r.status_code == 200

    r2 = client.get("/api/admin/pedestal/1/sensors", headers=auth_headers)
    ids = [s["id"] for s in r2.json()]
    assert sensor_id not in ids


def test_delete_sensor_not_found(client, auth_headers):
    """Deleting a non-existent sensor returns 404."""
    r = client.delete("/api/admin/pedestal/sensors/99999", headers=auth_headers)
    assert r.status_code == 404


def test_sensor_requires_admin(client):
    """Sensor list requires admin auth."""
    r = client.get("/api/admin/pedestal/1/sensors")
    assert r.status_code in (401, 403)


# ─── Feature toggles ──────────────────────────────────────────────────────────

def test_toggle_mobile_enabled_on(client, auth_headers):
    """mobile_enabled can be turned on."""
    r = client.patch("/api/pedestals/1", json={"mobile_enabled": True},
                     headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["mobile_enabled"] is True


def test_toggle_mobile_enabled_off(client, auth_headers):
    """mobile_enabled can be turned off."""
    r = client.patch("/api/pedestals/1", json={"mobile_enabled": False},
                     headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["mobile_enabled"] is False


def test_mobile_disabled_hides_from_customer(client, auth_headers, cust_headers):
    """When mobile_enabled=False the pedestal is invisible in the customer app."""
    # Disable mobile for pedestal 1
    client.patch("/api/pedestals/1", json={"mobile_enabled": False},
                 headers=auth_headers)

    r = client.get("/api/customer/sessions/pedestal-status", headers=cust_headers)
    assert r.status_code == 200
    ids = [p["id"] for p in r.json()]
    assert 1 not in ids

    # Re-enable so other tests still have a pedestal
    client.patch("/api/pedestals/1", json={"mobile_enabled": True},
                 headers=auth_headers)


def test_toggle_ai_enabled_on(client, auth_headers):
    """ai_enabled can be toggled on."""
    r = client.patch("/api/pedestals/1", json={"ai_enabled": True},
                     headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["ai_enabled"] is True


def test_toggle_ai_enabled_off(client, auth_headers):
    """ai_enabled can be toggled off."""
    r = client.patch("/api/pedestals/1", json={"ai_enabled": False},
                     headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["ai_enabled"] is False


# ─── Health endpoint ──────────────────────────────────────────────────────────

def test_health_requires_admin(client):
    """/api/pedestals/health requires authentication (returns 401 or 403)."""
    r = client.get("/api/pedestals/health")
    assert r.status_code in (401, 403)


def test_health_endpoint_admin(client, auth_headers):
    """/api/pedestals/health is accessible with admin auth."""
    r = client.get("/api/pedestals/health", headers=auth_headers)
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, dict)


def test_health_contains_expected_fields(client, auth_headers):
    """Health response has all required monitoring fields."""
    r = client.get("/api/pedestals/health", headers=auth_headers)
    assert r.status_code == 200
    for _pid, health in r.json().items():
        assert "opta_connected" in health
        assert "camera_reachable" in health
        assert "temp_sensor_reachable" in health
