from datetime import datetime
from decimal import Decimal
from typing import Optional
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from .models import UserRole


class OrganizationCreate(BaseModel):
    name: str = Field(min_length=2, max_length=200)


class OrganizationRead(OrganizationCreate):
    model_config = ConfigDict(from_attributes=True)
    id: str
    created_at: datetime


class ApiKeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class ApiKeyRead(BaseModel):
    id: str
    name: str
    prefix: str
    key: str
    created_at: datetime


class CustomerCreate(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    email: EmailStr | None = None
    tax_id: str | None = Field(default=None, max_length=64)


class CustomerRead(CustomerCreate):
    model_config = ConfigDict(from_attributes=True)
    id: str
    organization_id: str
    created_at: datetime


class InvoiceCreate(BaseModel):
    customer_id: str | None = None  # Optionnel en lecture : la colonne peut être NULL après annulation de la facture liée
    number: str = Field(min_length=1, max_length=64)
    total_minor: int = Field(default=0, ge=0)
    currency: str = Field(default="EUR", min_length=3, max_length=3)
    notes: str | None = None


class InvoiceUpdate(BaseModel):
    number: str | None = Field(default=None, min_length=1, max_length=64)
    total_minor: int | None = Field(default=None, gt=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    notes: str | None = None


class InvoiceRead(BaseModel):
    """Lecture d'une facture (indépendante de InvoiceCreate : un client supprimé
    met customer_id à NULL en cascade, ce qui n'est pas une donnée d'entrée valide)."""

    model_config = ConfigDict(from_attributes=True)
    id: str
    organization_id: str
    customer_id: str | None = None
    number: str
    total_minor: int
    currency: str
    status: str
    issued_at: datetime | None = None
    created_at: datetime


# Schemas for invoices created with line items
class InvoiceLineCreate(BaseModel):
    description: str = Field(min_length=1, max_length=500)
    quantity: Decimal = Field(default=Decimal("1.00"), gt=0)
    unit_price_minor: int = Field(gt=0, description="Unit price excluding tax in cents")
    tax_rate: Decimal = Field(default=Decimal("20.00"), ge=0, le=100, description="Tax rate percentage")
    product_code: str | None = Field(default=None, max_length=64)


class InvoiceCreateWithLines(BaseModel):
    customer_id: str
    # Chaîne vide autorisée : déclenche l'auto-génération du numéro (séquence officielle).
    number: str = Field(default="", max_length=64)
    currency: str = Field(default="EUR", min_length=3, max_length=3)
    notes: str | None = None
    payment_terms: str | None = None
    purchase_order_number: str | None = None
    lines: list[InvoiceLineCreate] = Field(..., min_length=1)


class InvoiceLineRead(BaseModel):
    id: str
    description: str
    quantity: Decimal
    unit_price_minor: int
    tax_rate: Decimal
    line_total_minor: int
    tax_amount_minor: int
    line_gross_minor: int
    product_code: str | None = None

    model_config = ConfigDict(from_attributes=True)


class InvoiceReadWithLines(InvoiceRead):
    lines: list[InvoiceLineRead] = []
    subtotal_minor: int = 0
    tax_total_minor: int = 0
    amount_due_minor: int = 0
    issue_date: datetime | None = None
    due_date: datetime | None = None
    payment_terms: str | None = None
    purchase_order_number: str | None = None
    updated_at: datetime | None = None


class PaginatedCustomers(BaseModel):
    items: list[CustomerRead]
    total: int
    page: int
    per_page: int
    pages: int


class PaginatedInvoices(BaseModel):
    items: list[InvoiceRead]
    total: int
    page: int
    per_page: int
    pages: int


# User & Auth Schemas
class UserCreate(BaseModel):
    email: EmailStr = Field(max_length=320)
    password: str = Field(min_length=8, max_length=72)
    full_name: str | None = Field(default=None, max_length=200)


class UserRegister(BaseModel):
    email: EmailStr = Field(max_length=320)
    password: str = Field(min_length=8, max_length=72)
    full_name: str | None = Field(default=None, max_length=200)
    organization_name: str = Field(min_length=2, max_length=200)


class UserUpdate(BaseModel):
    full_name: str | None = Field(default=None, max_length=200)
    is_active: bool | None = None


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    organization_id: str
    email: EmailStr
    full_name: str | None = None
    role: UserRole
    is_active: bool
    email_verified: bool
    mfa_enabled: bool
    last_login_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class UserReadWithMFA(UserRead):
    mfa_secret: str | None = None


class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class TokenRefresh(BaseModel):
    refresh_token: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    mfa_code: str | None = None


class MFASetup(BaseModel):
    mfa_code: str


class PasswordReset(BaseModel):
    email: EmailStr


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=8, max_length=72)
    new_password: str = Field(min_length=8, max_length=72)


class InviteUser(BaseModel):
    email: EmailStr = Field(max_length=320)
    full_name: str | None = Field(default=None, max_length=200)
    role: UserRole = UserRole.VIEWER


class InvitationCreate(BaseModel):
    email: EmailStr
    role: UserRole
    expires_in_days: int = Field(default=7, ge=1, le=30)


class InvitationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    organization_id: str
    email: EmailStr
    role: UserRole
    invited_by_id: str
    invited_by_email: str
    status: str  # pending, accepted, expired, revoked
    expires_at: datetime
    created_at: datetime


class PaginatedUsers(BaseModel):
    items: list[UserRead]
    total: int
    page: int
    per_page: int
    pages: int


# Invoice Numbering Schemas
class InvoiceNumberGenerate(BaseModel):
    """Schéma pour demander la génération d'un numéro de facture."""
    organization_id: str | None = None  # Optionnel, pris du contexte si non fourni
    year: int | None = Field(default=None, ge=2000, le=2100)
    prefix: str | None = Field(default=None, min_length=1, max_length=10)


class InvoiceNumberResponse(BaseModel):
    """Réponse contenant le numéro généré."""
    model_config = ConfigDict(from_attributes=True)
    number: str
    year: int
    prefix: str
    sequence: int
    generated_at: datetime = Field(default_factory=lambda: datetime.now())


class InvoiceNumberValidationRequest(BaseModel):
    """Schéma pour valider un numéro de facture."""
    number: str = Field(min_length=1, max_length=64)


class InvoiceNumberValidationResponse(BaseModel):
    """Résultat de la validation d'un numéro."""
    is_valid: bool
    error_message: str | None = None


class InvoiceContinuityCheckResponse(BaseModel):
    """Résultat de la vérification de continuité de numérotation."""
    has_gaps: bool
    expected_count: int
    actual_count: int
    gaps: list[str]
    min_number: str | None
    max_number: str | None
    year: int
    prefix: str


# ---------------------------------------------------------------------------
# Transmission PDP (facturation électronique)
# ---------------------------------------------------------------------------


class TransmissionRead(BaseModel):
    """Représentation en lecture d'une transmission."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    organization_id: str
    invoice_id: str | None
    credit_note_id: str | None
    pdp_provider: str
    status: str
    external_reference: str | None
    error_message: str | None
    attempt_count: int
    last_attempt_at: datetime | None
    transmitted_at: datetime | None
    accepted_at: datetime | None
    created_at: datetime | None
    updated_at: datetime | None


class TransmissionSubmitRequest(BaseModel):
    """Demande de transmission d'une facture à une PDP."""

    invoice_id: str = Field(min_length=1)
    provider: str = Field(default="mock", min_length=1, max_length=64)
    format: str = Field(default="factur-x", pattern="^(factur-x|xml)$")


class PDPProvidersResponse(BaseModel):
    """Liste des fournisseurs PDP enregistrés."""

    providers: list[str]


# ---------------------------------------------------------------------------
# Webhooks
# ---------------------------------------------------------------------------

class WebhookEndpointCreate(BaseModel):
    url: str = Field(min_length=8, max_length=512)
    events: list[str] = Field(min_length=1, max_length=20)
    secret: str | None = Field(default=None, min_length=10, max_length=255)


class WebhookEndpointRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    organization_id: str
    url: str
    events: list[str]
    is_active: bool
    created_at: datetime | None = None

    @field_validator("events", mode="before")
    @classmethod
    def _parse_events(cls, value):
        if isinstance(value, str):
            import json as _json
            try:
                return _json.loads(value)
            except ValueError:
                return []
        return value


class WebhookDeliveryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    webhook_id: str
    event_type: str
    status: str
    http_status: int | None
    attempt_count: int
    error_message: str | None
    delivered_at: datetime | None
    created_at: datetime | None


class WebhookTestRequest(BaseModel):
    event_type: str = Field(default="webhook.test", min_length=1, max_length=64)
    data: dict = Field(default_factory=dict)
