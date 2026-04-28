import axios from 'axios'
import { useAuthStore } from '../store/authStore'

// v3.10 — typed client for the per-pedestal daily LED schedule.

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

export type LedColor = 'green' | 'blue' | 'red' | 'yellow'

export interface LedSchedule {
  pedestal_id: number
  enabled: boolean
  on_time: string | null
  off_time: string | null
  color: LedColor
  days_of_week: string
  updated_at: string | null
}

export interface LedScheduleBody {
  enabled: boolean
  on_time: string
  off_time: string
  color: LedColor
  days_of_week: string
}

export const getLedSchedule = (pedestalId: number) =>
  api.get<LedSchedule>(`/pedestals/${pedestalId}/led-schedule`).then((r) => r.data)

export const upsertLedSchedule = (pedestalId: number, body: LedScheduleBody) =>
  api.put<LedSchedule>(`/pedestals/${pedestalId}/led-schedule`, body).then((r) => r.data)

export const deleteLedSchedule = (pedestalId: number) =>
  api.delete<{ deleted: boolean }>(`/pedestals/${pedestalId}/led-schedule`).then((r) => r.data)

export const testLedSchedule = (pedestalId: number) =>
  api.post<{ status: string; pedestal_id: number; color: LedColor; state: string }>(
    `/pedestals/${pedestalId}/led-schedule/test`,
  ).then((r) => r.data)
