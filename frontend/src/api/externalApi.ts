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

// ── Types ─────────────────────────────────────────────────────────────────────

export interface EndpointCatalogItem {
  id: string
  path: string
  method: string
  category: string
  allow_bidirectional: boolean
}

export interface EventCatalogItem {
  id: string
  name: string
  category: string
}

export interface Catalog {
  endpoints: EndpointCatalogItem[]
  events: EventCatalogItem[]
}

export interface EndpointEntry {
  id: string
  mode: 'monitor' | 'bidirectional'
}

export interface VerifyResult {
  endpoint_id: string
  path: string
  status_code: number | null
  ok: boolean | null
  note: string
}

export interface ExtApiConfig {
  id: number | null
  api_key: string | null
  allowed_endpoints: EndpointEntry[]
  webhook_url: string | null
  allowed_events: string[]
  active: boolean
  verified: boolean
  last_verified_at: string | null
  verification_results: VerifyResult[] | null
  created_at: string | null
  updated_at: string | null
}

export interface UpdateConfigPayload {
  allowed_endpoints: EndpointEntry[]
  webhook_url: string | null
  allowed_events: string[]
}

// ── API calls ─────────────────────────────────────────────────────────────────

export const getCatalog = (): Promise<Catalog> =>
  api.get<Catalog>('/admin/ext-api/catalog').then((r) => r.data)

export const getConfig = (): Promise<ExtApiConfig> =>
  api.get<ExtApiConfig>('/admin/ext-api/config').then((r) => r.data)

export const updateConfig = (data: UpdateConfigPayload): Promise<ExtApiConfig> =>
  api.put<ExtApiConfig>('/admin/ext-api/config', data).then((r) => r.data)

export const rotateKey = (): Promise<{ api_key: string }> =>
  api.post<{ api_key: string }>('/admin/ext-api/config/rotate-key').then((r) => r.data)

export const verifyConfig = (): Promise<{ verified: boolean; results: VerifyResult[] }> =>
  api
    .post<{ verified: boolean; results: VerifyResult[] }>('/admin/ext-api/config/verify')
    .then((r) => r.data)

export const activateConfig = (): Promise<{ active: boolean }> =>
  api.post<{ active: boolean }>('/admin/ext-api/config/activate').then((r) => r.data)

export const deactivateConfig = (): Promise<{ active: boolean }> =>
  api.post<{ active: boolean }>('/admin/ext-api/config/deactivate').then((r) => r.data)
