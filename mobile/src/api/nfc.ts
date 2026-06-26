import { apiClient } from './client'

// NFC charging flow — wraps the backend's purpose-built NFC endpoints
// (POST /api/nfc/scan, GET/POST /api/nfc/session/{id}). These authenticate with
// the static ERP X-API-Key (machine key), NOT the customer Bearer token, so we
// attach the header explicitly per call. The key is configured once in .env as
// EXPO_PUBLIC_ERP_API_KEY (preserved across `setup-env` runs).
//
// Backend, unchanged: a physical tag UID must already be admin-provisioned to a
// socket. /api/nfc/scan pre-registers the customer's intent (5-min window); the
// socket actually activates when they plug in AND Smart Mode is ON.

const ERP_API_KEY = process.env.EXPO_PUBLIC_ERP_API_KEY ?? ''

export const erpApiKeyConfigured = () => ERP_API_KEY.trim().length > 0

const erpConfig = () => ({ headers: { 'X-API-Key': ERP_API_KEY } })

export interface NfcScanResult {
  status: string // "pending"
  message: string
  cabinet_id: string // e.g. "MAR_KRK_ORM_01"
  socket_id: string // "Q1".."Q4"
  berth_id: string | null
  expires_at: string // ISO 8601
}

export interface NfcSessionStatus {
  session_id: number
  cabinet_id: string | null
  socket_id: string | null
  customer_id: string
  status: string // "active" | "ended"
  activated_at: string
  duration_minutes: number
  energy_kwh: number
  power_kw_current: number
  estimated_cost: number | null
}

/** Pre-register intent to charge on the socket this tag is provisioned to. */
export const nfcScan = (nfcTagId: string, userId: string) =>
  apiClient
    .post<NfcScanResult>('/api/nfc/scan', { nfc_tag_id: nfcTagId, user_id: userId }, erpConfig())
    .then((r) => r.data)

/** Poll authoritative session status (energy, power, estimated cost). */
export const getNfcSession = (sessionId: number) =>
  apiClient
    .get<NfcSessionStatus>(`/api/nfc/session/${sessionId}`, erpConfig())
    .then((r) => r.data)

/** Remotely stop an active NFC session. */
export const stopNfcSession = (sessionId: number) =>
  apiClient
    .post<NfcSessionStatus>(`/api/nfc/session/${sessionId}/stop`, {}, erpConfig())
    .then((r) => r.data)

/** "Q1" → 1, "Q3" → 3. Returns null if not a recognised socket label. */
export const socketLabelToNumber = (label: string | null | undefined): number | null => {
  if (!label) return null
  const m = /^Q?(\d)$/.exec(label.trim().toUpperCase())
  return m ? Number(m[1]) : null
}
