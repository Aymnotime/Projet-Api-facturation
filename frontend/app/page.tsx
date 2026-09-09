'use client';

import { useState } from 'react';
import Sidebar from '@/components/Sidebar';
import DashboardPage from '@/components/DashboardPage';
import InvoicesPage from '@/components/InvoicesPage';
import CustomersPage from '@/components/CustomersPage';
import SettingsPage from '@/components/SettingsPage';

type Page = 'dashboard' | 'invoices' | 'customers' | 'settings';

export default function DashboardLayout() {
  const [currentPage, setCurrentPage] = useState<Page>('dashboard');

  const renderPage = () => {
    switch (currentPage) {
      case 'dashboard':
        return <DashboardPage />;
      case 'invoices':
        return <InvoicesPage />;
      case 'customers':
        return <CustomersPage />;
      case 'settings':
        return <SettingsPage />;
      default:
        return <DashboardPage />;
    }
  };

  return (
    <div className="flex h-screen bg-gray-100">
      <div className="w-64 flex-shrink-0">
        <Sidebar />
      </div>
      <main className="flex-1 overflow-y-auto">{renderPage()}</main>
    </div>
  );
}
