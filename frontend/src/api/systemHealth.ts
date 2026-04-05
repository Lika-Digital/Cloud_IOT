import axios from 'axios'
import { useAuthStore } from '../store/authStore'

const api = axios.create({ baseURL: '/api' })

api.interceptors.request.use((config) => {
  const token = useAuthStore.getState().token
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

api.interceptors.response.use(
  (r) => r,
  (error) => {
    if (error.response?.status === 401) { useAuthStore.getState().logout(); window.location.href = '/login' }
    return Promise.reject(error)
  }
)

export interface ErrorLogEntry {
  id: number
  level: 'error' | 'warning' | 'info'
  category: 'system' | 'hw'
  source: string
  message: string
  details: string | null
  created_at: string
}

export interface HealthSummary {
  total_7d: number
  errors_7d: number
  warnings_7d: number
  system_errors: number
  hw_errors: number
  hw_warnings: number
  last_24h_total: number
  last_24h_errors: number
  mqtt_connected: boolean
}

export const getHealthSummary = () =>
  api.get<HealthSummary>('/system/health').then((r) => r.data)

export const getErrorLogs = (params?: {
  category?: 'system' | 'hw'
  level?: 'error' | 'warning' | 'info'
  hours?: number
  limit?: number
}) => api.get<ErrorLogEntry[]>('/system/logs', { params }).then((r) => r.data)

export const clearLogs = () =>
  api.delete<{ deleted: number }>('/system/logs').then((r) => r.data)

// ─── Hardware stats ───────────────────────────────────────────────────────────

export interface HardwareAlarm {
  level: 'warning' | 'critical'
  param: string
  label: string
  value: number
  threshold: number
  unit: string
}

export interface HardwareActionEntry {
  timestamp: string
  param: string
  value: number
  alarm_level: string
  action: string
  result: string
}

export interface NetworkInterface {
  name: string
  up: boolean
  speed: number
  ip: string | null
  bytes_sent: number
  bytes_recv: number
  bytes_sent_hr: string
  bytes_recv_hr: string
}

export interface HardwareThresholds {
  cpu_warning: number
  cpu_critical: number
  mem_warning: number
  mem_critical: number
  disk_warning: number
  disk_critical: number
  temp_warning: number
  temp_critical: number
}

export interface HardwareStats {
  available: boolean
  error?: string
  collected_at: string
  elapsed_ms: number
  rtsp_suspended: boolean
  cpu_percent: number
  cpu_per_core: number[]
  cpu_freq_pct: number
  cpu_freq_mhz: number | null
  load_1: number
  load_5: number
  load_15: number
  mem_total: number
  mem_used: number
  mem_free: number
  mem_percent: number
  mem_total_hr: string
  mem_used_hr: string
  mem_free_hr: string
  disk_percent: number
  disk_total_hr: string
  disk_used_hr: string
  disk_free_hr: string
  disk_path: string
  cpu_temp: number | null
  cpu_temp_max: number
  uptime: string
  interfaces: NetworkInterface[]
  thresholds: HardwareThresholds
  alarms: HardwareAlarm[]
  action_log: HardwareActionEntry[]
}

export const getHardwareStats = () =>
  api.get<HardwareStats>('/system/hardware-stats').then((r) => r.data)
