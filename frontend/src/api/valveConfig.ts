import axios from 'axios'
import { useAuthStore } from '../store/authStore'

// v3.9 — typed client for per-valve auto-activation config (V1, V2).
// Matches the pattern in pedestalConfig.ts / breakers.ts — own axios
// instance + Bearer injector + 401-redirect interceptor.

const api = axios.create({ baseURL: '/api' })

api.interceptors.request.use((config) => {
  const token = useAuthStore.getState().token
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

api.interceptors.response.use(
  (r) => r,
  (error) => {
    if (error.response?.status === 401) {
      useAuthStore.getState().logout()
      window.location.href = '/login'
    }
    return Promise.reject(error)
  },
)

export interface ValveConfigRow {
  valve_id: number
  auto_activate: boolean
}

export const getValveConfigs = (pedestalId: number) =>
  api.get<ValveConfigRow[]>(`/pedestals/${pedestalId}/valves/config`).then((r) => r.data)

export const setValveConfig = (pedestalId: number, valveId: number, autoActivate: boolean) =>
  api.patch<ValveConfigRow>(
    `/pedestals/${pedestalId}/valves/${valveId}/config`,
    { auto_activate: autoActivate },
  ).then((r) => r.data)
