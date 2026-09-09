import axios from 'axios';
import type { Invoice, Customer, Organization, PaginatedResponse } from '@/types';

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1';

const api = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Intercepteur pour ajouter le token d'authentification
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('auth_token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

export const invoiceApi = {
  getAll: async (page = 1, perPage = 20, status?: string) => {
    const params = new URLSearchParams({ page: String(page), per_page: String(perPage) });
    if (status) params.append('status', status);
    
    const response = await api.get<PaginatedResponse<Invoice>>(`/invoices?${params}`);
    return response.data;
  },

  getById: async (id: string) => {
    const response = await api.get<Invoice>(`/invoices/${id}`);
    return response.data;
  },

  create: async (data: Partial<Invoice>) => {
    const response = await api.post<Invoice>('/invoices', data);
    return response.data;
  },

  update: async (id: string, data: Partial<Invoice>) => {
    const response = await api.patch<Invoice>(`/invoices/${id}`, data);
    return response.data;
  },

  delete: async (id: string) => {
    await api.delete(`/invoices/${id}`);
  },

  issue: async (id: string) => {
    const response = await api.post<Invoice>(`/invoices/${id}/issue`);
    return response.data;
  },

  cancel: async (id: string) => {
    const response = await api.post<Invoice>(`/invoices/${id}/cancel`);
    return response.data;
  },

  markPaid: async (id: string) => {
    const response = await api.post<Invoice>(`/invoices/${id}/mark-paid`);
    return response.data;
  },
};

export const customerApi = {
  getAll: async (page = 1, perPage = 20) => {
    const params = new URLSearchParams({ page: String(page), per_page: String(perPage) });
    const response = await api.get<PaginatedResponse<Customer>>(`/customers?${params}`);
    return response.data;
  },

  getById: async (id: string) => {
    const response = await api.get<Customer>(`/customers/${id}`);
    return response.data;
  },

  create: async (data: Partial<Customer>) => {
    const response = await api.post<Customer>('/customers', data);
    return response.data;
  },

  update: async (id: string, data: Partial<Customer>) => {
    const response = await api.patch<Customer>(`/customers/${id}`, data);
    return response.data;
  },

  delete: async (id: string) => {
    await api.delete(`/customers/${id}`);
  },
};

export const organizationApi = {
  getCurrent: async () => {
    const response = await api.get<Organization>('/organizations/current');
    return response.data;
  },

  update: async (id: string, data: Partial<Organization>) => {
    const response = await api.patch<Organization>(`/organizations/${id}`, data);
    return response.data;
  },
};

export default api;
