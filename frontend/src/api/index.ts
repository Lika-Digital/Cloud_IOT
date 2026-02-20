import axios from 'axios'
import type { Pedestal, Session } from '../store'

const api = axios.create({ baseURL: '/api' })

// Pedestals
export const getPedestals = () => api.get<Pedestal[]>('/pedestals').then((r) => r.data)
export const getPedestal = (id: number) => api.get<Pedestal>(`/pedestals/${id}`).then((r) => r.data)
export const setMode = (
  id: number,
  mode: 'synthetic' | 'real',
  ip_address?: string
) =>
  api
    .patch<Pedestal>(`/pedestals/${id}/mode`, null, { params: { mode, ip_address } })
    .then((r) => r.data)
export const updatePedestal = (id: number, data: Partial<Pedestal>) =>
  api.patch<Pedestal>(`/pedestals/${id}`, data).then((r) => r.data)
export const createPedestal = (data: { name: string; location?: string }) =>
  api.post<Pedestal>('/pedestals', data).then((r) => r.data)
export const getSimulatorStatus = (id: number) =>
  api.get<{ running: boolean }>(`/pedestals/${id}/simulator/status`).then((r) => r.data)
export const configurePedestals = (count: number) =>
  api.post<Pedestal[]>(`/pedestals/configure`, null, { params: { count } }).then((r) => r.data)

// Sessions
export const getSessions = (params?: {
  pedestal_id?: number
  status?: string
  limit?: number
}) => api.get<Session[]>('/sessions', { params }).then((r) => r.data)
export const getPendingSessions = (pedestal_id?: number) =>
  api.get<Session[]>('/sessions/pending', { params: { pedestal_id } }).then((r) => r.data)
export const getActiveSessions = (pedestal_id?: number) =>
  api.get<Session[]>('/sessions/active', { params: { pedestal_id } }).then((r) => r.data)

// Controls
export const allowSession = (id: number) =>
  api.post<Session>(`/controls/${id}/allow`).then((r) => r.data)
export const denySession = (id: number) =>
  api.post<Session>(`/controls/${id}/deny`).then((r) => r.data)
export const stopSession = (id: number) =>
  api.post<Session>(`/controls/${id}/stop`).then((r) => r.data)

// Analytics
export const getDailyConsumption = (params?: { pedestal_id?: number; days?: number }) =>
  api.get<DailyConsumption[]>('/analytics/consumption/daily', { params }).then((r) => r.data)
export const getSessionSummary = (pedestal_id?: number) =>
  api.get<SessionSummary>('/analytics/sessions/summary', { params: { pedestal_id } }).then((r) => r.data)
export const getConsumptionBySocket = (pedestal_id?: number) =>
  api.get('/analytics/consumption/by-socket', { params: { pedestal_id } }).then((r) => r.data)
export const getConsumptionByPedestal = () =>
  api.get<PedestalConsumption[]>('/analytics/consumption/by-pedestal').then((r) => r.data)

// Diagnostics
export const runDiagnostics = (pedestalId: number) =>
  api.post<DiagnosticsResult>(`/pedestals/${pedestalId}/diagnostics/run`).then((r) => r.data)
export const resetInitialization = (pedestalId: number) =>
  api.post<{ pedestal_id: number; initialized: boolean }>(`/pedestals/${pedestalId}/diagnostics/reset`).then((r) => r.data)

// Camera
export const getCameraDetections = (pedestalId: number) =>
  api.get<CameraDetectionResponse>(`/camera/${pedestalId}/detections`).then((r) => r.data)
export const getCameraStreamUrl = (pedestalId: number) => `/api/camera/${pedestalId}/stream`

// Predictions
export const trainModels = (pedestal_id?: number) =>
  api.post('/predictions/train', null, { params: { pedestal_id } }).then((r) => r.data)
export const getPredictionStatus = () =>
  api.get<{ electricity_model_ready: boolean; water_model_ready: boolean }>('/predictions/status').then((r) => r.data)
export const predictElectricity = (duration_minutes: number) =>
  api.get<PredictionResult>('/predictions/electricity', { params: { duration_minutes } }).then((r) => r.data)
export const predictWater = (duration_minutes: number) =>
  api.get<PredictionResult>('/predictions/water', { params: { duration_minutes } }).then((r) => r.data)

// Types
export interface DailyConsumption {
  date: string
  energy_kwh: number
  water_liters: number
  session_count: number
}

export interface SessionSummary {
  total_sessions: number
  by_status: Record<string, number>
  total_energy_kwh: number
  total_water_liters: number
  completed_sessions: number
}

export interface PedestalConsumption {
  pedestal_id: number
  total_energy_kwh: number
  total_water_liters: number
  session_count: number
}

export interface DiagnosticsResult {
  pedestal_id: number
  sensors: Record<string, 'ok' | 'fail' | 'missing'>
  all_ok: boolean
  initialized: boolean
  error: string | null
}

export interface DetectionBox {
  label: string
  confidence: number
  x1: number
  y1: number
  x2: number
  y2: number
}

export interface DetectionFrame {
  time_s: number
  detections: DetectionBox[]
}

export interface CameraDetectionResponse {
  pedestal_id: number
  mode: string
  frames: DetectionFrame[]
}

export interface PredictionResult {
  predicted_duration_minutes: number
  predicted_consumption: number
  unit: string
  type: string
}
