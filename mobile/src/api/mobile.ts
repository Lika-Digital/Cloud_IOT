import { apiClient } from './client'

// v3.6 — QR-claim + live monitoring types, mirroring backend/app/routers/mobile.py.

export type QrClaimStatus = 'no_session' | 'claimed' | 'already_owner' | 'read_only'

export interface QrClaimNoSession {
  status: 'no_session'
  pedestal_id: string
  socket_id: string
  socket_state: 'idle' | 'pending' | 'active' | 'fault'
}

export interface QrClaimSession {
  status: Exclude<QrClaimStatus, 'no_session'>
  session_id: number
  pedestal_id: string
  socket_id: string
  socket_state: 'idle' | 'pending' | 'active' | 'fault'
  session_started_at: string | null
  duration_seconds: number
  energy_kwh: number
  power_kw: number
  is_owner: boolean
  websocket_token: string
}

export type QrClaimResponse = QrClaimNoSession | QrClaimSession

export interface SessionLiveResponse {
  session_id: number
  socket_state: string
  duration_seconds: number
  energy_kwh: number
  power_kw: number
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
