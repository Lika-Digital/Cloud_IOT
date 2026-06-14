import axios from 'axios'
import { useAuthStore } from '../store/authStore'

const api = axios.create({ baseURL: '/api/alarms' })

api.interceptors.request.use((config) => {
  const token = useAuthStore.getState().token
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

export interface AlarmRecord {
  id: number
  alarm_type: string
  source: string
  pedestal_id: number | null
  status: string
  severity: 'warning' | 'critical' | null
  message: string
  details?: string | null
  triggered_at: string
  acknowledged_at: string | null
  acknowledged_by: string | null
  resolved_at: string | null
}

export const getActiveAlarms = () =>
  api.get<AlarmRecord[]>('/active').then((r) => r.data)

export const acknowledgeAlarm = (id: number) =>
  api.post<AlarmRecord>(`/${id}/acknowledge`).then((r) => r.data)
