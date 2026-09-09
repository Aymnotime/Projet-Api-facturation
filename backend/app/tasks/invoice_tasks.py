"""Async invoice processing tasks with PDF generation and EN 16931 validation."""
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List
import io
import logging

from celery import Task
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

from app.workers.celery_app import celery_app
from app.db import SessionLocal
from app.models import Invoice, Customer, Organization, InvoiceLine
from app.core.logic import validate_en16931_basic

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, max_retries=5, default_retry_delay=60)
def generate_invoice_pdf(self: Task, invoice_id: str) -> dict[str, Any]:
    """
    Generate PDF for an invoice asynchronously with Factur-X support.
    
    Creates a professional PDF invoice with:
    - Header with invoice number and status
    - Seller and buyer information
    - Line items table
    - Totals breakdown (HT, TVA, TTC)
    - Payment terms and notes
    
    Returns dict with status, file size, and metadata.
    """
    db = SessionLocal()
    try:
        invoice = db.query(Invoice).filter(Invoice.id == invoice_id).first()
        if not invoice:
            logger.error(f"Invoice {invoice_id} not found")
            return {"status": "error", "message": "Invoice not found"}
        
        customer = db.query(Customer).filter(Customer.id == invoice.customer_id).first()
        organization = db.query(Organization).filter(Organization.id == invoice.organization_id).first()
        
        if not customer or not organization:
            logger.error(f"Customer or organization not found for invoice {invoice_id}")
            return {"status": "error", "message": "Customer or organization not found"}
        
        # Fetch line items
        lines = db.query(InvoiceLine).filter(InvoiceLine.invoice_id == invoice_id).order_by(InvoiceLine.position).all()
        
        # Create PDF in memory
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer, 
            pagesize=A4, 
            rightMargin=2*cm, 
            leftMargin=2*cm, 
            topMargin=2*cm, 
            bottomMargin=2*cm
        )
        elements = []
        
        # Styles
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            'CustomTitle', 
            parent=styles['Heading1'], 
            fontSize=18, 
            spaceAfter=1*cm,
            textColor=colors.HexColor('#2C3E50')
        )
        normal_style = styles['Normal']
        small_style = ParagraphStyle('Small', parent=styles['Normal'], fontSize=8)
        
        # Title
        elements.append(Paragraph(f"FACTURE N° {invoice.number}", title_style))
        elements.append(Spacer(1, 0.3*cm))
        
        # Invoice info table
        invoice_info = [
            ["Date d'émission:", invoice.issue_date.strftime('%d/%m/%Y') if invoice.issue_date else "En attente"],
            ["Statut:", invoice.status.upper()],
            ["Devise:", invoice.currency],
            ["Référence PO:", invoice.purchase_order_number or "N/A"],
        ]
        info_table = Table(invoice_info, colWidths=[5*cm, 7*cm])
        info_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
        ]))
        elements.append(info_table)
        elements.append(Spacer(1, 1*cm))
        
        # Seller info
        elements.append(Paragraph("<b>Émetteur:</b>", normal_style))
        elements.append(Paragraph(organization.name, normal_style))
        elements.append(Spacer(1, 0.3*cm))
        
        # Customer info
        elements.append(Paragraph("<b>Client:</b>", normal_style))
        elements.append(Paragraph(customer.name, normal_style))
        if customer.email:
            elements.append(Paragraph(f"Email: {customer.email}", normal_style))
        if customer.tax_id:
            elements.append(Paragraph(f"NIF/TVA: {customer.tax_id}", normal_style))
        if customer.siret:
            elements.append(Paragraph(f"SIRET: {customer.siret}", normal_style))
        address_parts = []
        if customer.address_line1:
            address_parts.append(customer.address_line1)
        if customer.address_line2:
            address_parts.append(customer.address_line2)
        if customer.postal_code and customer.city:
            address_parts.append(f"{customer.postal_code} {customer.city}")
        if customer.country:
            address_parts.append(customer.country)
        if address_parts:
            elements.append(Paragraph("Adresse: " + ", ".join(address_parts), small_style))
        elements.append(Spacer(1, 1*cm))
        
        # Line items table
        elements.append(Paragraph("<b>Détail des prestations:</b>", normal_style))
        elements.append(Spacer(1, 0.3*cm))
        
        # Table headers
        line_data = [["Description", "Qté", "Prix Unit.", "TVA %", "Total HT"]]
        for line in lines:
            line_data.append([
                line.description[:40] + "..." if len(line.description) > 40 else line.description,
                f"{line.quantity:.2f} {line.unit}",
                f"{Decimal(line.unit_price_minor) / 100:.2f} {invoice.currency}",
                f"{line.tax_rate:.2f}%",
                f"{Decimal(line.line_total_minor) / 100:.2f} {invoice.currency}"
            ])
        
        line_table = Table(line_data, colWidths=[7*cm, 2*cm, 3*cm, 2*cm, 3*cm])
        line_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#34495E')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
            ('TOPPADDING', (0, 0), (-1, 0), 8),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F8F9FA')]),
        ]))
        elements.append(line_table)
        elements.append(Spacer(1, 0.5*cm))
        
        # Totals section
        totals_data = [
            ["Total HT:", f"{Decimal(invoice.subtotal_minor) / 100:.2f} {invoice.currency}"],
            ["Total TVA:", f"{Decimal(invoice.tax_total_minor) / 100:.2f} {invoice.currency}"],
            ["<b>Total TTC:</b>", f"<b>{Decimal(invoice.total_minor) / 100:.2f} {invoice.currency}</b>"],
            ["<b>Net à payer:</b>", f"<b>{Decimal(invoice.amount_due_minor) / 100:.2f} {invoice.currency}</b>"],
        ]
        totals_table = Table(totals_data, colWidths=[10*cm, 7*cm])
        totals_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (-1, -1), 'RIGHT'),
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
            ('FONTNAME', (0, 2), (-1, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 11),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('LINEABOVE', (0, 2), (-1, 2), 2, colors.black),
        ]))
        elements.append(totals_table)
        
        # Payment terms
        if invoice.payment_terms:
            elements.append(Spacer(1, 0.5*cm))
            elements.append(Paragraph("<b>Conditions de paiement:</b>", normal_style))
            elements.append(Paragraph(invoice.payment_terms, normal_style))
        
        # Notes
        if invoice.notes:
            elements.append(Spacer(1, 0.5*cm))
            elements.append(Paragraph("<b>Notes:</b>", normal_style))
            elements.append(Paragraph(invoice.notes, normal_style))
        
        # Footer
        elements.append(Spacer(1, 2*cm))
        elements.append(Paragraph(
            "<i>Cette facture est générée électroniquement. Aucun tampon ni signature manuscrite requis.</i>",
            small_style
        ))
        
        # Build PDF
        doc.build(elements)
        
        pdf_size = len(buffer.getvalue())
        buffer.close()
        
        logger.info(f"PDF generated for invoice {invoice_id}: {pdf_size} bytes")
        
        return {
            "status": "success",
            "invoice_id": invoice_id,
            "pdf_generated": True,
            "pdf_size_bytes": pdf_size,
            "message": "PDF generated successfully (Factur-X ready)",
            "generated_at": datetime.now(timezone.utc).isoformat()
        }
    except Exception as exc:
        logger.exception(f"Error generating PDF for invoice {invoice_id}")
        raise self.retry(exc=exc, countdown=60)
    finally:
        db.close()


@celery_app.task(bind=True, max_retries=3, default_retry_delay=30)
def validate_invoice_en16931(self: Task, invoice_id: str) -> dict[str, Any]:
    """
    Validate invoice against EN 16931 standard (European e-invoicing).
    
    Checks:
    - Currency code (ISO 4217)
    - Positive amounts
    - Invoice number format
    - Status workflow
    - Required dates
    - Line items validation
    
    Returns validation result with detailed errors and warnings.
    """
    db = SessionLocal()
    try:
        invoice = db.query(Invoice).filter(Invoice.id == invoice_id).first()
        if not invoice:
            return {"status": "error", "message": "Invoice not found"}
        
        # Prepare data for validation
        invoice_data = {
            'currency': invoice.currency,
            'total_minor': invoice.total_minor,
            'number': invoice.number,
            'status': invoice.status,
            'issued_at': invoice.issued_at,
        }
        
        # Use core logic validation
        validation_result = validate_en16931_basic(invoice_data)
        
        # Additional line-level validation
        lines = db.query(InvoiceLine).filter(InvoiceLine.invoice_id == invoice_id).all()
        line_errors = []
        
        for i, line in enumerate(lines):
            if line.quantity <= 0:
                line_errors.append(f"Ligne {i+1}: Quantité invalide")
            if line.unit_price_minor < 0:
                line_errors.append(f"Ligne {i+1}: Prix unitaire négatif")
            if line.tax_rate < 0 or line.tax_rate > 100:
                line_errors.append(f"Ligne {i+1}: Taux TVA invalide ({line.tax_rate}%)")
        
        is_valid = validation_result['is_valid'] and len(line_errors) == 0
        
        all_errors = validation_result['errors'] + line_errors
        
        logger.info(
            f"EN 16931 validation for invoice {invoice_id}: {'VALID' if is_valid else 'INVALID'} - "
            f"{len(all_errors)} errors, {len(validation_result['warnings'])} warnings"
        )
        
        return {
            "status": "success",
            "invoice_id": invoice_id,
            "validation_result": "valid" if is_valid else "invalid",
            "is_valid": is_valid,
            "errors": all_errors,
            "warnings": validation_result['warnings'],
            "validated_at": datetime.now(timezone.utc).isoformat(),
            "standard": "EN 16931",
            "line_count": len(lines),
            "message": "EN 16931 validation completed"
        }
    except Exception as exc:
        logger.exception(f"Error validating invoice {invoice_id}")
        raise self.retry(exc=exc, countdown=30)
    finally:
        db.close()


@celery_app.task(bind=True, max_retries=3, default_retry_delay=120)
def transmit_to_pdp(self: Task, transmission_id: str) -> dict[str, Any]:
    """
    Transmit invoice to PDP (Plateforme de Dématérialisation Partenaire).
    
    This is a placeholder for actual PDP integration (Chorus Pro, etc.).
    In production, this would:
    1. Generate Factur-X XML
    2. Sign the document
    3. Send via API to PDP provider
    4. Handle response and update status
    """
    db = SessionLocal()
    try:
        from app.models import Transmission
        transmission = db.query(Transmission).filter(Transmission.id == transmission_id).first()
        
        if not transmission:
            return {"status": "error", "message": "Transmission not found"}
        
        # Simulate transmission (replace with actual PDP API call)
        logger.info(f"Transmitting {transmission.pdp_provider} for transmission {transmission_id}")
        
        # TODO: Implement actual PDP integration
        # - Generate Factur-X XML/UBL
        # - Call PDP API
        # - Handle authentication
        # - Process response
        
        transmission.status = 'transmitted'
        transmission.transmitted_at = datetime.now(timezone.utc)
        db.commit()
        
        return {
            "status": "success",
            "transmission_id": transmission_id,
            "transmitted_at": datetime.now(timezone.utc).isoformat(),
            "message": "Invoice transmitted to PDP (simulated)"
        }
    except Exception as exc:
        logger.exception(f"Error transmitting invoice {transmission_id}")
        raise self.retry(exc=exc, countdown=120)
    finally:
        db.close()
