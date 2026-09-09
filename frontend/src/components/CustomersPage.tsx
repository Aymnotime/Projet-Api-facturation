'use client';

import { useState, useEffect } from 'react';
import { Plus, Search, Building2, Mail, Phone, MapPin } from 'lucide-react';
import type { Customer, PaginatedResponse } from '@/types';
import { customerApi } from '@/lib/api';

export default function CustomersPage() {
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [perPage] = useState(20);
  const [total, setTotal] = useState(0);
  const [pages, setPages] = useState(0);
  const [searchTerm, setSearchTerm] = useState('');

  const fetchCustomers = async () => {
    setLoading(true);
    try {
      const data = await customerApi.getAll(page, perPage);
      setCustomers(data.items);
      setTotal(data.total);
      setPages(data.pages);
    } catch (error) {
      console.error('Erreur lors du chargement des clients:', error);
      alert('Erreur lors du chargement des clients');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchCustomers();
  }, [page]);

  const handleCreateCustomer = () => {
    alert('Fonctionnalité de création à implémenter');
  };

  return (
    <div className="p-8">
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-gray-900">Clients</h1>
        <p className="mt-2 text-sm text-gray-600">Gérez vos clients et leurs informations</p>
      </div>

      {/* Filters */}
      <div className="mb-6 flex flex-col sm:flex-row gap-4">
        <div className="flex-1 relative">
          <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 text-gray-400 h-5 w-5" />
          <input
            type="text"
            placeholder="Rechercher un client..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="w-full pl-10 pr-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
          />
        </div>

        <button
          onClick={handleCreateCustomer}
          className="flex items-center px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
        >
          <Plus className="h-5 w-5 mr-2" />
          Nouveau client
        </button>
      </div>

      {/* Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {loading ? (
          <div className="col-span-full p-8 text-center">
            <div className="inline-block animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
            <p className="mt-2 text-gray-600">Chargement des clients...</p>
          </div>
        ) : customers.length === 0 ? (
          <div className="col-span-full p-8 text-center">
            <Building2 className="mx-auto h-12 w-12 text-gray-400" />
            <p className="mt-4 text-gray-500">Aucun client trouvé</p>
            <button
              onClick={handleCreateCustomer}
              className="mt-4 text-blue-600 hover:text-blue-800 font-medium"
            >
              Ajouter votre premier client
            </button>
          </div>
        ) : (
          customers.map((customer) => (
            <div
              key={customer.id}
              className="bg-white rounded-lg shadow border border-gray-200 p-6 hover:shadow-md transition-shadow"
            >
              <div className="flex items-start justify-between mb-4">
                <div className="flex items-center">
                  <div className="h-10 w-10 rounded-full bg-blue-100 flex items-center justify-center">
                    <Building2 className="h-6 w-6 text-blue-600" />
                  </div>
                  <div className="ml-3">
                    <h3 className="text-lg font-semibold text-gray-900">{customer.name}</h3>
                    {customer.vat_number && (
                      <p className="text-sm text-gray-500">TVA: {customer.vat_number}</p>
                    )}
                  </div>
                </div>
              </div>

              <div className="space-y-2 text-sm text-gray-600">
                {customer.email && (
                  <div className="flex items-center">
                    <Mail className="h-4 w-4 mr-2 text-gray-400" />
                    {customer.email}
                  </div>
                )}
                {customer.phone && (
                  <div className="flex items-center">
                    <Phone className="h-4 w-4 mr-2 text-gray-400" />
                    {customer.phone}
                  </div>
                )}
                {(customer.address_line1 || customer.city) && (
                  <div className="flex items-start">
                    <MapPin className="h-4 w-4 mr-2 mt-0.5 text-gray-400" />
                    <span>
                      {[customer.address_line1, customer.postal_code, customer.city, customer.country]
                        .filter(Boolean)
                        .join(', ')}
                    </span>
                  </div>
                )}
              </div>

              <div className="mt-4 pt-4 border-t border-gray-200 flex justify-end space-x-2">
                <button className="text-sm text-blue-600 hover:text-blue-800 font-medium">
                  Voir les factures
                </button>
                <button className="text-sm text-gray-600 hover:text-gray-800 font-medium">
                  Modifier
                </button>
              </div>
            </div>
          ))
        )}
      </div>

      {/* Pagination */}
      {customers.length > 0 && (
        <div className="mt-8 flex items-center justify-between">
          <p className="text-sm text-gray-600">
            Affichage de <span className="font-medium">{customers.length}</span> sur{' '}
            <span className="font-medium">{total}</span> clients
          </p>
          <div className="flex items-center space-x-2">
            <button
              onClick={() => setPage(Math.max(1, page - 1))}
              disabled={page === 1}
              className="px-4 py-2 border border-gray-300 rounded-lg text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              Précédent
            </button>
            <span className="text-sm text-gray-600">
              Page {page} sur {pages}
            </span>
            <button
              onClick={() => setPage(Math.min(pages, page + 1))}
              disabled={page === pages}
              className="px-4 py-2 border border-gray-300 rounded-lg text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              Suivant
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
