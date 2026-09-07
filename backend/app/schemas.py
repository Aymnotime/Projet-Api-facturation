from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel, ConfigDict, EmailStr, Field


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
