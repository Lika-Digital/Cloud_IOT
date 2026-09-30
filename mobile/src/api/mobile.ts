import { apiClient } from './client'

// v3.6 — QR-claim + live monitoring types, mirroring backend/app/routers/mobile.py.
//
// v3.43 — QR addresses all SIX outlets: Q1-Q4 (electricity) and V1-V2 (water). Six outlets
// reachable by NFC and four by QR was a difference nobody could explain to a customer
// standing at a water outlet with no code on it.
//
// Consequence for every consumer of these types: `energy_kwh` / `power_kw` and
// `water_liters` / `flow_lpm` are now NULLABLE, and exactly one pair carries figures. Null
// means "this outlet does not measure that quantity" — it is not 0.0, which would read as a
// measurement of nothing. A component that calls `.toFixed()` on the wrong pair crashes
// rather than lying, which is the preferable of the two.

export type QrClaimStatus = 'no_session' | 'claimed' | 'already_owner' | 'read_only'

export type OutletType = 'socket' | 'valve'
export type SessionType = 'electricity' | 'water'

// 'unknown' is only ever returned for a water outlet: the firmware sends no valve state —
// there is no "hose connected" signal and no valve state topic — so idle and pending cannot
// be told apart. Render it as "—" rather than picking one.
export type OutletState = 'idle' | 'pending' | 'active' | 'fault' | 'unknown'

export interface QrClaimNoSession {
  status: 'no_session'
  pedestal_id: string
  socket_id: string
  outlet_type: OutletType
  session_type: SessionType
  socket_state: OutletState
}

export interface QrClaimSession {
  status: Exclude<QrClaimStatus, 'no_session'>
  session_id: number
  pedestal_id: string
  socket_id: string
  outlet_type: OutletType
  session_type: SessionType
  socket_state: OutletState
  session_started_at: string | null
  duration_seconds: number
  energy_kwh: number | null
  power_kw: number | null
  water_liters: number | null
  flow_lpm: number | null
  is_owner: boolean
  websocket_token: string
}

export type QrClaimResponse = QrClaimNoSession | QrClaimSession

export interface SessionLiveResponse {
  session_id: number
  socket_state: OutletState
  session_type: SessionType
  duration_seconds: number
  energy_kwh: number | null
  power_kw: number | null
  water_liters: number | null
  flow_lpm: number | null
  last_updated_at: string
}


export async function qrClaim(pedestal_id: string, socket_id: string): Promise<QrClaimResponse> {
  const r = await apiClient.post('/api/mobile/qr/claim', { pedestal_id, socket_id })
  return r.data as QrClaimResponse
}


export async function sessionLive(sessionId: number): Promise<SessionLiveResponse> {
  const r = await apiClient.get(`/api/mobile/sessions/${sessionId}/live`)
  return r.data as SessionLiveResponse
}
