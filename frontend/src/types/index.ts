export interface Invoice {
  id: string;
  invoice_number: string;
  organization_id: string;
  customer_id: string;
  status: 'draft' | 'issued' | 'paid' | 'cancelled' | 'void' | 'overdue';
  issue_date?: string;
  due_date?: string;
  currency: string;
  subtotal: number;
  tax_amount: number;
  total_amount: number;
  lines: InvoiceLine[];
  notes?: string;
  created_at: string;
  updated_at: string;
}

export interface InvoiceLine {
  id?: string;
  description: string;
  quantity: number;
  unit_price: number;
  tax_rate: number;
  tax_amount: number;
  line_total: number;
}

export interface Customer {
  id: string;
  organization_id: string;
  name: string;
  email?: string;
  phone?: string;
  address_line1?: string;
  address_line2?: string;
  postal_code?: string;
  city?: string;
  country?: string;
  vat_number?: string;
  created_at: string;
  updated_at: string;
}

export interface Organization {
  id: string;
  name: string;
  legal_name?: string;
  vat_number?: string;
  address_line1?: string;
  address_line2?: string;
  postal_code?: string;
  city?: string;
  country?: string;
  created_at: string;
  updated_at: string;
}

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  per_page: number;
  pages: number;
}

export interface User {
  id: string;
  email: string;
  full_name?: string;
  role: 'owner' | 'admin' | 'member' | 'viewer';
  organization_id: string;
  created_at: string;
}
