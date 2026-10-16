import axios from 'axios'
import { useAuthStore } from '../store/authStore'

/**
 * Guard (spec §5.5). `/status` is any role — the state and its sentence, no picture. Everything
 * that shows or judges what guard saw, and every command, is ADMIN ONLY in the API too
 * (owner, 2026-10-16): the page hides it AND the server refuses it.
 */
const api = axios.create({ baseURL: '/api/guard' })

api.interceptors.request.use((config) => {
  const token = useAuthStore.getState().token
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

export interface GuardCamera {
  camera_id: number
  pedestal_id: number
  /** The same words /marina shows for this state (§5.5.1; TC-GU-15). */
  sentence: string
  sentence_code: 'not_answering' | 'on' | 'off' | 'paused'
  desired_state: string
  state: string
  reason: string | null
  auto_resumes: { used: number; max: number } | null
}

export interface GuardPersonEvent {
  kind: 'person'
  id: number
  camera_id: number
  pedestal_id: number | null
  at_utc: string
  label: 'correct' | 'false_alarm' | null
  has_frame: boolean
  has_video: boolean
  video_skipped: boolean
  video_skip_reason: string | null
}

export interface GuardStateRow {
  kind: 'paused_cpu' | 'auto_resumed'
  id: number
  camera_id: number
  at_utc: string
  reason: string | null
}

export type GuardListRow = GuardPersonEvent | GuardStateRow

export const getGuardStatus = () =>
  api.get<{ marina_id: string; cameras: GuardCamera[] }>('/status').then((r) => r.data)

export const armGuard = (cameraId: number) => api.post(`/${cameraId}/enable`)
export const switchOffGuard = (cameraId: number) => api.post(`/${cameraId}/disable`)

export const getGuardEvents = (cameraId: number, offset: number, limit = 50) =>
  api.get<{ total: number; limit: number; offset: number; events: GuardListRow[] }>(
    '/events', { params: { camera_id: cameraId, offset, limit } },
  ).then((r) => r.data)

export const labelGuardEvent = (eventId: number, label: 'correct' | 'false_alarm') =>
  api.post(`/events/${eventId}/label`, { label })

/** The clip as a blob URL: a <video src> cannot carry the Authorization header. */
export async function fetchGuardVideo(eventId: number): Promise<
  { ok: true; url: string } | { ok: false; status: number; reason: string | null }
> {
  try {
    const r = await api.get(`/events/${eventId}/video`, { responseType: 'blob' })
    return { ok: true, url: URL.createObjectURL(r.data as Blob) }
  } catch (e) {
    const err = e as { response?: { status?: number; data?: unknown } }
    let reason: string | null = null
    const data = err.response?.data
    if (data instanceof Blob) {
      try {
        const body = JSON.parse(await data.text())
        reason = body?.detail?.reason ?? null
      } catch {
        reason = null
      }
    }
    return { ok: false, status: err.response?.status ?? 0, reason }
  }
}
