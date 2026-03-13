import axios from 'axios'
import { Platform } from 'react-native'
import { getToken } from '../store/authStore'

// On web running in the browser on the same machine as the backend, always use
// localhost — the LAN IP in .env is only needed for physical devices on Wi-Fi.
function resolveApiUrl(): string {
  if (Platform.OS === 'web' && typeof window !== 'undefined' && window.location.hostname === 'localhost') {
    return 'http://localhost:8000'
  }
  return process.env.EXPO_PUBLIC_API_URL ?? 'http://localhost:8000'
}

const BASE_URL = resolveApiUrl()

export const apiClient = axios.create({ baseURL: BASE_URL, timeout: 10_000 })

apiClient.interceptors.request.use((config) => {
  const token = getToken()
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})
