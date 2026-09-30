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
  socket_id: string // "Q1".."Q4" for a socket, "V1"/"V2" for a water outlet
  // v3.43 — a cabinet has SIX tags: 4 sockets and 2 water outlets. Water works exactly like
  // electricity, so a scan can now come back as a water session. Present on every response
  // from v3.43; optional here so an older backend does not break the typing.
  outlet_type?: 'socket' | 'valve'
  session_type?: 'electricity' | 'water'
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

/** "Q1" → 1, "Q3" → 3, "V2" → 2. Returns null if not an outlet this hardware has.
 *
 * v3.43. The old pattern was `/^Q?(\d)$/`, which returned null for "V1" — so a water scan
 * produced `outletNum: null`, and the websocket adoption check treats null as "matches
 * anything" (see useWebSocket.ts). A customer who scanned a water tag would have adopted
 * whatever electricity session appeared next under their user id.
 *
 * The prefix is now REQUIRED, and the numbers are bounded per kind. Dropping the optional
 * `Q?` matters: a bare "1" is genuinely ambiguous between socket 1 and valve 1, and this
 * function's whole job is to resolve an outlet. It returns null rather than guessing — the
 * caller pairs the number with the session type, which is what actually disambiguates.
 */
export const outletLabelToNumber = (label: string | null | undefined): number | null => {
  if (!label) return null
  const m = /^(Q[1-4]|V[1-2])$/.exec(label.trim().toUpperCase())
  return m ? Number(m[1].slice(1)) : null
}

/** @deprecated v3.43 — use `outletLabelToNumber`; kept so an un-updated import still builds. */
export const socketLabelToNumber = outletLabelToNumber
