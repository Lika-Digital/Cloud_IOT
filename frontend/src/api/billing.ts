import axios from 'axios'

const api = axios.create({ baseURL: '/api' })

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('auth_token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

export interface BillingConfig {
  id: number
  kwh_price_eur: number
  liter_price_eur: number
  updated_at: string
}

export interface SpendingRow {
  customer_id: number
  customer_name: string | null
  customer_email: string
  session_count: number
  total_kwh: number
  total_liters: number
  total_eur: number
}

export interface CustomerRow {
  id: number
  email: string
  name: string | null
  ship_name: string | null
  active_session_id: number | null
  active_session_type: string | null
  created_at: string
}

export interface ChatMessage {
  id: number
  customer_id: number
  message: string
  direction: 'from_customer' | 'from_operator'
  created_at: string
  read_at: string | null
}

export const getBillingConfig = () =>
  api.get<BillingConfig>('/billing/config').then((r) => r.data)

export const setBillingConfig = (data: { kwh_price_eur: number; liter_price_eur: number }) =>
  api.put<BillingConfig>('/billing/config', data).then((r) => r.data)

export const getSpendingOverview = () =>
  api.get<SpendingRow[]>('/billing/spending').then((r) => r.data)

export const getCustomers = () =>
  api.get<CustomerRow[]>('/billing/customers').then((r) => r.data)

export const getChatMessages = (customerId: number) =>
  api.get<ChatMessage[]>(`/chat/messages/${customerId}`).then((r) => r.data)

export const sendOperatorReply = (customerId: number, message: string) =>
  api.post<ChatMessage>(`/chat/operator/reply/${customerId}`, { message }).then((r) => r.data)

export const markChatRead = (customerId: number) =>
  api.post(`/chat/mark-read/${customerId}`).then((r) => r.data)

export const getUnreadCount = () =>
  api.get<{ unread_customers: number }>('/chat/unread-count').then((r) => r.data)
