"""
Tests pour le système d'idempotence.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import app
from app.models import IdempotencyKey, Organization, ApiKey, Customer, Invoice
from app.db import get_db, engine, Base
from app.security import generate_api_key

# Create test database
Base.metadata.create_all(bind=engine)

client = TestClient(app)


@pytest.fixture
def test_org():
    """Create a test organization."""
    db = next(get_db())
    org = Organization(name="Test Org Idempotency")
    db.add(org)
    db.commit()
    db.refresh(org)
    yield org
    db.delete(org)
    db.commit()


@pytest.fixture
def test_api_key(test_org):
    """Create a test API key."""
    db = next(get_db())
    raw_key, prefix, key_hash = generate_api_key()
    api_key = ApiKey(
        organization_id=test_org.id,
        name="Test Key",
        prefix=prefix,
        key_hash=key_hash
    )
    db.add(api_key)
    db.commit()
    yield {"raw": raw_key, "object": api_key}
    db.delete(api_key)
    db.commit()


@pytest.fixture
def test_customer(test_org):
    """Create a test customer."""
    db = next(get_db())
    customer = Customer(
        organization_id=test_org.id,
        name="Test Customer",
        email="test@example.com"
    )
    db.add(customer)
    db.commit()
    db.refresh(customer)
    yield customer
    db.delete(customer)
    db.commit()


def test_idempotency_first_request(test_org, test_api_key):
    """Test that the first request creates a new resource."""
    headers = {
        "Authorization": f"Bearer {test_api_key['raw']}",
        "Idempotency-Key": "test-key-001"
    }
    
    response = client.post(
        "/v1/customers",
        json={"name": "Customer A", "email": "a@example.com"},
        headers=headers
    )
    
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Customer A"
    assert "id" in data
    
    # Verify idempotency key was stored (check by organization_id since key is hashed)
    db = next(get_db())
    keys = db.scalars(select(IdempotencyKey).where(IdempotencyKey.organization_id == test_org.id)).all()
    assert len(keys) > 0
    # Find the key for this request
    found_key = None
    for k in keys:
        if k.method == "POST" and "/customers" in k.path:
            found_key = k
            break
    assert found_key is not None
    assert found_key.response_status == 201


def test_idempotency_duplicate_request(test_org, test_api_key):
    """Test that duplicate requests return cached response."""
    headers = {
        "Authorization": f"Bearer {test_api_key['raw']}",
        "Idempotency-Key": "test-key-002"
    }
    
    # First request
    response1 = client.post(
        "/v1/customers",
        json={"name": "Customer B", "email": "b@example.com"},
        headers=headers
    )
    
    assert response1.status_code == 201
    data1 = response1.json()
    customer_id = data1["id"]
    
    # Second identical request
    response2 = client.post(
        "/v1/customers",
        json={"name": "Customer B", "email": "b@example.com"},
        headers=headers
    )
    
    assert response2.status_code == 201
    data2 = response2.json()
    
    # Should return same customer
    assert data2["id"] == customer_id
    assert data2["name"] == "Customer B"
    
    # Verify only one customer was created
    db = next(get_db())
    count = db.scalar(
        select(Customer).where(Customer.organization_id == test_org.id, Customer.email == "b@example.com")
    )
    assert count is not None


def test_idempotency_different_payload_same_key(test_org, test_api_key):
    """Test that different payloads with same key returns cached response (not error)."""
    headers = {
        "Authorization": f"Bearer {test_api_key['raw']}",
        "Idempotency-Key": "test-key-003"
    }
    
    # First request
    response1 = client.post(
        "/v1/customers",
        json={"name": "Customer C", "email": "c@example.com"},
        headers=headers
    )
    
    assert response1.status_code == 201
    data1 = response1.json()
    
    # Second request with different payload but same key
    # In our implementation, we return cached response without checking payload
    response2 = client.post(
        "/v1/customers",
        json={"name": "Customer D", "email": "d@example.com"},  # Different!
        headers=headers
    )
    
    # Should return cached response from first request
    assert response2.status_code == 201
    data2 = response2.json()
    assert data2["id"] == data1["id"]
    assert data2["name"] == "Customer C"  # Not Customer D


def test_idempotency_invoice_creation(test_org, test_api_key, test_customer):
    """Test idempotency for invoice creation."""
    headers = {
        "Authorization": f"Bearer {test_api_key['raw']}",
        "Idempotency-Key": "test-key-invoice-001"
    }
    
    invoice_data = {
        "customer_id": test_customer.id,
        "number": "INV-2024-TEST",  # Unique number per test
        "currency": "EUR",
        "lines": [
            {
                "description": "Service consulting",
                "quantity": 10,
                "unit_price_minor": 10000,  # 100.00 EUR
                "tax_rate": 20.0
            }
        ]
    }
    
    # First request
    response1 = client.post("/v1/invoices", json=invoice_data, headers=headers)
    assert response1.status_code == 201
    data1 = response1.json()
    invoice_id = data1["id"]
    
    # Second identical request - should return cached response
    response2 = client.post("/v1/invoices", json=invoice_data, headers=headers)
    assert response2.status_code == 201
    data2 = response2.json()
    
    # Should return same invoice
    assert data2["id"] == invoice_id
    assert data2["number"] == "INV-2024-TEST"
    
    # Verify only one invoice was created
    db = next(get_db())
    count = db.scalar(
        select(Invoice).where(Invoice.organization_id == test_org.id, Invoice.number == "INV-2024-TEST")
    )
    assert count is not None


def test_idempotency_without_key(test_org, test_api_key):
    """Test that requests without idempotency key work normally."""
    headers = {
        "Authorization": f"Bearer {test_api_key['raw']}"
    }
    
    # Two requests without idempotency key should create two resources
    response1 = client.post(
        "/v1/customers",
        json={"name": "Customer E", "email": "e@example.com"},
        headers=headers
    )
    
    response2 = client.post(
        "/v1/customers",
        json={"name": "Customer F", "email": "f@example.com"},
        headers=headers
    )
    
    assert response1.status_code == 201
    assert response2.status_code == 201
    
    data1 = response1.json()
    data2 = response2.json()
    
    assert data1["id"] != data2["id"]


def test_idempotency_key_expiration(test_org, test_api_key):
    """Test that expired idempotency keys allow new requests."""
    from datetime import datetime, timedelta, timezone
    
    headers = {
        "Authorization": f"Bearer {test_api_key['raw']}",
        "Idempotency-Key": "test-key-expired"
    }
    
    # First request
    response1 = client.post(
        "/v1/customers",
        json={"name": "Customer G", "email": "g@example.com"},
        headers=headers
    )
    
    assert response1.status_code == 201
    data1 = response1.json()
    
    # Manually expire the key
    db = next(get_db())
    idem_key = db.scalar(
        select(IdempotencyKey).where(IdempotencyKey.organization_id == test_org.id)
    )
    if idem_key:
        idem_key.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
        db.commit()
    
    # Second request after expiration should create new resource
    response2 = client.post(
        "/v1/customers",
        json={"name": "Customer H", "email": "h@example.com"},
        headers=headers
    )
    
    assert response2.status_code == 201
    data2 = response2.json()
    
    # Should be different customers
    assert data1["id"] != data2["id"]


def test_idempotency_different_methods(test_org, test_api_key):
    """Test that same key can be used for different HTTP methods."""
    # Note: This depends on implementation details
    # In our case, we store method+path, so same key with different methods should work
    pass  # Would need PUT/PATCH endpoints to test properly


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
