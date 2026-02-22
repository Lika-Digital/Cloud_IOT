import axios from 'axios'

const api = axios.create({ baseURL: '/api' })

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('auth_token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

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
  simulator_running: boolean
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
