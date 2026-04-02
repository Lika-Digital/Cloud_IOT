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

export interface SmtpConfig {
  host: string
  port: number
  tls: boolean
  username: string
  password: string
  from_email: string
  configured: boolean
  source: 'db' | 'env' | 'none'
}

export const getSmtpConfig = (): Promise<SmtpConfig> =>
  api.get<SmtpConfig>('/admin/settings/smtp').then((r) => r.data)

export const updateSmtpConfig = (data: Omit<SmtpConfig, 'configured' | 'source'>): Promise<{ message: string }> =>
  api.put('/admin/settings/smtp', data).then((r) => r.data)

export const testSmtp = (): Promise<{ message: string }> =>
  api.post<{ message: string }>('/admin/settings/smtp/test').then((r) => r.data)

export interface NetworkInfo {
  lan_ip: string
  mqtt_broker_host: string
  mqtt_port: number
  snmp_trap_port: number
}

export const getNetworkInfo = (): Promise<NetworkInfo> =>
  api.get<NetworkInfo>('/admin/settings/network-info').then((r) => r.data)

export interface SnmpConfig {
  enabled: boolean
  port: number
  community: string
  temp_oid: string
  pedestal_id: number
}

export const getSnmpConfig = (): Promise<SnmpConfig> =>
  api.get<SnmpConfig>('/admin/settings/snmp').then((r) => r.data)

export const updateSnmpConfig = (data: SnmpConfig): Promise<{ message: string; config: SnmpConfig }> =>
  api.put('/admin/settings/snmp', data).then((r) => r.data)

export interface ActivePedestalItem {
  id: number
  name: string
  connected: boolean
  last_heartbeat: string | null
}

export interface ActivePedestalsInfo {
  total: number
  connected: number
  pedestals: ActivePedestalItem[]
}

export const getActivePedestals = (): Promise<ActivePedestalsInfo> =>
  api.get<ActivePedestalsInfo>('/admin/settings/active-pedestals').then((r) => r.data)

export interface PilotAssignment {
  id: number
  username: string
  pedestal_id: number
  socket_id: number
  active: boolean
  created_at: string
}

export interface PilotAssignmentCreate {
  username: string
  pedestal_id: number
  socket_id: number
}

export const getPilotAssignments = (): Promise<PilotAssignment[]> =>
  api.get<PilotAssignment[]>('/admin/settings/pilot-assignments').then((r) => r.data)

export const createPilotAssignment = (data: PilotAssignmentCreate): Promise<PilotAssignment> =>
  api.post<PilotAssignment>('/admin/settings/pilot-assignments', data).then((r) => r.data)

export const deletePilotAssignment = (id: number): Promise<void> =>
  api.delete(`/admin/settings/pilot-assignments/${id}`).then(() => undefined)
