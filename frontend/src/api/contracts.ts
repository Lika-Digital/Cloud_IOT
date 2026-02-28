import axios from 'axios'
import { useAuthStore } from '../store/authStore'

const api = axios.create({ baseURL: '/api' })

api.interceptors.request.use((config) => {
  const token = useAuthStore.getState().token
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

api.interceptors.response.use(
  (r) => r,
  (error) => {
    if (error.response?.status === 401) { useAuthStore.getState().logout(); window.location.href = '/login' }
    return Promise.reject(error)
  }
)

export interface ContractTemplate {
  id: number
  title: string
  body: string
  validity_days: number
  active: boolean
  notify_on_register: boolean
  created_at: string
}

export interface CustomerContract {
  id: number
  customer_id: number
  customer_name: string | null
  customer_email: string | null
  template_id: number
  template_title: string | null
  signed_at: string
  valid_until: string | null
  status: string
}

export const getTemplates = () =>
  api.get<ContractTemplate[]>('/contracts/templates').then((r) => r.data)

export const createTemplate = (data: {
  title: string
  body: string
  validity_days: number
  notify_on_register: boolean
}) => api.post<ContractTemplate>('/contracts/templates', data).then((r) => r.data)

export const updateTemplate = (id: number, data: Partial<ContractTemplate>) =>
  api.patch<ContractTemplate>(`/contracts/templates/${id}`, data).then((r) => r.data)

export const getAdminContracts = () =>
  api.get<CustomerContract[]>('/admin/contracts').then((r) => r.data)

export const downloadContractPdf = (contractId: number) =>
  api.get(`/admin/contracts/${contractId}/pdf`, { responseType: 'blob' }).then((r) => r.data)
