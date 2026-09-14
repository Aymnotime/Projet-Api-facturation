from datetime import datetime
from decimal import Decimal
from enum import Enum as PyEnum
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


class UserRole(str, PyEnum):
    OWNER = "owner"
    ADMIN = "admin"
    DEVELOPER = "developer"
    ACCOUNTANT = "accountant"
    VIEWER = "viewer"


class InvoiceStatus(str, PyEnum):
    DRAFT = "draft"
    ISSUED = "issued"
    PAID = "paid"
    CANCELLED = "cancelled"
    VOID = "void"


class TransmissionStatus(str, PyEnum):
    DRAFT = "draft"
    VALIDATING = "validating"
    VALIDATED = "validated"
    GENERATING = "generating"
    GENERATED = "generated"
    READY_TO_SEND = "ready_to_send"
    TRANSMITTING = "transmitting"
    TRANSMITTED = "transmitted"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    FAILED = "failed"


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    
    api_keys: Mapped[list["ApiKey"]] = relationship(back_populates="organization", cascade="all, delete-orphan")
    customers: Mapped[list["Customer"]] = relationship(back_populates="organization", cascade="all, delete-orphan")
    invoices: Mapped[list["Invoice"]] = relationship(back_populates="organization", cascade="all, delete-orphan")
    users: Mapped[list["User"]] = relationship(back_populates="organization", cascade="all, delete-orphan")
    invoice_lines: Mapped[list["InvoiceLine"]] = relationship(back_populates="organization", cascade="all, delete-orphan")
    credit_notes: Mapped[list["CreditNote"]] = relationship(back_populates="organization", cascade="all, delete-orphan")
    transmissions: Mapped[list["Transmission"]] = relationship(back_populates="organization", cascade="all, delete-orphan")
    webhooks: Mapped[list["WebhookEndpoint"]] = relationship(back_populates="organization", cascade="all, delete-orphan")
    events: Mapped[list["Event"]] = relationship(back_populates="organization", cascade="all, delete-orphan")
    audit_logs: Mapped[list["AuditLog"]] = relationship(back_populates="organization", cascade="all, delete-orphan")
    idempotency_keys: Mapped[list["IdempotencyKey"]] = relationship(back_populates="organization", cascade="all, delete-orphan")
    number_sequences: Mapped[list["NumberSequence"]] = relationship(back_populates="organization", cascade="all, delete-orphan")
    invitations: Mapped[list["Invitation"]] = relationship(back_populates="organization", cascade="all, delete-orphan")

    __table_args__ = (Index("ix_organizations_name", "name"),)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    role: Mapped[str] = mapped_column(Enum(UserRole), default=UserRole.VIEWER)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    mfa_secret: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
    organization: Mapped[Organization] = relationship(back_populates="users")
    invitations: Mapped[list["Invitation"]] = relationship(back_populates="accepted_user", foreign_keys="Invitation.accepted_user_id")


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    prefix: Mapped[str] = mapped_column(String(16))
    environment: Mapped[str] = mapped_column(String(16), default="test")  # test or live
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    organization: Mapped[Organization] = relationship(back_populates="api_keys")


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    tax_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    siret: Mapped[str | None] = mapped_column(String(14), nullable=True)
    address_line1: Mapped[str | None] = mapped_column(String(255), nullable=True)
    address_line2: Mapped[str | None] = mapped_column(String(255), nullable=True)
    postal_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    country: Mapped[str] = mapped_column(String(2), default="FR")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    organization: Mapped[Organization] = relationship(back_populates="customers")
    invoices: Mapped[list["Invoice"]] = relationship(back_populates="customer")

    __table_args__ = (Index("idx_customers_org_name", "organization_id", "name"),)


class Invoice(Base):
    __tablename__ = "invoices"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"))
    number: Mapped[str] = mapped_column(String(64), index=True)
    currency: Mapped[str] = mapped_column(String(3), default="EUR")
    status: Mapped[str] = mapped_column(Enum(InvoiceStatus), default=InvoiceStatus.DRAFT)
    issue_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    due_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    issued_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    subtotal_minor: Mapped[int] = mapped_column(Integer, default=0)  # HT
    tax_total_minor: Mapped[int] = mapped_column(Integer, default=0)  # TVA
    total_minor: Mapped[int] = mapped_column(Integer, default=0)  # TTC
    amount_due_minor: Mapped[int] = mapped_column(Integer, default=0)  # Restant à payer
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    payment_terms: Mapped[str | None] = mapped_column(Text, nullable=True)
    purchase_order_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
    organization: Mapped[Organization] = relationship(back_populates="invoices")
    customer: Mapped[Customer] = relationship(back_populates="invoices")
    lines: Mapped[list["InvoiceLine"]] = relationship(back_populates="invoice", cascade="all, delete-orphan")
    transmissions: Mapped[list["Transmission"]] = relationship(back_populates="invoice", cascade="all, delete-orphan")
    events: Mapped[list["Event"]] = relationship(back_populates="invoice", cascade="all, delete-orphan")
    payments: Mapped[list["Payment"]] = relationship(back_populates="invoice", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("organization_id", "number", name="uq_invoice_org_number"),
        Index("idx_invoices_org_status", "organization_id", "status"),
        Index("idx_invoices_org_issue_date", "organization_id", "issue_date"),
    )


class InvoiceLine(Base):
    __tablename__ = "invoice_lines"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    invoice_id: Mapped[str] = mapped_column(ForeignKey("invoices.id", ondelete="CASCADE"))
    description: Mapped[str] = mapped_column(String(500))
    quantity: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=1)
    unit: Mapped[str] = mapped_column(String(20), default="unit")  # unit, hour, day, etc.
    unit_price_minor: Mapped[int] = mapped_column(Integer)  # Prix unitaire HT en centimes
    discount_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=0)  # % remise
    discount_amount_minor: Mapped[int] = mapped_column(Integer, default=0)  # Montant remise HT
    tax_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=20)  # % TVA
    tax_amount_minor: Mapped[int] = mapped_column(Integer, default=0)  # Montant TVA
    line_total_minor: Mapped[int] = mapped_column(Integer)  # Total ligne HT
    line_gross_minor: Mapped[int] = mapped_column(Integer)  # Total ligne TTC
    position: Mapped[int] = mapped_column(Integer, default=0)
    product_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    organization: Mapped[Organization] = relationship(back_populates="invoice_lines")
    invoice: Mapped[Invoice] = relationship(back_populates="lines")


class CreditNote(Base):
    __tablename__ = "credit_notes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"))
    number: Mapped[str] = mapped_column(String(64), index=True)
    currency: Mapped[str] = mapped_column(String(3), default="EUR")
    status: Mapped[str] = mapped_column(Enum(InvoiceStatus), default=InvoiceStatus.DRAFT)
    issue_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    issued_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    original_invoice_id: Mapped[str | None] = mapped_column(ForeignKey("invoices.id"), nullable=True)
    reason: Mapped[str] = mapped_column(Text)
    subtotal_minor: Mapped[int] = mapped_column(Integer, default=0)
    tax_total_minor: Mapped[int] = mapped_column(Integer, default=0)
    total_minor: Mapped[int] = mapped_column(Integer, default=0)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    organization: Mapped[Organization] = relationship(back_populates="credit_notes")
    customer: Mapped[Customer] = relationship()
    original_invoice: Mapped[Invoice | None] = relationship()

    __table_args__ = (
        UniqueConstraint("organization_id", "number", name="uq_credit_note_org_number"),
    )


class Transmission(Base):
    __tablename__ = "transmissions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    invoice_id: Mapped[str | None] = mapped_column(ForeignKey("invoices.id"), nullable=True)
    credit_note_id: Mapped[str | None] = mapped_column(ForeignKey("credit_notes.id"), nullable=True)
    pdp_provider: Mapped[str] = mapped_column(String(64))  # Nom du PDP
    status: Mapped[str] = mapped_column(Enum(TransmissionStatus), default=TransmissionStatus.DRAFT)
    external_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    transmitted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
    organization: Mapped[Organization] = relationship(back_populates="transmissions")
    invoice: Mapped[Invoice | None] = relationship(back_populates="transmissions")


class WebhookEndpoint(Base):
    __tablename__ = "webhook_endpoints"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    url: Mapped[str] = mapped_column(String(512))
    secret: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    events: Mapped[str] = mapped_column(Text, default="[]")  # JSON string of events
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
    organization: Mapped[Organization] = relationship(back_populates="webhooks")


class WebhookDelivery(Base):
    __tablename__ = "webhook_deliveries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    webhook_id: Mapped[str] = mapped_column(ForeignKey("webhook_endpoints.id", ondelete="CASCADE"), index=True)
    event_type: Mapped[str] = mapped_column(String(64))
    payload: Mapped[str] = mapped_column(Text)  # JSON string
    status: Mapped[str] = mapped_column(String(32), default="pending")  # pending, success, failed
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Event(Base):
    """Event sourcing léger pour tracer l'historique immuable."""
    __tablename__ = "events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    aggregate_type: Mapped[str] = mapped_column(String(64))  # invoice, credit_note, etc.
    aggregate_id: Mapped[str] = mapped_column(String(36), ForeignKey("invoices.id", ondelete="CASCADE"), index=True)
    event_type: Mapped[str] = mapped_column(String(64))  # invoice.created, invoice.issued, etc.
    actor_type: Mapped[str] = mapped_column(String(32))  # user, api_key, system
    actor_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    event_metadata: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON string
    payload: Mapped[str] = mapped_column(Text)  # JSON string
    occurred_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    organization: Mapped[Organization] = relationship(back_populates="events")
    invoice: Mapped[Invoice | None] = relationship(back_populates="events")

    __table_args__ = (Index("idx_events_aggregate", "aggregate_type", "aggregate_id"),)


class AuditLog(Base):
    """Logs d'audit pour toutes les opérations sensibles."""
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    action: Mapped[str] = mapped_column(String(64))  # login, create_api_key, delete_invoice, etc.
    resource_type: Mapped[str] = mapped_column(String(64))
    resource_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    actor_type: Mapped[str] = mapped_column(String(32))  # user, api_key, system
    actor_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON string
    occurred_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    organization: Mapped[Organization] = relationship(back_populates="audit_logs")

    __table_args__ = (Index("idx_audit_logs_actor", "actor_type", "actor_id"),)


class IdempotencyKey(Base):
    """Clés d'idempotence pour éviter les doublons."""
    __tablename__ = "idempotency_keys"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    key: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    method: Mapped[str] = mapped_column(String(16))  # POST, PUT, etc.
    path: Mapped[str] = mapped_column(String(512))
    response_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_body: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON string
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    organization: Mapped[Organization] = relationship(back_populates="idempotency_keys")

    __table_args__ = (Index("idx_idempotency_key_org_key", "organization_id", "key"),)


class Invitation(Base):
    """User invitations for multi-tenant onboarding."""
    __tablename__ = "invitations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    email: Mapped[str] = mapped_column(String(320))
    token: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    role: Mapped[str] = mapped_column(Enum(UserRole), default=UserRole.VIEWER)
    status: Mapped[str] = mapped_column(String(32), default="pending")  # pending, accepted, declined, expired
    invited_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    expires_at: Mapped[datetime]
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    accepted_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    organization: Mapped[Organization] = relationship(back_populates="invitations")
    accepted_user: Mapped["User"] = relationship(back_populates="invitations")

    __table_args__ = (Index("idx_invitations_email_org", "email", "organization_id"),)


class NumberSequence(Base):
    """Number sequences for invoice/credit note numbering per organization."""
    __tablename__ = "number_sequences"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    doc_type: Mapped[str] = mapped_column(String(64))  # "invoice", "credit_note", etc.
    prefix: Mapped[str | None] = mapped_column(String(32), nullable=True)
    year: Mapped[int]
    current_value: Mapped[int] = mapped_column(Integer, default=0)
    padding: Mapped[int] = mapped_column(Integer, default=6)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    organization: Mapped[Organization] = relationship(back_populates="number_sequences")

    __table_args__ = (
        UniqueConstraint("organization_id", "doc_type", "year", name="uq_number_sequences_org_type_year"),
        
    )


class Payment(Base):
    """Payments linked to invoices."""
    __tablename__ = "payments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    invoice_id: Mapped[str] = mapped_column(ForeignKey("invoices.id", ondelete="CASCADE"), index=True)
    amount_minor: Mapped[int]
    payment_date: Mapped[datetime]
    method: Mapped[str] = mapped_column(String(64))
    reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    invoice: Mapped[Invoice] = relationship(back_populates="payments")
