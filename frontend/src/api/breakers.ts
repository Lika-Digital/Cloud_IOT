import axios from 'axios'
import { useAuthStore } from '../store/authStore'

// v3.8 — typed client for the internal breaker endpoints (admin + monitor).
// ERP endpoints under /api/ext/... are not used from the operator dashboard;
// only the internal /api/pedestals/... surface is consumed here.

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

// ── Types ───────────────────────────────────────────────────────────────────

export type BreakerState = 'closed' | 'tripped' | 'open' | 'resetting' | 'unknown'

export interface BreakerStatus {
  pedestal_id: number
  socket_id: number
  breaker_state: BreakerState
  breaker_last_trip_at: string | null
  breaker_trip_cause: string | null
  breaker_trip_count: number
  breaker_type: string | null
  breaker_rating: string | null
  breaker_poles: string | null
  breaker_rcd: boolean | null
  breaker_rcd_sensitivity: string | null
}

export interface BreakerEvent {
  id: number
  pedestal_id: number
  socket_id: number
  event_type:
    | 'tripped'
    | 'reset_attempted'
    | 'reset_success'
    | 'reset_failed'
    | 'manually_opened'
  timestamp: string
  trip_cause: string | null
  current_at_trip: number | null
  reset_initiated_by: string | null
}

// ── Calls ───────────────────────────────────────────────────────────────────

export const getSocketBreakerStatus = (pedestalId: number, socketId: number) =>
  api.get<BreakerStatus>(
    `/pedestals/${pedestalId}/sockets/${socketId}/breaker/status`,
  ).then((r) => r.data)

export const getSocketBreakerHistory = (
  pedestalId: number,
  socketId: number,
  limit = 10,
) =>
  api.get<{ pedestal_id: number; socket_id: number; events: BreakerEvent[] }>(
    `/pedestals/${pedestalId}/sockets/${socketId}/breaker/history`,
    { params: { limit } },
  ).then((r) => r.data)

export const getPedestalBreakerHistory = (pedestalId: number) =>
  api.get<{ pedestal_id: number; events: BreakerEvent[] }>(
    `/pedestals/${pedestalId}/breaker/history`,
  ).then((r) => r.data)

export const postBreakerReset = (pedestalId: number, socketId: number) =>
  api.post<{
    status: 'reset_command_sent'
    socket_id: number
    initiated_by: string
  }>(
    `/pedestals/${pedestalId}/sockets/${socketId}/breaker/reset`,
  ).then((r) => r.data)
