import axios from 'axios'

const api = axios.create({ baseURL: '/api' })

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('auth_token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

export interface BerthOut {
  id: number
  name: string
  pedestal_id: number | null
  status: 'free' | 'occupied' | 'reserved'
  detected_status: string
  video_source: string | null
  last_analyzed: string | null
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
