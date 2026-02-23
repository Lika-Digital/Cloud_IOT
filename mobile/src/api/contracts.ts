import { apiClient } from './client'

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
  template_id: number
  template_title: string | null
  signed_at: string
  valid_until: string | null
  status: string
}

export const getPendingContracts = () =>
  apiClient.get<ContractTemplate[]>('/api/customer/contracts/pending').then((r) => r.data)

export const signContract = (templateId: number, signatureData: string) =>
  apiClient
    .post<CustomerContract>(`/api/customer/contracts/${templateId}/sign`, {
      signature_data: signatureData,
    })
    .then((r) => r.data)

export const getMyContracts = () =>
  apiClient.get<CustomerContract[]>('/api/customer/contracts/mine').then((r) => r.data)

export const getContractPdfUrl = (contractId: number) =>
  `/api/customer/contracts/${contractId}/pdf`
