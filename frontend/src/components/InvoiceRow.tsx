'use client';

import { useState } from 'react';
import { ChevronDown, ChevronUp, Download, Send, CheckCircle, XCircle } from 'lucide-react';
import type { Invoice } from '@/types';
import { formatCurrency, formatDate, getStatusColor, getStatusLabel } from '@/lib/utils';
import { invoiceApi } from '@/lib/api';

interface InvoiceRowProps {
  invoice: Invoice;
  onRefresh: () => void;
}

export default function InvoiceRow({ invoice, onRefresh }: InvoiceRowProps) {
  const [expanded, setExpanded] = useState(false);
  const [loading, setLoading] = useState<string | null>(null);

  const handleAction = async (action: 'issue' | 'cancel' | 'mark-paid') => {
    if (!confirm(`Êtes-vous sûr de vouloir ${action === 'issue' ? 'émettre' : action === 'cancel' ? 'annuler' : 'marquer comme payée'} cette facture ?`)) {
      return;
    }

    setLoading(action);
    try {
      if (action === 'issue') {
        await invoiceApi.issue(invoice.id);
      } else if (action === 'cancel') {
        await invoiceApi.cancel(invoice.id);
      } else if (action === 'mark-paid') {
        await invoiceApi.markPaid(invoice.id);
      }
      onRefresh();
    } catch (error) {
      alert('Erreur lors de l\'action: ' + (error as Error).message);
    } finally {
      setLoading(null);
    }
  };

  const handleDownload = async () => {
    setLoading('download');
    try {
      // TODO: Implementer le téléchargement du PDF depuis le backend
      alert('Fonctionnalité de téléchargement PDF à implémenter');
    } catch (error) {
      alert('Erreur lors du téléchargement: ' + (error as Error).message);
    } finally {
      setLoading(null);
    }
  };

  const canIssue = invoice.status === 'draft';
  const canCancel = invoice.status === 'issued';
  const canMarkPaid = invoice.status === 'issued';

  return (
    <>
      <tr className="border-b border-gray-200 hover:bg-gray-50">
        <td className="px-6 py-4 whitespace-nowrap">
          <button
            onClick={() => setExpanded(!expanded)}
            className="text-gray-500 hover:text-gray-700"
          >
            {expanded ? <ChevronUp className="h-5 w-5" /> : <ChevronDown className="h-5 w-5" />}
          </button>
        </td>
        <td className="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900">
          {invoice.invoice_number}
        </td>
        <td className="px-6 py-4 whitespace-nowrap">
          <span className={`inline-flex px-2.5 py-0.5 rounded-full text-xs font-medium ${getStatusColor(invoice.status)}`}>
            {getStatusLabel(invoice.status)}
          </span>
        </td>
        <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
          {formatDate(invoice.issue_date)}
        </td>
        <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
          {formatDate(invoice.due_date)}
        </td>
        <td className="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900">
          {formatCurrency(invoice.total_amount, invoice.currency)}
        </td>
        <td className="px-6 py-4 whitespace-nowrap text-right text-sm font-medium">
          <div className="flex items-center justify-end space-x-2">
            {canIssue && (
              <button
                onClick={() => handleAction('issue')}
                disabled={loading === 'issue'}
                className="text-blue-600 hover:text-blue-900 disabled:opacity-50"
              >
                <Send className="h-4 w-4" />
              </button>
            )}
            {canMarkPaid && (
              <button
                onClick={() => handleAction('mark-paid')}
                disabled={loading === 'mark-paid'}
                className="text-green-600 hover:text-green-900 disabled:opacity-50"
              >
                <CheckCircle className="h-4 w-4" />
              </button>
            )}
            {canCancel && (
              <button
                onClick={() => handleAction('cancel')}
                disabled={loading === 'cancel'}
                className="text-red-600 hover:text-red-900 disabled:opacity-50"
              >
                <XCircle className="h-4 w-4" />
              </button>
            )}
            <button
              onClick={handleDownload}
              disabled={loading === 'download'}
              className="text-gray-600 hover:text-gray-900 disabled:opacity-50"
            >
              <Download className="h-4 w-4" />
            </button>
          </div>
        </td>
      </tr>
      {expanded && (
        <tr className="bg-gray-50">
          <td colSpan={7} className="px-6 py-4">
            <div className="space-y-2">
              <h4 className="font-medium text-gray-900">Lignes de facture</h4>
              <table className="min-w-full divide-y divide-gray-200">
                <thead>
                  <tr>
                    <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Description</th>
                    <th className="px-3 py-2 text-right text-xs font-medium text-gray-500 uppercase">Qté</th>
                    <th className="px-3 py-2 text-right text-xs font-medium text-gray-500 uppercase">Prix unit.</th>
                    <th className="px-3 py-2 text-right text-xs font-medium text-gray-500 uppercase">TVA %</th>
                    <th className="px-3 py-2 text-right text-xs font-medium text-gray-500 uppercase">Total</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-200">
                  {invoice.lines.map((line, idx) => (
                    <tr key={idx}>
                      <td className="px-3 py-2 text-sm text-gray-900">{line.description}</td>
                      <td className="px-3 py-2 text-sm text-gray-500 text-right">{line.quantity}</td>
                      <td className="px-3 py-2 text-sm text-gray-500 text-right">
                        {formatCurrency(line.unit_price, invoice.currency)}
                      </td>
                      <td className="px-3 py-2 text-sm text-gray-500 text-right">{line.tax_rate}%</td>
                      <td className="px-3 py-2 text-sm text-gray-900 text-right">
                        {formatCurrency(line.line_total, invoice.currency)}
                      </td>
                    </tr>
                  ))}
                </tbody>
                <tfoot>
                  <tr>
                    <td colSpan={4} className="px-3 py-2 text-sm font-medium text-gray-900 text-right">Sous-total</td>
                    <td className="px-3 py-2 text-sm text-gray-900 text-right">
                      {formatCurrency(invoice.subtotal, invoice.currency)}
                    </td>
                  </tr>
                  <tr>
                    <td colSpan={4} className="px-3 py-2 text-sm font-medium text-gray-900 text-right">TVA</td>
                    <td className="px-3 py-2 text-sm text-gray-900 text-right">
                      {formatCurrency(invoice.tax_amount, invoice.currency)}
                    </td>
                  </tr>
                  <tr>
                    <td colSpan={4} className="px-3 py-2 text-sm font-bold text-gray-900 text-right">Total TTC</td>
                    <td className="px-3 py-2 text-sm font-bold text-gray-900 text-right">
                      {formatCurrency(invoice.total_amount, invoice.currency)}
                    </td>
                  </tr>
                </tfoot>
              </table>
              {invoice.notes && (
                <div className="mt-4 p-3 bg-white rounded-lg border border-gray-200">
                  <h4 className="font-medium text-gray-900 mb-2">Notes</h4>
                  <p className="text-sm text-gray-600">{invoice.notes}</p>
                </div>
              )}
            </div>
          </td>
        </tr>
      )}
    </>
  );
}
