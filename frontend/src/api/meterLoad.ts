import axios from 'axios'
import { useAuthStore } from '../store/authStore'

// v3.11 — typed client for the internal load-monitoring endpoints.
// ERP endpoints under /api/ext/... are not consumed by the operator
// dashboard; only the internal /api/pedestals/... surface lives here.

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

// v3.12 — `auto_stop` added: terminal state set when a 90% overload
// triggers an automatic socket stop. Stays until the operator
// acknowledges via the dedicated endpoint. The store + every render
// path that switches on LoadStatus must handle this case.
export type LoadStatus = 'normal' | 'warning' | 'critical' | 'auto_stop' | 'unknown'

export interface SocketLoadState {
  pedestal_id: number
  socket_id: number
  meter_type: string | null
  phases: number | null
  rated_amps: number | null
  modbus_address: number | null
  hw_config_received_at: string | null
  current_amps: number | null
  voltage_v: number | null
  power_kw: number | null
  power_factor: number | null
  energy_kwh: number | null
  frequency_hz: number | null
  load_pct: number | null
  load_status: LoadStatus
  meter_load_updated_at: string | null
  warning_threshold_pct: number
  critical_threshold_pct: number
  // 3-phase only
  current_l1?: number | null
  current_l2?: number | null
  current_l3?: number | null
  voltage_l1?: number | null
  voltage_l2?: number | null
  voltage_l3?: number | null
}

export interface MeterLoadAlarm {
  id: number
  pedestal_id: number
  socket_id: number
  // v3.12 — 'auto_stop' added; rows of this type are written when the
  // 90% threshold triggers an automatic socket stop.
  alarm_type: 'warning' | 'critical' | 'auto_stop'
  current_amps: number
  rated_amps: number
  load_pct: number
  phases: number
  meter_type: string | null
  triggered_at: string
  resolved_at: string | null
  resolved_by: string | null
  acknowledged: boolean
  acknowledged_at: string | null
  acknowledged_by: string | null
}

export const getSocketLoad = (pedestalId: number, socketId: number) =>
  api.get<SocketLoadState>(
    `/pedestals/${pedestalId}/sockets/${socketId}/load`,
  ).then((r) => r.data)

export const getPedestalLoad = (pedestalId: number) =>
  api.get<{ pedestal_id: number; sockets: SocketLoadState[] }>(
    `/pedestals/${pedestalId}/load`,
  ).then((r) => r.data)

export const patchLoadThresholds = (
  pedestalId: number,
  socketId: number,
  warning: number,
  critical: number,
) =>
  api.patch<SocketLoadState>(
    `/pedestals/${pedestalId}/sockets/${socketId}/load/thresholds`,
    { warning_threshold_pct: warning, critical_threshold_pct: critical },
  ).then((r) => r.data)

export const getPedestalLoadAlarms = (pedestalId: number) =>
  api.get<{ pedestal_id: number; alarms: MeterLoadAlarm[] }>(
    `/pedestals/${pedestalId}/load/alarms`,
  ).then((r) => r.data)

export const getSocketLoadHistory = (pedestalId: number, socketId: number) =>
  api.get<{ pedestal_id: number; socket_id: number; events: MeterLoadAlarm[] }>(
    `/pedestals/${pedestalId}/sockets/${socketId}/load/history`,
  ).then((r) => r.data)

export const acknowledgeLoadAlarm = (pedestalId: number, alarmId: number) =>
  api.post<MeterLoadAlarm>(
    `/pedestals/${pedestalId}/load/alarms/${alarmId}/acknowledge`,
  ).then((r) => r.data)

export const resolveLoadAlarm = (pedestalId: number, alarmId: number) =>
  api.post<MeterLoadAlarm>(
    `/pedestals/${pedestalId}/load/alarms/${alarmId}/resolve`,
  ).then((r) => r.data)

// v3.12 — operator (or admin via UI) acknowledges the auto-stop alarm,
// which clears the SocketConfig.auto_stop_pending_ack latch and unblocks
// re-activation. Server returns {status, socket_id}. ERP callers use the
// /api/ext/.../auto-stop/acknowledge twin (not exposed here — the dashboard
// only ever calls the internal admin endpoint).
export const acknowledgeAutoStop = (pedestalId: number, socketId: number) =>
  api.post<{ status: string; socket_id: number }>(
    `/pedestals/${pedestalId}/sockets/${socketId}/load/auto-stop/acknowledge`,
  ).then((r) => r.data)
