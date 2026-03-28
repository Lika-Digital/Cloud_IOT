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
