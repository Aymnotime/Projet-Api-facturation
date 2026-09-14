"""
Tests pour le service de numérotation des factures.
Vérifie la génération, la validation et la continuité de la numérotation.
"""
import pytest
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select, func

from app.models import Invoice, Organization, Customer
from app.services.invoice_numbering_service import (
    InvoiceNumberingService,
    InvoiceNumberingError
)


class TestInvoiceNumberingService:
    """Tests unitaires pour le service de numérotation."""
    
    def test_generate_first_invoice_number(self, db_session, test_organization):
        """Teste la génération du premier numéro de facture."""
        from datetime import datetime
        current_year = datetime.now().year
        
        number = InvoiceNumberingService.generate_number(
            db=db_session,
            organization_id=test_organization.id
        )
        
        assert number == f"FAC-{current_year}-0001"
    
    def test_generate_sequential_numbers(self, db_session, test_organization):
        """Teste la génération de numéros séquentiels."""
        from datetime import datetime
        current_year = datetime.now().year
        
        # Créer une première facture manuellement
        customer = Customer(
            organization_id=test_organization.id,
            name="Test Customer"
        )
        db_session.add(customer)
        db_session.commit()
        db_session.refresh(customer)
        
        invoice1 = Invoice(
            organization_id=test_organization.id,
            customer_id=customer.id,
            number=f"FAC-{current_year}-0001",
            subtotal_minor=10000,
            tax_total_minor=2000,
            total_minor=12000,
            amount_due_minor=12000
        )
        db_session.add(invoice1)
        db_session.commit()
        
        # Générer le prochain numéro
        number2 = InvoiceNumberingService.generate_number(
            db=db_session,
            organization_id=test_organization.id
        )
        
        assert number2 == f"FAC-{current_year}-0002"
    
    def test_generate_number_with_custom_prefix(self, db_session, test_organization):
        """Teste la génération avec un préfixe personnalisé."""
        number = InvoiceNumberingService.generate_number(
            db=db_session,
            organization_id=test_organization.id,
            prefix="INV"
        )
        
        from datetime import datetime
        current_year = datetime.now().year
        assert number == f"INV-{current_year}-0001"
    
    def test_generate_number_with_custom_year(self, db_session, test_organization):
        """Teste la génération avec une année personnalisée."""
        number = InvoiceNumberingService.generate_number(
            db=db_session,
            organization_id=test_organization.id,
            year=2024
        )
        
        assert number == "FAC-2024-0001"
    
    def test_validate_number_format_valid(self):
        """Teste la validation d'un numéro valide."""
        is_valid, error = InvoiceNumberingService.validate_number_format("FAC-2025-0001")
        
        assert is_valid is True
        assert error is None
    
    def test_validate_number_format_empty(self):
        """Teste la validation d'un numéro vide."""
        is_valid, error = InvoiceNumberingService.validate_number_format("")
        
        assert is_valid is False
        assert error is not None
    
    def test_validate_number_format_special_chars(self):
        """Teste la validation d'un numéro avec caractères spéciaux."""
        is_valid, error = InvoiceNumberingService.validate_number_format("FAC@2025#0001")
        
        assert is_valid is False
        assert "caractères spéciaux" in error
    
    def test_validate_number_format_too_long(self):
        """Teste la validation d'un numéro trop long."""
        long_number = "FAC-" + "2025-" + "0" * 60
        
        is_valid, error = InvoiceNumberingService.validate_number_format(long_number)
        
        assert is_valid is False
        assert "64 caractères" in error
    
    def test_validate_number_format_invalid_year(self):
        """Teste la validation d'un numéro avec année invalide."""
        is_valid, error = InvoiceNumberingService.validate_number_format("FAC-1900-0001")
        
        assert is_valid is False
        assert "Année invalide" in error
    
    def test_check_continuity_no_gaps(self, db_session, test_organization):
        """Teste la vérification de continuité sans trous."""
        # Créer des factures continues
        customer = Customer(
            organization_id=test_organization.id,
            name="Test Customer"
        )
        db_session.add(customer)
        db_session.commit()
        
        for i in range(1, 6):
            invoice = Invoice(
                organization_id=test_organization.id,
                customer_id=customer.id,
                number=f"FAC-2025-{i:04d}",
                subtotal_minor=10000,
                tax_total_minor=2000,
                total_minor=12000,
                amount_due_minor=12000
            )
            db_session.add(invoice)
        
        db_session.commit()
        
        result = InvoiceNumberingService.check_continuity(
            db=db_session,
            organization_id=test_organization.id,
            year=2025
        )
        
        assert result["has_gaps"] is False
        assert result["expected_count"] == 5
        assert result["actual_count"] == 5
        assert len(result["gaps"]) == 0
    
    def test_check_continuity_with_gaps(self, db_session, test_organization):
        """Teste la vérification de continuité avec trous."""
        customer = Customer(
            organization_id=test_organization.id,
            name="Test Customer"
        )
        db_session.add(customer)
        db_session.commit()
        
        # Créer des factures avec des trous (1, 2, 4, 5 - manque 3)
        for i in [1, 2, 4, 5]:
            invoice = Invoice(
                organization_id=test_organization.id,
                customer_id=customer.id,
                number=f"FAC-2025-{i:04d}",
                subtotal_minor=10000,
                tax_total_minor=2000,
                total_minor=12000,
                amount_due_minor=12000
            )
            db_session.add(invoice)
        
        db_session.commit()
        
        result = InvoiceNumberingService.check_continuity(
            db=db_session,
            organization_id=test_organization.id,
            year=2025
        )
        
        assert result["has_gaps"] is True
        assert result["expected_count"] == 5
        assert result["actual_count"] == 4
        assert "FAC-2025-0003" in result["gaps"]
    
    def test_reset_sequence_when_empty(self, db_session, test_organization):
        """Teste la réinitialisation de séquence quand aucune facture n'existe."""
        success = InvoiceNumberingService.reset_sequence_for_year(
            db=db_session,
            organization_id=test_organization.id,
            year=2026
        )
        
        assert success is True
    
    def test_reset_sequence_when_not_empty_raises(self, db_session, test_organization):
        """Teste que la réinitialisation échoue si des factures existent."""
        # Créer une facture pour 2025
        customer = Customer(
            organization_id=test_organization.id,
            name="Test Customer"
        )
        db_session.add(customer)
        db_session.commit()
        
        invoice = Invoice(
            organization_id=test_organization.id,
            customer_id=customer.id,
            number="FAC-2025-0001",
            subtotal_minor=10000,
            tax_total_minor=2000,
            total_minor=12000,
            amount_due_minor=12000
        )
        db_session.add(invoice)
        db_session.commit()
        
        with pytest.raises(InvoiceNumberingError) as exc_info:
            InvoiceNumberingService.reset_sequence_for_year(
                db=db_session,
                organization_id=test_organization.id,
                year=2025
            )
        
        assert "existent déjà" in str(exc_info.value)
    
    def test_get_next_sequence(self, db_session, test_organization):
        """Teste la récupération de la prochaine séquence."""
        from datetime import datetime
        current_year = datetime.now().year
        
        customer = Customer(
            organization_id=test_organization.id,
            name="Test Customer"
        )
        db_session.add(customer)
        db_session.commit()
        
        # Créer 3 factures
        for i in range(1, 4):
            invoice = Invoice(
                organization_id=test_organization.id,
                customer_id=customer.id,
                number=f"FAC-{current_year}-{i:04d}",
                subtotal_minor=10000,
                tax_total_minor=2000,
                total_minor=12000,
                amount_due_minor=12000
            )
            db_session.add(invoice)
        
        db_session.commit()
        
        next_seq = InvoiceNumberingService.get_next_sequence(
            db=db_session,
            organization_id=test_organization.id
        )
        
        assert next_seq == 4
    
    def test_isolation_between_organizations(self, db_session, test_organization):
        """Teste l'isolation de numérotation entre organisations."""
        from datetime import datetime
        current_year = datetime.now().year
        
        # Créer une deuxième organisation
        org2 = Organization(name="Org 2")
        db_session.add(org2)
        db_session.commit()
        
        # Créer une facture dans org1
        customer1 = Customer(organization_id=test_organization.id, name="Customer 1")
        db_session.add(customer1)
        db_session.commit()
        
        invoice1 = Invoice(
            organization_id=test_organization.id,
            customer_id=customer1.id,
            number=f"FAC-{current_year}-0001",
            subtotal_minor=10000,
            tax_total_minor=2000,
            total_minor=12000,
            amount_due_minor=12000
        )
        db_session.add(invoice1)
        db_session.commit()
        
        # Générer un numéro pour org2 - devrait être 0001 aussi (chaque org a sa propre séquence)
        number2 = InvoiceNumberingService.generate_number(
            db=db_session,
            organization_id=org2.id
        )
        
        assert number2 == f"FAC-{current_year}-0001"


class TestInvoiceNumberingAPI:
    """Tests d'intégration pour les endpoints API de numérotation."""
    
    def test_generate_number_endpoint(self, client, auth_headers, test_organization):
        """Teste l'endpoint de génération de numéro."""
        response = client.post(
            "/v1/invoice-numbering/generate",
            headers=auth_headers(test_organization),
            json={}
        )
        
        assert response.status_code == 201
        data = response.json()
        assert "number" in data
        assert data["number"].startswith("FAC-2025-")
    
    def test_validate_number_endpoint_valid(self, client, auth_headers, test_organization):
        """Teste l'endpoint de validation avec un numéro valide."""
        response = client.post(
            "/v1/invoice-numbering/validate",
            headers=auth_headers(test_organization),
            json={"number": "FAC-2025-0001"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["is_valid"] is True
    
    def test_validate_number_endpoint_invalid(self, client, auth_headers, test_organization):
        """Teste l'endpoint de validation avec un numéro invalide."""
        response = client.post(
            "/v1/invoice-numbering/validate",
            headers=auth_headers(test_organization),
            json={"number": "INVALID@NUMBER"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["is_valid"] is False
    
    def test_continuity_check_endpoint(self, client, auth_headers, test_organization):
        """Teste l'endpoint de vérification de continuité."""
        response = client.get(
            "/v1/invoice-numbering/continuity",
            headers=auth_headers(test_organization)
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "has_gaps" in data
        assert "expected_count" in data
        assert "actual_count" in data
    
    def test_next_sequence_endpoint(self, client, auth_headers, test_organization):
        """Teste l'endpoint de récupération de la prochaine séquence."""
        response = client.get(
            "/v1/invoice-numbering/next-sequence",
            headers=auth_headers(test_organization)
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "next_sequence" in data
        assert "formatted_number" in data
    
    def test_create_invoice_auto_generates_number(self, client, auth_headers, test_organization):
        """Teste que la création de facture génère automatiquement un numéro."""
        # Créer un client d'abord
        customer_response = client.post(
            "/v1/customers",
            headers=auth_headers(test_organization),
            json={"name": "Test Customer", "email": "test@example.com"}
        )
        customer_id = customer_response.json()["id"]
        
        # Créer une facture SANS numéro (auto-génération)
        invoice_data = {
            "customer_id": customer_id,
            "number": "",  # Vide pour auto-génération
            "currency": "EUR",
            "lines": [
                {
                    "description": "Service test",
                    "quantity": 1,
                    "unit_price_minor": 10000,
                    "tax_rate": 20.0
                }
            ]
        }
        
        response = client.post(
            "/v1/invoices",
            headers=auth_headers(test_organization),
            json=invoice_data
        )
        
        assert response.status_code == 201
        data = response.json()
        assert "number" in data
        assert data["number"].startswith("FAC-2025-")
    
    def test_create_invoice_with_custom_number(self, client, auth_headers, test_organization):
        """Teste que la création de facture accepte un numéro personnalisé."""
        # Créer un client
        customer_response = client.post(
            "/v1/customers",
            headers=auth_headers(test_organization),
            json={"name": "Test Customer", "email": "test@example.com"}
        )
        customer_id = customer_response.json()["id"]
        
        # Créer une facture AVEC numéro personnalisé
        invoice_data = {
            "customer_id": customer_id,
            "number": "CUSTOM-2025-ABC",
            "currency": "EUR",
            "lines": [
                {
                    "description": "Service test",
                    "quantity": 1,
                    "unit_price_minor": 10000,
                    "tax_rate": 20.0
                }
            ]
        }
        
        response = client.post(
            "/v1/invoices",
            headers=auth_headers(test_organization),
            json=invoice_data
        )
        
        assert response.status_code == 201
        data = response.json()
        assert data["number"] == "CUSTOM-2025-ABC"
    
    def test_create_invoice_duplicate_number_fails(self, client, auth_headers, test_organization):
        """Teste que la création échoue avec un numéro en double."""
        # Créer un client
        customer_response = client.post(
            "/v1/customers",
            headers=auth_headers(test_organization),
            json={"name": "Test Customer", "email": "test@example.com"}
        )
        customer_id = customer_response.json()["id"]
        
        invoice_data = {
            "customer_id": customer_id,
            "number": "DUP-2025-001",
            "currency": "EUR",
            "lines": [
                {
                    "description": "Service test",
                    "quantity": 1,
                    "unit_price_minor": 10000,
                    "tax_rate": 20.0
                }
            ]
        }
        
        # Première création - succès
        response1 = client.post(
            "/v1/invoices",
            headers=auth_headers(test_organization),
            json=invoice_data
        )
        assert response1.status_code == 201
        
        # Deuxième création avec même numéro - échec
        response2 = client.post(
            "/v1/invoices",
            headers=auth_headers(test_organization),
            json=invoice_data
        )
        assert response2.status_code == 409
        assert "already exists" in response2.json()["detail"]
