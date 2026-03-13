"""Customer registration, login, profile endpoints."""
import pytest


CUSTOMER_EMAIL = "authtest@example.com"
CUSTOMER_PASS  = "securepass123"


@pytest.fixture(scope="module")
def registered_token(client):
    """Register once, return token for the module."""
    client.post("/api/customer/auth/register", json={
        "email": CUSTOMER_EMAIL,
        "password": CUSTOMER_PASS,
        "name": "Auth Test User",
        "ship_name": "Sea Breeze",
    })
    r = client.post("/api/customer/auth/login", json={
        "email": CUSTOMER_EMAIL,
        "password": CUSTOMER_PASS,
    })
    assert r.status_code == 200
    return r.json()["access_token"]


def test_register_success(client):
    r = client.post("/api/customer/auth/register", json={
        "email": "newuser_unique@example.com",
        "password": "password123",
        "name": "New User",
    })
    assert r.status_code == 200
    assert "access_token" in r.json()


def test_register_duplicate_email(client):
    payload = {
        "email": "duplicate@example.com",
        "password": "pass1234",
    }
    client.post("/api/customer/auth/register", json=payload)
    r = client.post("/api/customer/auth/register", json=payload)
    assert r.status_code == 400


def test_register_invalid_email(client):
    r = client.post("/api/customer/auth/register", json={
        "email": "not-an-email",
        "password": "pass1234",
    })
    assert r.status_code == 422


def test_register_short_password(client):
    r = client.post("/api/customer/auth/register", json={
        "email": "shortpass@example.com",
        "password": "abc",
    })
    assert r.status_code == 422


def test_login_success(client, registered_token):
    assert registered_token  # already tested in fixture


def test_login_wrong_password(client):
    client.post("/api/customer/auth/register", json={
        "email": "wrongpass@example.com",
        "password": "correct123",
    })
    r = client.post("/api/customer/auth/login", json={
        "email": "wrongpass@example.com",
        "password": "wrongpassword",
    })
    assert r.status_code == 401


def test_login_nonexistent_user(client):
    r = client.post("/api/customer/auth/login", json={
        "email": "nobody@example.com",
        "password": "pass1234",
    })
    assert r.status_code == 401


def test_get_me(client, registered_token):
    r = client.get("/api/customer/auth/me", headers={"Authorization": f"Bearer {registered_token}"})
    assert r.status_code == 200
    data = r.json()
    assert data["email"] == CUSTOMER_EMAIL
    assert data["ship_name"] == "Sea Breeze"


def test_get_me_no_token(client):
    r = client.get("/api/customer/auth/me")
    assert r.status_code in (401, 403)


def test_update_profile(client, registered_token):
    r = client.patch(
        "/api/customer/auth/profile",
        json={"name": "Updated Name", "ship_name": "Updated Vessel"},
        headers={"Authorization": f"Bearer {registered_token}"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["name"] == "Updated Name"
    assert data["ship_name"] == "Updated Vessel"
