import axios from 'axios'
import { getToken } from '../store/authStore'

const BASE_URL = process.env.EXPO_PUBLIC_API_URL ?? 'http://localhost:8000'

export const apiClient = axios.create({ baseURL: BASE_URL, timeout: 10_000 })

apiClient.interceptors.request.use((config) => {
  const token = getToken()
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})
