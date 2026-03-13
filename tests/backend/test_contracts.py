"""Contract templates (admin CRUD) and customer contract signing."""
import pytest


@pytest.fixture(scope="module")
def template_id(client, auth_headers):
    """Create a template and return its id."""
    r = client.post("/api/contracts/templates", json={
        "title": "Test Contract",
        "body": "You agree to the terms.",
        "validity_days": 30,
        "active": True,
        "notify_on_register": False,
    }, headers=auth_headers)
    assert r.status_code == 200
    return r.json()["id"]


def test_list_templates(client, auth_headers):
    r = client.get("/api/contracts/templates", headers=auth_headers)
    assert r.status_code == 200
    assert isinstance(r.json(), list)
    assert len(r.json()) >= 1


def test_create_template(template_id):
    assert isinstance(template_id, int)
    assert template_id > 0


def test_update_template(client, auth_headers, template_id):
    r = client.patch(f"/api/contracts/templates/{template_id}", json={
        "title": "Updated Test Contract",
        "validity_days": 60,
    }, headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["title"] == "Updated Test Contract"


def test_templates_require_auth(client):
    r = client.get("/api/contracts/templates")
    assert r.status_code == 403


def test_customer_pending_contracts(client, cust_headers):
    r = client.get("/api/customer/contracts/pending", headers=cust_headers)
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_customer_my_contracts(client, cust_headers):
    r = client.get("/api/customer/contracts/mine", headers=cust_headers)
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_customer_sign_contract(client, cust_headers):
    # Get first pending contract
    r = client.get("/api/customer/contracts/pending", headers=cust_headers)
    assert r.status_code == 200
    pending = r.json()
    if not pending:
        pytest.skip("No pending contracts for customer")

    template_id = pending[0]["id"]
    # Sign with a minimal base64 PNG stub
    fake_sig = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
    r2 = client.post(
        f"/api/customer/contracts/{template_id}/sign",
        json={"signature_data": fake_sig},
        headers=cust_headers,
    )
    assert r2.status_code == 200


def test_admin_list_contracts(client, auth_headers):
    r = client.get("/api/admin/contracts", headers=auth_headers)
    assert r.status_code == 200
    assert isinstance(r.json(), list)
