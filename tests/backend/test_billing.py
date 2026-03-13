"""Billing config and spending endpoints (admin)."""


def test_get_billing_config(client, auth_headers):
    r = client.get("/api/billing/config", headers=auth_headers)
    assert r.status_code == 200
    data = r.json()
    assert "kwh_price_eur" in data
    assert "liter_price_eur" in data


def test_update_billing_config(client, auth_headers):
    r = client.put("/api/billing/config", json={
        "kwh_price_eur": 0.35,
        "liter_price_eur": 0.02,
    }, headers=auth_headers)
    assert r.status_code == 200
    data = r.json()
    assert data["kwh_price_eur"] == 0.35
    assert data["liter_price_eur"] == 0.02


def test_billing_config_requires_auth(client):
    """Billing config requires an authenticated operator — no token returns 403."""
    r = client.get("/api/billing/config")
    assert r.status_code in (401, 403)


def test_billing_config_no_token(client):
    r = client.get("/api/billing/config")
    assert r.status_code in (401, 403)


def test_get_spending(client, auth_headers):
    r = client.get("/api/billing/spending", headers=auth_headers)
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_get_spending_detail(client, auth_headers):
    r = client.get("/api/billing/spending/detail", headers=auth_headers)
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_get_customers(client, auth_headers):
    r = client.get("/api/billing/customers", headers=auth_headers)
    assert r.status_code == 200
    assert isinstance(r.json(), list)
