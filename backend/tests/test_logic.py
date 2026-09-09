"""Tests for core business logic module."""
import pytest
from decimal import Decimal
from datetime import date, datetime, timezone

from app.core.logic import (
    calculate_line_total,
    calculate_tax_amount,
    calculate_invoice_totals,
    validate_state_transition,
    get_next_valid_statuses,
    validate_invoice_data,
    validate_en16931_basic,
    generate_invoice_number,
    calculate_due_date,
    CalculationError,
    ValidationError,
    InvoiceStatus,
)


class TestCalculateLineTotal:
    """Test line total calculations."""
    
    def test_basic_calculation(self):
        """Test basic line total calculation."""
        result = calculate_line_total(Decimal('2.00'), Decimal('100.00'))
        assert result == Decimal('200.00')
    
    def test_decimal_precision(self):
        """Test decimal precision and rounding."""
        result = calculate_line_total(Decimal('1.5'), Decimal('99.99'))
        assert result == Decimal('149.99')  # 1.5 * 99.99 = 149.985 -> rounds to 149.99
    
    def test_zero_quantity_error(self):
        """Test that zero quantity raises error."""
        with pytest.raises(CalculationError, match="Quantity must be positive"):
            calculate_line_total(Decimal('0'), Decimal('100.00'))
    
    def test_negative_quantity_error(self):
        """Test that negative quantity raises error."""
        with pytest.raises(CalculationError, match="Quantity must be positive"):
            calculate_line_total(Decimal('-1'), Decimal('100.00'))
    
    def test_negative_price_error(self):
        """Test that negative price raises error."""
        with pytest.raises(CalculationError, match="Unit price cannot be negative"):
            calculate_line_total(Decimal('1'), Decimal('-100.00'))


class TestCalculateTaxAmount:
    """Test tax amount calculations."""
    
    def test_standard_tax_rate(self):
        """Test standard 20% tax rate."""
        result = calculate_tax_amount(Decimal('100.00'), Decimal('20.00'))
        assert result == Decimal('20.00')
    
    def test_reduced_tax_rate(self):
        """Test reduced 5.5% tax rate."""
        result = calculate_tax_amount(Decimal('100.00'), Decimal('5.5'))
        assert result == Decimal('5.50')
    
    def test_zero_tax_rate(self):
        """Test zero tax rate."""
        result = calculate_tax_amount(Decimal('100.00'), Decimal('0'))
        assert result == Decimal('0.00')
    
    def test_invalid_tax_rate_negative(self):
        """Test that negative tax rate raises error."""
        with pytest.raises(CalculationError, match="Tax rate must be between 0 and 100"):
            calculate_tax_amount(Decimal('100.00'), Decimal('-5'))
    
    def test_invalid_tax_rate_over_100(self):
        """Test that tax rate over 100 raises error."""
        with pytest.raises(CalculationError, match="Tax rate must be between 0 and 100"):
            calculate_tax_amount(Decimal('100.00'), Decimal('150'))


class TestCalculateInvoiceTotals:
    """Test invoice totals calculations."""
    
    def test_single_line(self):
        """Test calculation with single line."""
        lines = [
            {'quantity': 2, 'unit_price': Decimal('50.00'), 'tax_rate': Decimal('20.00')}
        ]
        result = calculate_invoice_totals(lines)
        
        assert result['subtotal'] == Decimal('100.00')
        assert result['total_tax'] == Decimal('20.00')
        assert result['total_including_tax'] == Decimal('120.00')
    
    def test_multiple_lines_same_tax(self):
        """Test calculation with multiple lines at same tax rate."""
        lines = [
            {'quantity': 1, 'unit_price': Decimal('100.00'), 'tax_rate': Decimal('20.00')},
            {'quantity': 2, 'unit_price': Decimal('50.00'), 'tax_rate': Decimal('20.00')}
        ]
        result = calculate_invoice_totals(lines)
        
        assert result['subtotal'] == Decimal('200.00')
        assert result['total_tax'] == Decimal('40.00')
        assert result['total_including_tax'] == Decimal('240.00')
    
    def test_multiple_lines_different_tax(self):
        """Test calculation with multiple lines at different tax rates."""
        lines = [
            {'quantity': 1, 'unit_price': Decimal('100.00'), 'tax_rate': Decimal('20.00')},
            {'quantity': 1, 'unit_price': Decimal('50.00'), 'tax_rate': Decimal('5.5')}
        ]
        result = calculate_invoice_totals(lines)
        
        assert result['subtotal'] == Decimal('150.00')
        # 100 * 20% = 20.00, 50 * 5.5% = 2.75
        assert result['total_tax'] == Decimal('22.75')
        assert result['total_including_tax'] == Decimal('172.75')
    
    def test_empty_lines_error(self):
        """Test that empty lines raise error."""
        with pytest.raises(CalculationError, match="at least one line item"):
            calculate_invoice_totals([])
    
    def test_invalid_line_data(self):
        """Test that invalid line data raises error."""
        lines = [
            {'quantity': 'invalid', 'unit_price': Decimal('100.00'), 'tax_rate': Decimal('20.00')}
        ]
        with pytest.raises(CalculationError, match="Invalid data in line"):
            calculate_invoice_totals(lines)


class TestStateTransitions:
    """Test invoice state transitions."""
    
    def test_draft_to_issued_allowed(self):
        """Test draft to issued transition is allowed."""
        assert validate_state_transition(InvoiceStatus.DRAFT, InvoiceStatus.ISSUED) is True
    
    def test_draft_to_cancelled_allowed(self):
        """Test draft to cancelled transition is allowed."""
        assert validate_state_transition(InvoiceStatus.DRAFT, InvoiceStatus.CANCELLED) is True
    
    def test_draft_to_paid_not_allowed(self):
        """Test draft to paid transition is not allowed."""
        assert validate_state_transition(InvoiceStatus.DRAFT, InvoiceStatus.PAID) is False
    
    def test_issued_to_paid_allowed(self):
        """Test issued to paid transition is allowed."""
        assert validate_state_transition(InvoiceStatus.ISSUED, InvoiceStatus.PAID) is True
    
    def test_issued_to_void_allowed(self):
        """Test issued to void transition is allowed."""
        assert validate_state_transition(InvoiceStatus.ISSUED, InvoiceStatus.VOID) is True
    
    def test_paid_is_terminal_except_void(self):
        """Test that paid is terminal except for void."""
        assert validate_state_transition(InvoiceStatus.PAID, InvoiceStatus.VOID) is True
        assert validate_state_transition(InvoiceStatus.PAID, InvoiceStatus.CANCELLED) is False
        assert validate_state_transition(InvoiceStatus.PAID, InvoiceStatus.DRAFT) is False
    
    def test_cancelled_is_terminal(self):
        """Test that cancelled is terminal state."""
        assert validate_state_transition(InvoiceStatus.CANCELLED, InvoiceStatus.DRAFT) is False
        assert validate_state_transition(InvoiceStatus.CANCELLED, InvoiceStatus.ISSUED) is False
    
    def test_get_next_valid_statuses_draft(self):
        """Test getting valid next statuses from draft."""
        statuses = get_next_valid_statuses(InvoiceStatus.DRAFT)
        assert InvoiceStatus.ISSUED in statuses
        assert InvoiceStatus.CANCELLED in statuses
        assert InvoiceStatus.PAID not in statuses


class TestValidateInvoiceData:
    """Test invoice data validation."""
    
    def test_valid_invoice(self):
        """Test validation of valid invoice data."""
        data = {
            'lines': [
                {'quantity': 1, 'unit_price': Decimal('100.00'), 'tax_rate': Decimal('20.00')}
            ]
        }
        # Should not raise
        validate_invoice_data(data)
    
    def test_missing_lines_error(self):
        """Test that missing lines raises error."""
        with pytest.raises(ValidationError, match="at least one line item"):
            validate_invoice_data({})
    
    def test_invalid_quantity(self):
        """Test that invalid quantity raises error."""
        data = {
            'lines': [
                {'quantity': -1, 'unit_price': Decimal('100.00'), 'tax_rate': Decimal('20.00')}
            ]
        }
        with pytest.raises(ValidationError, match="Quantity must be positive"):
            validate_invoice_data(data)
    
    def test_invalid_tax_rate(self):
        """Test that invalid tax rate raises error."""
        data = {
            'lines': [
                {'quantity': 1, 'unit_price': Decimal('100.00'), 'tax_rate': Decimal('150')}
            ]
        }
        with pytest.raises(ValidationError, match="Tax rate must be between 0 and 100"):
            validate_invoice_data(data)


class TestValidateEN16931Basic:
    """Test EN 16931 basic validation."""
    
    def test_valid_invoice(self):
        """Test validation of valid invoice."""
        data = {
            'currency': 'EUR',
            'total_minor': 10000,
            'number': 'INV-2024-001',
            'status': 'draft'
        }
        result = validate_en16931_basic(data)
        assert result['is_valid'] is True
        assert len(result['errors']) == 0
    
    def test_invalid_currency(self):
        """Test that invalid currency code raises error."""
        data = {
            'currency': 'EURO',  # Should be 3 letters
            'total_minor': 10000,
            'number': 'INV-001',
            'status': 'draft'
        }
        result = validate_en16931_basic(data)
        assert result['is_valid'] is False
        assert any("currency" in err.lower() for err in result['errors'])
    
    def test_negative_total(self):
        """Test that negative total raises error."""
        data = {
            'currency': 'EUR',
            'total_minor': -100,
            'number': 'INV-001',
            'status': 'draft'
        }
        result = validate_en16931_basic(data)
        assert result['is_valid'] is False
        assert any("positive" in err.lower() for err in result['errors'])
    
    def test_issued_missing_date(self):
        """Test that issued invoice without date raises error."""
        data = {
            'currency': 'EUR',
            'total_minor': 10000,
            'number': 'INV-001',
            'status': 'issued',
            'issued_at': None
        }
        result = validate_en16931_basic(data)
        assert result['is_valid'] is False
        assert any("issue date" in err.lower() for err in result['errors'])


class TestGenerateInvoiceNumber:
    """Test invoice number generation."""
    
    def test_basic_generation(self):
        """Test basic invoice number generation."""
        number = generate_invoice_number('ACME', 1, 2024)
        assert number == 'ACME-2024-0001'
    
    def test_sequence_padding(self):
        """Test sequence number padding."""
        number = generate_invoice_number('TEST', 123, 2024)
        assert number == 'TEST-2024-0123'
    
    def test_current_year_default(self):
        """Test that current year is used by default."""
        number = generate_invoice_number('XYZ', 1)
        current_year = datetime.now().year
        assert number == f'XYZ-{current_year}-0001'


class TestCalculateDueDate:
    """Test due date calculation."""
    
    def test_standard_30_days(self):
        """Test standard 30-day payment terms."""
        issue_date = datetime(2024, 1, 1, tzinfo=timezone.utc)
        due_date = calculate_due_date(issue_date, 30)
        assert due_date.day == 31  # Jan 1 + 30 days = Jan 31
    
    def test_custom_payment_terms(self):
        """Test custom payment terms."""
        issue_date = datetime(2024, 1, 1, tzinfo=timezone.utc)
        due_date = calculate_due_date(issue_date, 15)
        assert due_date.day == 16  # Jan 1 + 15 days = Jan 16
    
    def test_invalid_issue_date(self):
        """Test that invalid issue date raises error."""
        with pytest.raises(CalculationError, match="Invalid issue date"):
            calculate_due_date("not a date", 30)
