import axios from 'axios'
import { useAuthStore } from '../store/authStore'

// v3.37 — DB backup + usage-data export downloads. Both stream a file over
// HTTPS (same channel as the dashboard) so the browser saves it off the NUC.
const api = axios.create({ baseURL: '/api' })

api.interceptors.request.use((config) => {
  const token = useAuthStore.getState().token
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

function triggerDownload(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

const stamp = () => new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-')

/** Admin-only: download a consistent snapshot of both databases as a zip. */
export const downloadDatabaseBackup = async () => {
  const r = await api.get('/admin/backup/database', { responseType: 'blob' })
  triggerDownload(r.data as Blob, `cloud_iot_db_backup_${stamp()}.zip`)
}

/** Export sessions + energy intervals + invoices (control role). */
export const exportUsageData = async (
  format: 'json' | 'csv',
  dateFrom?: string,
  dateTo?: string,
) => {
  const params: Record<string, string> = { format }
  if (dateFrom) params.date_from = dateFrom
  if (dateTo) params.date_to = dateTo
  const r = await api.get('/admin/export/usage', { params, responseType: 'blob' })
  const ext = format === 'csv' ? 'zip' : 'json'
  triggerDownload(r.data as Blob, `cloud_iot_usage_${stamp()}.${ext}`)
}
