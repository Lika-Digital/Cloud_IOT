import { apiClient } from './client'

export interface Invoice {
  id: number
  session_id: number
  customer_id: number | null
  energy_kwh: number | null
  water_liters: number | null
  energy_cost_eur: number | null
  water_cost_eur: number | null
  total_eur: number
  paid: number
  created_at: string
}

export const getMyInvoices = () =>
  apiClient.get<Invoice[]>('/api/customer/invoices/mine').then((r) => r.data)

export const payInvoice = (id: number) =>
  apiClient.post<Invoice>(`/api/customer/invoices/${id}/pay`).then((r) => r.data)
