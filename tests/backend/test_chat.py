"""Customer ↔ operator chat endpoints."""
import pytest


@pytest.fixture(scope="module")
def customer_id(client, cust_headers):
    r = client.get("/api/customer/auth/me", headers=cust_headers)
    assert r.status_code == 200
    return r.json()["id"]


def test_customer_send_message(client, cust_headers):
    r = client.post("/api/chat/send", json={"message": "Hello, I need help."},
                    headers=cust_headers)
    assert r.status_code == 200
    data = r.json()
    assert data["message"] == "Hello, I need help."
    assert data["direction"] == "from_customer"


def test_customer_send_empty_message(client, cust_headers):
    r = client.post("/api/chat/send", json={"message": ""},
                    headers=cust_headers)
    assert r.status_code in (400, 422)


def test_customer_list_messages(client, auth_headers, customer_id):
    # /api/chat/messages/{id} is an admin endpoint — must use admin JWT
    # (was previously using cust_headers due to ID-collision security bug)
    r = client.get(f"/api/chat/messages/{customer_id}", headers=auth_headers)
    assert r.status_code == 200
    messages = r.json()
    assert isinstance(messages, list)
    assert any(m["direction"] == "from_customer" for m in messages)


def test_customer_unread_count(client, auth_headers):
    # /api/chat/unread-count is an admin endpoint — must use admin JWT
    r = client.get("/api/chat/unread-count", headers=auth_headers)
    assert r.status_code == 200
    assert "unread_customers" in r.json()


def test_customer_cannot_access_admin_chat_endpoints(client, cust_headers, customer_id):
    # Customer JWT must be rejected by admin-only chat endpoints (403)
    r = client.get(f"/api/chat/messages/{customer_id}", headers=cust_headers)
    assert r.status_code == 403, (
        f"Expected 403 (customer JWT should not access admin chat), got {r.status_code}"
    )
    r2 = client.get("/api/chat/unread-count", headers=cust_headers)
    assert r2.status_code == 403, (
        f"Expected 403 (customer JWT should not access admin unread-count), got {r2.status_code}"
    )


def test_operator_reply(client, auth_headers, customer_id):
    r = client.post(
        f"/api/chat/operator/reply/{customer_id}",
        json={"message": "We're on our way!"},
        headers=auth_headers,
    )
    assert r.status_code == 200
    data = r.json()
    assert data["direction"] == "from_operator"


def test_admin_list_messages(client, auth_headers, customer_id):
    r = client.get(f"/api/chat/messages/{customer_id}", headers=auth_headers)
    assert r.status_code == 200
    messages = r.json()
    assert any(m["direction"] == "from_operator" for m in messages)


def test_chat_requires_auth(client):
    r = client.get("/api/chat/unread-count")
    assert r.status_code == 403
