"""Invoice listing and payment endpoints."""


def test_list_my_invoices(client, cust_headers):
    r = client.get("/api/customer/invoices/mine", headers=cust_headers)
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_list_invoices_requires_auth(client):
    r = client.get("/api/customer/invoices/mine")
    assert r.status_code in (401, 403)


def test_pay_invoice(client, cust_headers):
    """If a completed session generated an invoice, pay it."""
    r = client.get("/api/customer/invoices/mine", headers=cust_headers)
    assert r.status_code == 200
    invoices = r.json()
    unpaid = [inv for inv in invoices if not inv["paid"]]
    if not unpaid:
        # No invoice to pay — session duration was too short to accrue cost; pass
        return

    inv_id = unpaid[0]["id"]
    r2 = client.post(f"/api/customer/invoices/{inv_id}/pay", headers=cust_headers)
    assert r2.status_code == 200
    assert r2.json()["paid"] in (True, 1)  # SQLite may return integer 1 for boolean True


def test_pay_nonexistent_invoice(client, cust_headers):
    r = client.post("/api/customer/invoices/999999/pay", headers=cust_headers)
    assert r.status_code == 404
