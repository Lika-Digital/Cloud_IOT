import axios from 'axios'
import { useAuthStore } from '../store/authStore'

// Own axios instance (mirrors api/meterLoad.ts) so NFC admin calls carry the
// operator JWT and share the 401 → logout behaviour.
const api = axios.create({ baseURL: '/api' })

api.interceptors.request.use((config) => {
  const token = useAuthStore.getState().token
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

api.interceptors.response.use(
  (r) => r,
  (error) => {
    if (error.response?.status === 401) {
      useAuthStore.getState().logout()
      window.location.href = '/login'
    }
    return Promise.reject(error)
  },
)

export type ProvisioningMode = 'qr' | 'nfc'

export interface NfcTag {
  nfc_tag_id: string
  cabinet_id: string
  socket_id: string          // "Q1".."Q4"
  provisioned_at: string | null
  provisioned_by: string | null
  is_active: boolean
}

export const listNfcTags = (cabinetId: string) =>
  api.get<NfcTag[]>(`/nfc/tags/${cabinetId}`).then((r) => r.data)

export const provisionNfcTag = (cabinet_id: string, socket_id: string, nfc_tag_id: string) =>
  api.post<NfcTag>('/nfc/tags', { cabinet_id, socket_id, nfc_tag_id }).then((r) => r.data)

export const provisionNfcTagsBulk = (
  cabinet_id: string,
  items: { socket_id: string; nfc_tag_id: string }[],
) => api.post<{ cabinet_id: string; tags: NfcTag[] }>('/nfc/tags/bulk', { cabinet_id, items })
  .then((r) => r.data)

export const removeNfcTag = (cabinet_id: string, socket_id: string) =>
  api.delete(`/nfc/tags/${cabinet_id}/${socket_id}`).then((r) => r.data)

export const getProvisioningMode = (cabinetId: string) =>
  api.get<{ cabinet_id: string; provisioning_mode: ProvisioningMode }>(`/nfc/mode/${cabinetId}`)
    .then((r) => r.data)

export const setProvisioningMode = (cabinetId: string, mode: ProvisioningMode) =>
  api.patch<{ cabinet_id: string; provisioning_mode: ProvisioningMode; auto_activate: boolean; sockets_updated: number }>(
    `/nfc/mode/${cabinetId}`, { mode },
  ).then((r) => r.data)
