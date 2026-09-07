"""
Core Business Logic for Invoicing
Handles financial calculations, state transitions, and validation rules.
"""
from decimal import Decimal, ROUND_HALF_UP
from typing import List, Dict, Any
from datetime import date
import enum

class InvoiceStatus(str, enum.Enum):
    DRAFT = "draft"
    ISSUED = "issued"
    PAID = "paid"
    CANCELLED = "cancelled"
    OVERDUE = "overdue"

# Allowed transitions: Current State -> List of allowed Next States
ALLOWED_TRANSITIONS = {
    InvoiceStatus.DRAFT: [InvoiceStatus.ISSUED, InvoiceStatus.CANCELLED],
    InvoiceStatus.ISSUED: [InvoiceStatus.PAID, InvoiceStatus.CANCELLED, InvoiceStatus.OVERDUE],
    InvoiceStatus.PAID: [],  # Terminal state
    InvoiceStatus.CANCELLED: [],  # Terminal state
    InvoiceStatus.OVERDUE: [InvoiceStatus.PAID],
}

class CalculationError(Exception):
    pass

class StateTransitionError(Exception):
    pass

def calculate_line_total(quantity: Decimal, unit_price: Decimal) -> Decimal:
    """Calculate total for a single line excluding tax."""
    return (quantity * unit_price).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

def calculate_tax_amount(taxable_amount: Decimal, tax_rate: Decimal) -> Decimal:
    """Calculate tax amount for a specific rate."""
    return (taxable_amount * (tax_rate / Decimal('100'))).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

def calculate_invoice_totals(lines: List[Dict[str, Any]]) -> Dict[str, Decimal]:
    """
    Calculate all totals for an invoice based on line items.
    Each line must have: quantity, unit_price, tax_rate
    Returns: subtotal, total_tax, total_including_tax
    """
    subtotal = Decimal('0.00')
    total_tax = Decimal('0.00')
    
    # Group by tax rate to ensure accurate summation
    tax_groups: Dict[Decimal, Decimal] = {}

    for line in lines:
        qty = Decimal(str(line['quantity']))
        price = Decimal(str(line['unit_price']))
        tax_rate = Decimal(str(line['tax_rate']))
        
        line_total = calculate_line_total(qty, price)
        subtotal += line_total
        
        if tax_rate not in tax_groups:
            tax_groups[tax_rate] = Decimal('0.00')
        tax_groups[tax_rate] += line_total

    # Calculate tax per group
    for rate, amount in tax_groups.items():
        total_tax += calculate_tax_amount(amount, rate)

    total_including_tax = subtotal + total_tax

    return {
        "subtotal": subtotal.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP),
        "total_tax": total_tax.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP),
        "total_including_tax": total_including_tax.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP),
        "tax_breakdown": {str(k): v for k, v in tax_groups.items()}
    }

def validate_state_transition(current_status: InvoiceStatus, new_status: InvoiceStatus) -> bool:
    """Check if a state transition is allowed."""
    allowed = ALLOWED_TRANSITIONS.get(current_status, [])
    return new_status in allowed

def get_next_valid_statuses(current_status: InvoiceStatus) -> List[InvoiceStatus]:
    """Get list of valid next statuses."""
    return ALLOWED_TRANSITIONS.get(current_status, [])

def validate_invoice_data(data: Dict[str, Any]) -> None:
    """Validate invoice data against business rules (EN 16931 basics)."""
    if not data.get('lines'):
        raise CalculationError("Invoice must have at least one line item.")
    
    for i, line in enumerate(data['lines']):
        if line['quantity'] <= 0:
            raise CalculationError(f"Line {i+1}: Quantity must be positive.")
        if line['unit_price'] < 0:
            raise CalculationError(f"Line {i+1}: Unit price cannot be negative.")
        if line['tax_rate'] < 0 or line['tax_rate'] > 100:
            raise CalculationError(f"Line {i+1}: Tax rate must be between 0 and 100.")
    
    if data.get('issue_date') and data['issue_date'] > date.today():
        # Warning only, not error, as future dating is sometimes allowed
        pass
