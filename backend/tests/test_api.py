from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_create_organization_and_api_key() -> None:
    organization = client.post("/v1/organizations", json={"name": "Acme"})
    assert organization.status_code == 201
    organization_id = organization.json()["id"]

    api_key = client.post(f"/v1/organizations/{organization_id}/api-keys", json={"name": "local"})
    assert api_key.status_code == 201
    assert api_key.json()["key"].startswith("sk_live_")

    headers = {"Authorization": f"Bearer {api_key.json()['key']}"}
    customer = client.post("/v1/customers", headers=headers, json={"name": "Client A"})
    assert customer.status_code == 201

    invoice = client.post(
        "/v1/invoices",
        headers=headers,
        json={
            "customer_id": customer.json()["id"],
            "number": "INV-001",
            "currency": "EUR",
            "notes": "Test invoice",
            "lines": [
                {
                    "description": "Service development",
                    "quantity": 1.0,
                    "unit_price_minor": 10000,
                    "tax_rate": 20.0
                }
            ]
        },
    )
    assert invoice.status_code == 201
    assert invoice.json()["status"] == "draft"
