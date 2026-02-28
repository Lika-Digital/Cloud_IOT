import axios from 'axios'

const api = axios.create({ baseURL: '/api/auth' })

export interface TokenResponse {
  access_token: string
  token_type: string
  role: 'admin' | 'monitor'
  email: string
}

export interface UserResponse {
  id: number
  email: string
  role: 'admin' | 'monitor'
  is_active: boolean
  created_at: string
}

export interface UserCreate {
  email: string
  password: string
  role: 'admin' | 'monitor'
}

import { useAuthStore } from '../store/authStore'

api.interceptors.request.use((config) => {
  const token = useAuthStore.getState().token
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

export const authLogin = (email: string, password: string) =>
  api.post<{ message: string }>('/login', { email, password }).then((r) => r.data)

export const authVerifyOtp = (email: string, code: string) =>
  api.post<TokenResponse>('/verify-otp', { email, code }).then((r) => r.data)

export const authGetMe = () =>
  api.get<UserResponse>('/me').then((r) => r.data)

export const authChangePassword = (current_password: string, new_password: string) =>
  api.post('/change-password', { current_password, new_password }).then((r) => r.data)

export const authListUsers = () =>
  api.get<UserResponse[]>('/users').then((r) => r.data)

export const authCreateUser = (data: UserCreate) =>
  api.post<UserResponse>('/users', data).then((r) => r.data)

export const authDeleteUser = (id: number) =>
  api.delete(`/users/${id}`).then((r) => r.data)
