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

export interface BerthOut {
  id: number
  name: string
  pedestal_id: number | null
  status: 'free' | 'occupied' | 'reserved'
  detected_status: string
  video_source: string | null
  last_analyzed: string | null
  occupied_bit: number
  match_ok_bit: number
  state_code: number
  alarm: number
  match_score: number | null
  analysis_error: string | null
}

export interface CalendarEntry {
  reservation_id: number
  customer_id: number
  check_in_date: string
  check_out_date: string
  status: string
}

export const getBerths = () =>
  api.get<BerthOut[]>('/berths').then((r) => r.data)

export const getBerthCalendar = (berthId: number) =>
  api.get<CalendarEntry[]>(`/admin/berths/calendar/${berthId}`).then((r) => r.data)

export const triggerAnalysis = (berthId: number) =>
  api.post<{ ok: boolean; detected_status: string }>(`/admin/berths/${berthId}/analyze`).then((r) => r.data)
