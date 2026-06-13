import axios from 'axios'
import { useAuthStore } from '../store/authStore'

const api = axios.create({ baseURL: '/api' })

api.interceptors.request.use((config) => {
  const token = useAuthStore.getState().token
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

export interface BackupMeta {
  filename: string
  size_bytes: number
  modified: string
}

export type ConfigBundle = Record<string, unknown>
export type RestoreReport = Record<string, { updated: number; inserted: number; skipped: number }>

export const exportConfig = (full = false): Promise<ConfigBundle> =>
  api.get<ConfigBundle>('/admin/config/export', { params: { full } }).then((r) => r.data)

export const getSupportBundle = (): Promise<ConfigBundle> =>
  api.get<ConfigBundle>('/admin/config/support-bundle').then((r) => r.data)

export const listBackups = (): Promise<{ backups: BackupMeta[] }> =>
  api.get<{ backups: BackupMeta[] }>('/admin/config/backups').then((r) => r.data)

export const importConfig = (bundle: ConfigBundle): Promise<{ status: string; report: RestoreReport }> =>
  api.post<{ status: string; report: RestoreReport }>('/admin/config/import', bundle).then((r) => r.data)
