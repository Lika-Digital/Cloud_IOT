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
  berth_type: 'transit' | 'yearly'
  status: 'free' | 'occupied' | 'reserved'
  detected_status: string
  last_analyzed: string | null
  // ML outputs
  occupied_bit: number
  match_ok_bit: number
  state_code: number     // 0=FREE  1=CORRECT  2=WRONG
  alarm: number
  match_score: number | null
  analysis_error: string | null
  confidence?: number
  // Camera (from pedestal_config)
  camera_stream_url: string | null
  camera_reachable: boolean
  // Reference images
  reference_image_count: number
  // Re-ID embedding (Section 7)
  sample_embedding_path?: string | null
  sample_updated_at?: string | null
  // Detection zone (Section 8)
  zone_x1?: number
  zone_y1?: number
  zone_x2?: number
  zone_y2?: number
  use_detection_zone?: number
}

export interface CalendarEntry {
  reservation_id: number
  customer_id: number
  check_in_date: string
  check_out_date: string
  status: string
}

export interface AnalyzeResult {
  ok: boolean
  detected_status: string
  occupied_bit: number
  match_ok_bit: number
  state_code: number
  alarm: number
  match_score: number | null
  error: string | null
  confidence?: number
  crop_path?: string | null
}

export interface StorageStatus {
  size_gb: number
  max_gb: number
  percent_used: number
  alarm_active: boolean
}

export const getBerths = () =>
  api.get<BerthOut[]>('/berths').then((r) => r.data)

export const getBerthCalendar = (berthId: number) =>
  api.get<CalendarEntry[]>(`/admin/berths/calendar/${berthId}`).then((r) => r.data)

export const triggerAnalysis = (berthId: number) =>
  api.post<AnalyzeResult>(`/admin/berths/${berthId}/analyze`).then((r) => r.data)

export const getReferenceImages = (berthId: number) =>
  api.get<{ images: string[] }>(`/admin/berths/${berthId}/reference-images`).then((r) => r.data.images)

export const uploadReferenceImages = (berthId: number, formData: FormData) =>
  api.post<{ saved: string[]; count: number }>(
    `/admin/berths/${berthId}/reference-images`,
    formData,
    { headers: { 'Content-Type': 'multipart/form-data' } },
  ).then((r) => r.data)

export const deleteReferenceImage = (berthId: number, filename: string) =>
  api.delete(`/admin/berths/${berthId}/reference-images/${encodeURIComponent(filename)}`).then((r) => r.data)

export const updateBerthConfig = (berthId: number, body: {
  name?: string
  pedestal_id?: number
  berth_type?: 'transit' | 'yearly'
  zone_x1?: number
  zone_y1?: number
  zone_x2?: number
  zone_y2?: number
  use_detection_zone?: number
}) =>
  api.put(`/admin/berths/${berthId}/config`, body).then((r) => r.data)

export const createBerth = (body: { name?: string; pedestal_id?: number; berth_type?: 'transit' | 'yearly' }) =>
  api.post('/admin/berths', body).then((r) => r.data)

export const deleteBerth = (berthId: number) =>
  api.delete(`/admin/berths/${berthId}`).then((r) => r.data)

// Sector configuration (Section 8)
export const getLatestFrame = (pedestalId: number) =>
  api.get<{ frame_b64: string | null }>(`/admin/pedestals/${pedestalId}/latest-frame`).then(r => r.data)

export const uploadSampleEmbedding = (berthId: number, formData: FormData) =>
  api.post<{ ok: boolean; berth_id: number; embedding_dim: number }>(
    `/admin/berths/${berthId}/sample-embedding`, formData,
    { headers: { 'Content-Type': 'multipart/form-data' } }
  ).then(r => r.data)

export const matchShip = (berthId: number) =>
  api.post<{ match_score: number; timestamp: string }>(`/admin/berths/${berthId}/match`).then(r => r.data)

export const confirmCrop = (berthId: number, imagePath: string, confirmed: boolean) =>
  api.post(`/admin/berths/${berthId}/confirm-crop`, { image_path: imagePath, confirmed }).then(r => r.data)

export const getStorageStatus = () =>
  api.get<StorageStatus>('/system/training-storage').then(r => r.data)
