import axios from 'axios'
import { useAuthStore } from '../store/authStore'

// v3.31 — typed client for the internal usage-history + monthly-report endpoints
// (admin only). Report download returns a plain-text blob; deletion is admin-only.

const api = axios.create({ baseURL: '/api' })

api.interceptors.request.use((config) => {
  const token = useAuthStore.getState().token
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

// ── Types ───────────────────────────────────────────────────────────────────

export type UsageResource = 'electricity' | 'water'

export interface UsageRow {
  session_id: number
  socket_id: number | null
  type: UsageResource
  started_at: string | null
  ended_at: string | null
  energy_kwh: number | null
  water_liters: number | null
  customer_id: number | null
  customer_name: string | null
  nfc_user_id: string | null
  end_reason: string | null
  /** 'register' | 'integrated_legacy' | 'unknown' | null. A figure without one is not shown
   *  as measured (the report's rule, 2026-10-14). */
  consumption_source: string | null
  /** The two register readings the figure is the difference of (kWh or L), or null. */
  register_start: number | null
  register_end: number | null
}

export interface ReportMeta {
  month: string          // "YYYY-MM"
  filename: string
  size_bytes: number
  generated_at: string
}

// ── Calls ───────────────────────────────────────────────────────────────────

export const getUsageHistory = (
  pedestalId: number,
  resource: UsageResource,
  socketId: number,
  month?: string,
) =>
  api.get<UsageRow[]>(`/pedestals/${pedestalId}/usage/history`, {
    params: { resource, socket_id: socketId, ...(month ? { month } : {}) },
  }).then((r) => r.data)

export const listUsageReports = (pedestalId: number) =>
  api.get<ReportMeta[]>(`/pedestals/${pedestalId}/usage/reports`).then((r) => r.data)

/** Download the plain-text monthly report and trigger a browser save.
 *  Admin gets the admin file (customer #id); everyone else the STAFF file, which is generated
 *  on its own with no customer column — not a redacted copy (owner, 2026-10-14). */
export const downloadUsageReport = async (pedestalId: number, month: string, isAdmin: boolean) => {
  const r = isAdmin
    ? await api.get(`/pedestals/${pedestalId}/usage/reports/${month}`, { responseType: 'blob' })
    : await api.get(`/pedestals/${pedestalId}/usage/staff-reports/${month}`, { responseType: 'blob' })
  const url = URL.createObjectURL(r.data as Blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `pedestal-${pedestalId}_${month}${isAdmin ? '' : '.staff'}.txt`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

export const deleteUsageReport = (pedestalId: number, month: string) =>
  api.delete<{ deleted: boolean; pedestal_id: number; month: string }>(
    `/pedestals/${pedestalId}/usage/reports/${month}`,
  ).then((r) => r.data)
