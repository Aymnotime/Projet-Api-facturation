from datetime import datetime
from decimal import Decimal
from typing import Optional
from pydantic import BaseModel, ConfigDict, EmailStr, Field

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
    customer_id: str
    number: str = Field(min_length=1, max_length=64)
    total_minor: int = Field(gt=0)
    currency: str = Field(default="EUR", min_length=3, max_length=3)
    notes: str | None = None


class InvoiceUpdate(BaseModel):
    number: str | None = Field(default=None, min_length=1, max_length=64)
    total_minor: int | None = Field(default=None, gt=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    notes: str | None = None


class InvoiceRead(InvoiceCreate):
    model_config = ConfigDict(from_attributes=True)
    id: str
    organization_id: str
    status: str
    issued_at: datetime | None = None
    created_at: datetime


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
