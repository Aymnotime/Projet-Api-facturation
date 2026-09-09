"""
Core Business Logic for Invoicing
Handles financial calculations, state transitions, and validation rules.
Production-ready with precision decimal arithmetic.
"""
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from typing import List, Dict, Any, Optional
from datetime import date, datetime, timezone
import enum
import re


class InvoiceStatus(str, enum.Enum):
    DRAFT = "draft"
    ISSUED = "issued"
    PAID = "paid"
    CANCELLED = "cancelled"
    OVERDUE = "overdue"
    VOID = "void"


# Allowed transitions: Current State -> List of allowed Next States
ALLOWED_TRANSITIONS = {
    InvoiceStatus.DRAFT: [InvoiceStatus.ISSUED, InvoiceStatus.CANCELLED],
    InvoiceStatus.ISSUED: [InvoiceStatus.PAID, InvoiceStatus.CANCELLED, InvoiceStatus.OVERDUE, InvoiceStatus.VOID],
    InvoiceStatus.PAID: [InvoiceStatus.VOID],  # Can void a paid invoice
    InvoiceStatus.CANCELLED: [],  # Terminal state
    InvoiceStatus.OVERDUE: [InvoiceStatus.PAID, InvoiceStatus.CANCELLED],
    InvoiceStatus.VOID: [],  # Terminal state
}


class CalculationError(Exception):
    """Raised when calculation fails."""
    pass


class StateTransitionError(Exception):
    """Raised when state transition is invalid."""
    pass


class ValidationError(Exception):
    """Raised when validation fails."""
    pass


def calculate_line_total(quantity: Decimal, unit_price: Decimal) -> Decimal:
    """Calculate total for a single line excluding tax with proper rounding."""
    if quantity <= 0:
        raise CalculationError("Quantity must be positive")
    if unit_price < 0:
        raise CalculationError("Unit price cannot be negative")
    
    result = (quantity * unit_price).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    return result


def calculate_tax_amount(taxable_amount: Decimal, tax_rate: Decimal) -> Decimal:
    """Calculate tax amount for a specific rate with proper rounding."""
    if tax_rate < 0 or tax_rate > Decimal('100'):
        raise CalculationError("Tax rate must be between 0 and 100")
    
    result = (taxable_amount * (tax_rate / Decimal('100'))).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    return result


def calculate_invoice_totals(lines: List[Dict[str, Any]]) -> Dict[str, Decimal]:
    """
    Calculate all totals for an invoice based on line items.
    Each line must have: quantity, unit_price, tax_rate
    
    Returns: subtotal, total_tax, total_including_tax, tax_breakdown
    
    Uses tax grouping to ensure accurate VAT calculation per rate.
    """
    if not lines:
        raise CalculationError("Invoice must have at least one line item")
    
    subtotal = Decimal('0.00')
    total_tax = Decimal('0.00')
    
    # Group by tax rate to ensure accurate summation per rate
    tax_groups: Dict[Decimal, Decimal] = {}

    for i, line in enumerate(lines):
        try:
            qty = Decimal(str(line['quantity']))
            price = Decimal(str(line['unit_price']))
            tax_rate = Decimal(str(line['tax_rate']))
        except (InvalidOperation, KeyError, TypeError) as e:
            raise CalculationError(f"Invalid data in line {i+1}: {str(e)}")
        
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
    """Check if a state transition is allowed according to business rules."""
    allowed = ALLOWED_TRANSITIONS.get(current_status, [])
    return new_status in allowed


def get_next_valid_statuses(current_status: InvoiceStatus) -> List[InvoiceStatus]:
    """Get list of valid next statuses for the current state."""
    return ALLOWED_TRANSITIONS.get(current_status, [])


def validate_invoice_data(data: Dict[str, Any]) -> None:
    """
    Validate invoice data against business rules (EN 16931 basics).
    Raises ValidationError if validation fails.
    """
    errors = []
    warnings = []
    
    # Rule: Must have lines
    if not data.get('lines'):
        raise ValidationError("Invoice must have at least one line item.")
    
    # Rule: Validate each line
    for i, line in enumerate(data['lines']):
        try:
            qty = Decimal(str(line.get('quantity', 0)))
            price = Decimal(str(line.get('unit_price', 0)))
            tax_rate = Decimal(str(line.get('tax_rate', 0)))
        except (InvalidOperation, TypeError):
            errors.append(f"Line {i+1}: Invalid numeric values")
            continue
        
        if qty <= 0:
            errors.append(f"Line {i+1}: Quantity must be positive")
        if price < 0:
            errors.append(f"Line {i+1}: Unit price cannot be negative")
        if tax_rate < 0 or tax_rate > 100:
            errors.append(f"Line {i+1}: Tax rate must be between 0 and 100")
    
    # Rule: Issue date validation (warning only)
    if data.get('issue_date'):
        try:
            issue_date = data['issue_date']
            if isinstance(issue_date, date) and issue_date > date.today():
                warnings.append("Invoice dated in the future")
        except (TypeError, ValueError):
            errors.append("Invalid issue date format")
    
    if errors:
        raise ValidationError("; ".join(errors))


def validate_en16931_basic(invoice_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Perform basic EN 16931 validation checks.
    Returns validation result with errors and warnings.
    """
    errors = []
    warnings = []
    
    # Rule: Currency code must be ISO 4217 (3 letters)
    currency = invoice_data.get('currency', '')
    if len(currency) != 3 or not currency.isalpha():
        errors.append(f"Invalid currency code: {currency}. Must be ISO 4217 (3 letters)")
    
    # Rule: Total amount must be positive
    total_minor = invoice_data.get('total_minor', 0)
    if total_minor <= 0:
        errors.append(f"Total amount must be positive: {total_minor}")
    
    # Rule: Invoice number should be alphanumeric (allow - and _)
    number = invoice_data.get('number', '')
    if number and not re.match(r'^[a-zA-Z0-9_-]+$', number):
        warnings.append(f"Invoice number contains special characters: {number}")
    
    # Rule: Status workflow validation
    status = invoice_data.get('status', 'draft')
    valid_statuses = ['draft', 'issued', 'paid', 'cancelled', 'void', 'overdue']
    if status not in valid_statuses:
        warnings.append(f"Non-standard invoice status: {status}")
    
    # Rule: Issue date required for issued invoices
    if status == 'issued' and not invoice_data.get('issued_at'):
        errors.append("Issued invoice missing issue date")
    
    return {
        "is_valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "validated_at": datetime.now(timezone.utc).isoformat()
    }


def generate_invoice_number(prefix: str, sequence: int, year: Optional[int] = None) -> str:
    """
    Generate a sequential invoice number following best practices.
    Format: PREFIX-YYYY-NNNN
    """
    if year is None:
        year = datetime.now().year
    
    # Zero-pad sequence to 4 digits minimum
    seq_str = str(sequence).zfill(4)
    
    return f"{prefix}-{year}-{seq_str}"


def calculate_due_date(issue_date: datetime, payment_terms_days: int = 30) -> datetime:
    """Calculate due date based on issue date and payment terms."""
    from datetime import timedelta
    if isinstance(issue_date, datetime):
        return issue_date + timedelta(days=payment_terms_days)
    raise CalculationError("Invalid issue date format")
