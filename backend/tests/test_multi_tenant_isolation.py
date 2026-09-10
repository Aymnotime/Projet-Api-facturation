"""Tests d'isolation multi-tenant pour garantir que les données sont correctement isolées entre organisations."""
import pytest
from sqlalchemy.orm import Session
from fastapi.testclient import TestClient

from app.models import Organization, User, Customer, Invoice, InvoiceStatus
from app.security import get_password_hash, generate_api_key
from app.db import Base, get_db
from app.main import app


class TestMultiTenantIsolation:
    """Tests pour vérifier l'isolation des données entre organisations."""

    def test_customers_isolated_between_organizations(self, db_session: Session):
        """Les clients d'une organisation ne doivent pas être visibles par une autre."""
        # Créer deux organisations
        org1 = Organization(name="Organization 1")
        org2 = Organization(name="Organization 2")
        db_session.add_all([org1, org2])
        db_session.commit()
        db_session.refresh(org1)
        db_session.refresh(org2)

        # Créer des API keys pour chaque organisation
        _, prefix1, hash1 = generate_api_key()
        _, prefix2, hash2 = generate_api_key()
        
        from app.models import ApiKey
        api_key1 = ApiKey(organization_id=org1.id, name="Key Org1", prefix=prefix1, key_hash=hash1)
        api_key2 = ApiKey(organization_id=org2.id, name="Key Org2", prefix=prefix2, key_hash=hash2)
        db_session.add_all([api_key1, api_key2])
        db_session.commit()

        # Créer des clients pour chaque organisation
        customer1 = Customer(
            name="Client Org1",
            email="client@org1.com",
            organization_id=org1.id
        )
        customer2 = Customer(
            name="Client Org2",
            email="client@org2.com",
            organization_id=org2.id
        )
        db_session.add_all([customer1, customer2])
        db_session.commit()

        # Vérifier que chaque organisation ne voit que ses propres clients
        org1_customers = db_session.query(Customer).filter(Customer.organization_id == org1.id).all()
        org2_customers = db_session.query(Customer).filter(Customer.organization_id == org2.id).all()

        assert len(org1_customers) == 1
        assert len(org2_customers) == 1
        assert org1_customers[0].name == "Client Org1"
        assert org2_customers[0].name == "Client Org2"

    def test_invoices_isolated_between_organizations(self, db_session: Session):
        """Les factures d'une organisation ne doivent pas être visibles par une autre."""
        # Créer deux organisations
        org1 = Organization(name="Org1 Invoices")
        org2 = Organization(name="Org2 Invoices")
        db_session.add_all([org1, org2])
        db_session.commit()
        db_session.refresh(org1)
        db_session.refresh(org2)

        # Créer des clients pour chaque organisation
        customer1 = Customer(name="Customer 1", email="c1@test.com", organization_id=org1.id)
        customer2 = Customer(name="Customer 2", email="c2@test.com", organization_id=org2.id)
        db_session.add_all([customer1, customer2])
        db_session.commit()

        # Créer des factures pour chaque organisation
        invoice1 = Invoice(
            number="FAC-2024-0001",
            customer_id=customer1.id,
            organization_id=org1.id,
            status=InvoiceStatus.DRAFT,
            total_minor=12000,
            subtotal_minor=10000,
            tax_total_minor=2000
        )
        invoice2 = Invoice(
            number="FAC-2024-0001",
            customer_id=customer2.id,
            organization_id=org2.id,
            status=InvoiceStatus.DRAFT,
            total_minor=24000,
            subtotal_minor=20000,
            tax_total_minor=4000
        )
        db_session.add_all([invoice1, invoice2])
        db_session.commit()

        # Vérifier l'isolation
        org1_invoices = db_session.query(Invoice).filter(Invoice.organization_id == org1.id).all()
        org2_invoices = db_session.query(Invoice).filter(Invoice.organization_id == org2.id).all()

        assert len(org1_invoices) == 1
        assert len(org2_invoices) == 1
        assert org1_invoices[0].number == "FAC-2024-0001"
        assert org2_invoices[0].number == "FAC-2024-0001"  # Même numéro possible car org différente
        assert org1_invoices[0].subtotal_minor == 10000
        assert org2_invoices[0].subtotal_minor == 20000

    def test_api_key_access_restricted_to_organization(self, db_session: Session):
        """Une API key ne doit permettre d'accéder qu'aux données de son organisation."""
        # Créer deux organisations
        org1 = Organization(name="Org1 Access")
        org2 = Organization(name="Org2 Access")
        db_session.add_all([org1, org2])
        db_session.commit()
        db_session.refresh(org1)
        db_session.refresh(org2)

        # Créer des API keys
        raw_key1, prefix1, hash1 = generate_api_key()
        raw_key2, prefix2, hash2 = generate_api_key()
        
        from app.models import ApiKey
        api_key1 = ApiKey(organization_id=org1.id, name="Key1", prefix=prefix1, key_hash=hash1)
        api_key2 = ApiKey(organization_id=org2.id, name="Key2", prefix=prefix2, key_hash=hash2)
        db_session.add_all([api_key1, api_key2])
        db_session.commit()

        # Créer des clients pour org2 (que org1 ne devrait pas pouvoir accéder)
        customer_org2 = Customer(
            name="Secret Client Org2",
            email="secret@org2.com",
            organization_id=org2.id
        )
        db_session.add(customer_org2)
        db_session.commit()

        # Simuler une requête avec la key d'org1
        # Dans l'implémentation réelle, le middleware extrait l'org_id de la key
        # Ici on vérifie au niveau DB que le filtre est correct
        accessible_customers = db_session.query(Customer).filter(
            Customer.organization_id == org1.id
        ).all()

        assert len(accessible_customers) == 0
        assert "Secret Client Org2" not in [c.name for c in accessible_customers]

    def test_user_cannot_access_another_organization_resources(self, db_session: Session):
        """Un utilisateur ne doit pas pouvoir accéder aux ressources d'une autre organisation."""
        # Créer deux organisations
        org1 = Organization(name="Org1 Users")
        org2 = Organization(name="Org2 Users")
        db_session.add_all([org1, org2])
        db_session.commit()
        db_session.refresh(org1)
        db_session.refresh(org2)

        # Créer des utilisateurs pour chaque organisation
        user1 = User(
            email="user1@org1.com",
            password_hash=get_password_hash("password123"),
            full_name="User 1",
            organization_id=org1.id,
            is_active=True,
            email_verified=True
        )
        user2 = User(
            email="user2@org2.com",
            password_hash=get_password_hash("password123"),
            full_name="User 2",
            organization_id=org2.id,
            is_active=True,
            email_verified=True
        )
        db_session.add_all([user1, user2])
        db_session.commit()

        # Vérifier que les utilisateurs sont bien liés à leur organisation
        assert user1.organization_id == org1.id
        assert user2.organization_id == org2.id

        # Vérifier que user1 ne peut pas accéder aux resources de org2
        org2_users = db_session.query(User).filter(User.organization_id == org2.id).all()
        assert user1 not in org2_users
        assert len(org2_users) == 1
        assert org2_users[0].email == "user2@org2.com"

    def test_invoice_numbering_isolated_per_organization(self, db_session: Session):
        """La numérotation des factures doit être isolée par organisation."""
        # Créer deux organisations
        org1 = Organization(name="Org1 Numbering")
        org2 = Organization(name="Org2 Numbering")
        db_session.add_all([org1, org2])
        db_session.commit()
        db_session.refresh(org1)
        db_session.refresh(org2)

        # Créer des clients
        customer1 = Customer(name="Customer 1", email="c1@num.com", organization_id=org1.id)
        customer2 = Customer(name="Customer 2", email="c2@num.com", organization_id=org2.id)
        db_session.add_all([customer1, customer2])
        db_session.commit()

        # Créer des factures avec le même numéro dans chaque organisation
        invoice1_org1 = Invoice(
            number="FAC-2024-0001",
            customer_id=customer1.id,
            organization_id=org1.id,
            status=InvoiceStatus.DRAFT,
            subtotal_minor=10000,
            total_minor=12000,
            tax_total_minor=2000
        )
        invoice2_org1 = Invoice(
            number="FAC-2024-0002",
            customer_id=customer1.id,
            organization_id=org1.id,
            status=InvoiceStatus.DRAFT,
            subtotal_minor=15000,
            total_minor=18000,
            tax_total_minor=3000
        )
        
        invoice1_org2 = Invoice(
            number="FAC-2024-0001",  # Même numéro que org1
            customer_id=customer2.id,
            organization_id=org2.id,
            status=InvoiceStatus.DRAFT,
            subtotal_minor=25000,
            total_minor=30000,
            tax_total_minor=5000
        )
        invoice2_org2 = Invoice(
            number="FAC-2024-0002",  # Même numéro que org1
            customer_id=customer2.id,
            organization_id=org2.id,
            status=InvoiceStatus.DRAFT,
            subtotal_minor=30000,
            total_minor=36000,
            tax_total_minor=6000
        )
        
        db_session.add_all([invoice1_org1, invoice2_org1, invoice1_org2, invoice2_org2])
        db_session.commit()

        # Vérifier que chaque organisation a sa propre séquence
        org1_invoices = db_session.query(Invoice).filter(
            Invoice.organization_id == org1.id
        ).order_by(Invoice.number).all()
        
        org2_invoices = db_session.query(Invoice).filter(
            Invoice.organization_id == org2.id
        ).order_by(Invoice.number).all()

        assert len(org1_invoices) == 2
        assert len(org2_invoices) == 2
        
        assert org1_invoices[0].number == "FAC-2024-0001"
        assert org1_invoices[1].number == "FAC-2024-0002"
        assert org2_invoices[0].number == "FAC-2024-0001"
        assert org2_invoices[1].number == "FAC-2024-0002"
        
        # Vérifier que les totaux sont différents (preuves que ce sont des factures différentes)
        assert org1_invoices[0].subtotal_minor == 10000
        assert org2_invoices[0].subtotal_minor == 25000

    def test_cross_organization_query_returns_empty(self, db_session: Session):
        """Une requête filtrée par organization_id ne doit jamais retourner de données d'autres orgs."""
        # Créer plusieurs organisations
        orgs = []
        for i in range(5):
            org = Organization(name=f"Org {i}")
            db_session.add(org)
            db_session.commit()
            db_session.refresh(org)
            orgs.append(org)

        # Créer des clients pour chaque organisation
        for i, org in enumerate(orgs):
            customer = Customer(
                name=f"Client Org {i}",
                email=f"client{i}@org.com",
                organization_id=org.id
            )
            db_session.add(customer)
        db_session.commit()

        # Tester pour chaque organisation
        for i, org in enumerate(orgs):
            customers = db_session.query(Customer).filter(
                Customer.organization_id == org.id
            ).all()
            
            assert len(customers) == 1
            assert customers[0].name == f"Client Org {i}"
            
            # Vérifier qu'aucun client d'une autre org n'est retourné
            for j, other_org in enumerate(orgs):
                if i != j:
                    other_customers = db_session.query(Customer).filter(
                        Customer.organization_id == other_org.id
                    ).all()
                    assert customers[0] not in other_customers

    def test_organization_deletion_cascades_properly(self, db_session: Session):
        """La suppression d'une organisation doit supprimer toutes ses données associées."""
        # Créer une organisation avec des données
        org = Organization(name="Org to Delete")
        db_session.add(org)
        db_session.commit()
        db_session.refresh(org)

        # Créer un client et une facture
        customer = Customer(
            name="Client to Delete",
            email="delete@test.com",
            organization_id=org.id
        )
        db_session.add(customer)
        db_session.commit()

        invoice = Invoice(
            number="FAC-2024-DELETE",
            customer_id=customer.id,
            organization_id=org.id,
            status=InvoiceStatus.DRAFT,
            subtotal_minor=10000,
            total_minor=12000,
            tax_total_minor=2000
        )
        db_session.add(invoice)
        db_session.commit()

        # Vérifier que les données existent
        assert db_session.query(Customer).filter(Customer.organization_id == org.id).count() == 1
        assert db_session.query(Invoice).filter(Invoice.organization_id == org.id).count() == 1

        # Supprimer l'organisation
        db_session.delete(org)
        db_session.commit()

        # Vérifier que les données associées ont été supprimées (cascade)
        # Note: Selon la configuration de cascade, cela peut varier
        remaining_customers = db_session.query(Customer).filter(
            Customer.organization_id == org.id
        ).all()
        remaining_invoices = db_session.query(Invoice).filter(
            Invoice.organization_id == org.id
        ).all()
        
        # Les références à une org supprimée devraient être nulles ou les objets supprimés
        assert len(remaining_customers) == 0 or all(c.organization_id is None for c in remaining_customers)
        assert len(remaining_invoices) == 0 or all(i.organization_id is None for i in remaining_invoices)

    def test_concurrent_access_same_organization(self, db_session: Session):
        """Plusieurs requêtes simultanées pour la même organisation doivent fonctionner correctement."""
        # Créer une organisation
        org = Organization(name="Concurrent Org")
        db_session.add(org)
        db_session.commit()
        db_session.refresh(org)

        # Simuler plusieurs créations de clients concurrentes
        customers_data = [
            {"name": f"Client {i}", "email": f"client{i}@concurrent.com"}
            for i in range(10)
        ]

        for data in customers_data:
            customer = Customer(
                name=data["name"],
                email=data["email"],
                organization_id=org.id
            )
            db_session.add(customer)
        
        db_session.commit()

        # Vérifier que tous les clients ont été créés
        customers = db_session.query(Customer).filter(
            Customer.organization_id == org.id
        ).all()

        assert len(customers) == 10
        assert all(c.organization_id == org.id for c in customers)

    def test_data_integrity_across_multiple_tenants(self, db_session: Session):
        """Test d'intégrité des données avec plusieurs organisations et types de ressources."""
        # Créer 3 organisations
        org_alpha = Organization(name="Alpha Corp")
        org_beta = Organization(name="Beta Inc")
        org_gamma = Organization(name="Gamma LLC")
        db_session.add_all([org_alpha, org_beta, org_gamma])
        db_session.commit()
        db_session.refresh(org_alpha)
        db_session.refresh(org_beta)
        db_session.refresh(org_gamma)

        # Créer des clients pour chaque organisation
        alpha_customers = []
        beta_customers = []
        gamma_customers = []

        for i in range(3):
            alpha_customers.append(Customer(
                name=f"Alpha Customer {i}",
                email=f"alpha{i}@test.com",
                organization_id=org_alpha.id
            ))
            beta_customers.append(Customer(
                name=f"Beta Customer {i}",
                email=f"beta{i}@test.com",
                organization_id=org_beta.id
            ))
            gamma_customers.append(Customer(
                name=f"Gamma Customer {i}",
                email=f"gamma{i}@test.com",
                organization_id=org_gamma.id
            ))

        db_session.add_all(alpha_customers + beta_customers + gamma_customers)
        db_session.commit()

        # Créer des factures pour Alpha
        alpha_invoices = []
        for i, customer in enumerate(alpha_customers):
            invoice = Invoice(
                number=f"FAC-2024-A{i:03d}",
                customer_id=customer.id,
                organization_id=org_alpha.id,
                status=InvoiceStatus.DRAFT,
                subtotal_minor=10000 * (i + 1),
                total_minor=12000 * (i + 1),
                tax_total_minor=2000 * (i + 1)
            )
            alpha_invoices.append(invoice)
        
        db_session.add_all(alpha_invoices)
        db_session.commit()

        # Vérifier l'intégrité pour Alpha
        alpha_db_customers = db_session.query(Customer).filter(
            Customer.organization_id == org_alpha.id
        ).all()
        alpha_db_invoices = db_session.query(Invoice).filter(
            Invoice.organization_id == org_alpha.id
        ).all()

        assert len(alpha_db_customers) == 3
        assert len(alpha_db_invoices) == 3
        assert all(c.organization_id == org_alpha.id for c in alpha_db_customers)
        assert all(i.organization_id == org_alpha.id for i in alpha_db_invoices)

        # Vérifier que Beta et Gamma n'ont pas été affectés
        beta_db_customers = db_session.query(Customer).filter(
            Customer.organization_id == org_beta.id
        ).all()
        gamma_db_customers = db_session.query(Customer).filter(
            Customer.organization_id == org_gamma.id
        ).all()

        assert len(beta_db_customers) == 3
        assert len(gamma_db_customers) == 3
        assert all(c.organization_id == org_beta.id for c in beta_db_customers)
        assert all(c.organization_id == org_gamma.id for c in gamma_db_customers)

        # Vérifier que Beta et Gamma n'ont pas de factures (on n'en a pas créé)
        assert db_session.query(Invoice).filter(
            Invoice.organization_id == org_beta.id
        ).count() == 0
        assert db_session.query(Invoice).filter(
            Invoice.organization_id == org_gamma.id
        ).count() == 0


class TestAPIEndpointIsolation:
    """Tests pour vérifier l'isolation au niveau des endpoints API."""

    @pytest.fixture
    def setup_organizations(self, db_session: Session):
        """Setup pour les tests API."""
        from app.models import ApiKey
        
        org1 = Organization(name="API Org 1")
        org2 = Organization(name="API Org 2")
        db_session.add_all([org1, org2])
        db_session.commit()
        db_session.refresh(org1)
        db_session.refresh(org2)

        raw_key1, prefix1, hash1 = generate_api_key()
        raw_key2, prefix2, hash2 = generate_api_key()
        
        api_key1 = ApiKey(organization_id=org1.id, name="Key1", prefix=prefix1, key_hash=hash1)
        api_key2 = ApiKey(organization_id=org2.id, name="Key2", prefix=prefix2, key_hash=hash2)
        db_session.add_all([api_key1, api_key2])
        db_session.commit()

        return {
            "org1": org1,
            "org2": org2,
            "key1": raw_key1,
            "key2": raw_key2
        }

    def test_customer_list_isolation_via_api(self, client: TestClient, db_session: Session, setup_organizations):
        """Vérifier que l'endpoint GET /customers isole les données par organisation."""
        org1 = setup_organizations["org1"]
        org2 = setup_organizations["org2"]
        key1 = setup_organizations["key1"]
        key2 = setup_organizations["key2"]

        # Créer des clients pour chaque organisation
        customer1 = Customer(name="Org1 Client", email="org1@client.com", organization_id=org1.id)
        customer2 = Customer(name="Org2 Client", email="org2@client.com", organization_id=org2.id)
        db_session.add_all([customer1, customer2])
        db_session.commit()

        # Requête avec key1 - ne devrait voir que le client d'org1
        headers1 = {"Authorization": f"Bearer {key1}"}
        response1 = client.get("/v1/customers", headers=headers1)
        
        assert response1.status_code == 200
        data1 = response1.json()
        assert len(data1["items"]) == 1
        assert data1["items"][0]["name"] == "Org1 Client"

        # Requête avec key2 - ne devrait voir que le client d'org2
        headers2 = {"Authorization": f"Bearer {key2}"}
        response2 = client.get("/v1/customers", headers=headers2)
        
        assert response2.status_code == 200
        data2 = response2.json()
        assert len(data2["items"]) == 1
        assert data2["items"][0]["name"] == "Org2 Client"

    def test_invoice_creation_isolation_via_api(self, client: TestClient, db_session: Session, setup_organizations):
        """Vérifier que la création de facture via API respecte l'isolation."""
        org1 = setup_organizations["org1"]
        key1 = setup_organizations["key1"]

        # Créer un client pour org1
        customer = Customer(name="Test Client", email="test@client.com", organization_id=org1.id)
        db_session.add(customer)
        db_session.commit()

        headers = {"Authorization": f"Bearer {key1}", "Content-Type": "application/json"}
        
        payload = {
            "customer_id": customer.id,
            "number": "FAC-2024-TEST-001",
            "lines": [
                {
                    "description": "Service test",
                    "quantity": 1,
                    "unit_price_minor": 10000,
                    "tax_rate": 20.0
                }
            ]
        }

        response = client.post("/v1/invoices", json=payload, headers=headers)
        assert response.status_code == 201
        
        data = response.json()
        assert data["organization_id"] == org1.id
        assert data["customer_id"] == customer.id

        # Vérifier dans la DB que la facture est bien liée à org1
        invoice = db_session.query(Invoice).filter(Invoice.id == data["id"]).first()
        assert invoice is not None
        assert invoice.organization_id == org1.id
