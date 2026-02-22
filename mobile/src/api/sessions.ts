import { apiClient } from './client'

export interface Session {
  id: number
  pedestal_id: number
  socket_id: number | null
  type: string
  status: string
  started_at: string
  ended_at: string | null
  energy_kwh: number | null
  water_liters: number | null
  customer_id: number | null
  deny_reason: string | null
}

export interface StartSessionBody {
  pedestal_id: number
  type: 'electricity' | 'water'
  socket_id?: number
  side?: string
}

export const startSession = (body: StartSessionBody) =>
  apiClient.post<Session>('/api/customer/sessions/start', body).then((r) => r.data)

export const getMySessions = () =>
  apiClient.get<Session[]>('/api/customer/sessions/mine').then((r) => r.data)

export const stopMySession = (id: number) =>
  apiClient.post<Session>(`/api/customer/sessions/${id}/stop`).then((r) => r.data)
