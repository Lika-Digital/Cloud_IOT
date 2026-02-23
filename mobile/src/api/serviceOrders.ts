import { apiClient } from './client'

export interface ServiceOrder {
  id: number
  customer_id: number
  service_type: string
  notes: string | null
  status: string
  created_at: string
}

export const submitServiceOrder = (service_type: string, notes?: string) =>
  apiClient
    .post<ServiceOrder>('/api/customer/service-orders/', { service_type, notes })
    .then((r) => r.data)

export const getMyServiceOrders = () =>
  apiClient.get<ServiceOrder[]>('/api/customer/service-orders/mine').then((r) => r.data)
