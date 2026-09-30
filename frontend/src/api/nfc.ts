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

// v3.43 — a cabinet has SIX outlets, not four: 4 electricity sockets and 2 water outlets,
// each with its own NFC tag. Water works exactly like electricity — the customer scans the
// tag on the outlet they are about to use, and the session belongs to whoever scanned.
export type OutletType = 'socket' | 'valve'

export interface NfcTag {
  nfc_tag_id: string
  cabinet_id: string
  socket_id: string          // "Q1".."Q4" for a socket, "V1"/"V2" for a valve
  // Never inferred from socket_id: both backend name vocabularies accept bare digits, so
  // "1" is genuinely ambiguous between socket 1 and valve 1. The server stores it.
  outlet_type: OutletType
  session_type: 'electricity' | 'water'
  provisioned_at: string | null
  provisioned_by: string | null
  is_active: boolean
  removed_at?: string | null
  removed_by?: string | null
}

// One row of the cabinet's own account of itself, from `opta/config/hardware`.
export interface CabinetOutlet {
  outlet_name: string
  outlet_type: OutletType
  session_type: 'electricity' | 'water'
  // Electricity only. Q1 is three-phase at 32 A on MAR_KRK_ORM_01 while Q3/Q4 are 16 A —
  // the sockets are NOT identical, which the old hardcoded four-row table implied.
  meter_type: string | null
  phases: number | null
  rated_amps: number | null
  // Water only.
  rated_liters_per_min: number | null
  nfc_tag_id: string | null
}

export interface CabinetOutlets {
  cabinet_id: string
  // False when the cabinet has never published its hardware config and the server fell back
  // to the canonical six. Surfaced rather than hidden: "never heard from this cabinet" and
  // "this cabinet has no water outlets" are different situations.
  reported: boolean
  outlets: CabinetOutlet[]
}

export const listCabinetOutlets = (cabinetId: string) =>
  api.get<CabinetOutlets>(`/nfc/outlets/${cabinetId}`).then((r) => r.data)

export const listNfcTags = (cabinetId: string) =>
  api.get<NfcTag[]>(`/nfc/tags/${cabinetId}`).then((r) => r.data)

export const provisionNfcTag = (
  cabinet_id: string,
  socket_id: string,
  nfc_tag_id: string,
  outlet_type: OutletType = 'socket',
) => api.post<NfcTag>('/nfc/tags', { cabinet_id, socket_id, nfc_tag_id, outlet_type })
  .then((r) => r.data)

export const provisionNfcTagsBulk = (
  cabinet_id: string,
  items: { socket_id: string; nfc_tag_id: string; outlet_type?: OutletType }[],
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
