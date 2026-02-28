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

// ─── Types ────────────────────────────────────────────────────────────────────

export interface PedestalConfigData {
  id: number
  pedestal_id: number
  site_id: string | null
  dock_id: string | null
  berth_ref: string | null
  pedestal_uid: string | null
  pedestal_model: string | null
  mqtt_username: string | null
  mqtt_password: string | null
  opta_client_id: string | null
  camera_stream_url: string | null
  camera_fqdn: string | null
  camera_username: string | null
  camera_password: string | null
  sensor_config_mode: 'auto' | 'manual'
  mdns_discovered: DiscoveredDevice[]
  snmp_discovered: SnmpDevice[]
  opta_connected: boolean
  last_heartbeat: string | null
  camera_reachable: boolean
  last_camera_check: string | null
  updated_at: string | null
  sensors: PedestalSensorData[]
}

export interface PedestalSensorData {
  id: number
  pedestal_id: number
  sensor_name: string
  sensor_type: string
  mqtt_topic: string
  unit: string | null
  min_alarm: number | null
  max_alarm: number | null
  is_active: boolean
  source: 'manual' | 'auto_mqtt'
  created_at: string | null
}

export interface PedestalConfigUpdate {
  site_id?: string
  dock_id?: string
  berth_ref?: string
  pedestal_uid?: string
  pedestal_model?: string
  mqtt_username?: string
  mqtt_password?: string
  opta_client_id?: string
  camera_stream_url?: string
  camera_fqdn?: string
  camera_username?: string
  camera_password?: string
  sensor_config_mode?: 'auto' | 'manual'
}

export interface SensorCreate {
  sensor_name: string
  sensor_type: string
  mqtt_topic: string
  unit?: string
  min_alarm?: number
  max_alarm?: number
  is_active?: boolean
}

export interface DiscoveredDevice {
  name: string
  address: string
  port: number
  type: string
}

export interface SnmpDevice {
  ip: string
  sysDescr: string
}

export interface PedestalHealth {
  opta_connected: boolean
  last_heartbeat: string | null
  camera_reachable: boolean
  last_camera_check: string | null
}

// ─── API calls ────────────────────────────────────────────────────────────────

export const getPedestalConfig = (id: number) =>
  api.get<PedestalConfigData>(`/admin/pedestal/${id}/config`).then((r) => r.data)

export const updatePedestalConfig = (id: number, data: PedestalConfigUpdate) =>
  api.put<PedestalConfigData>(`/admin/pedestal/${id}/config`, data).then((r) => r.data)

export const getPedestalSensors = (id: number) =>
  api.get<PedestalSensorData[]>(`/admin/pedestal/${id}/sensors`).then((r) => r.data)

export const addSensor = (id: number, data: SensorCreate) =>
  api.post<PedestalSensorData>(`/admin/pedestal/${id}/sensors`, data).then((r) => r.data)

export const deleteSensor = (sensorId: number) =>
  api.delete(`/admin/pedestal/sensors/${sensorId}`).then((r) => r.data)

export const runMdnsScan = (id: number) =>
  api.post<{ discovered: DiscoveredDevice[] }>(`/admin/pedestal/${id}/discover/mdns`).then((r) => r.data)

export const runSnmpScan = (id: number, subnet?: string) =>
  api.post<{ discovered: SnmpDevice[] }>(
    `/admin/pedestal/${id}/discover/snmp`,
    null,
    { params: subnet ? { subnet } : undefined }
  ).then((r) => r.data)

export const getPedestalHealth = () =>
  api.get<Record<number, PedestalHealth>>('/pedestals/health').then((r) => r.data)
