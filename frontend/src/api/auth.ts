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

// v3.19 — two-step partial-token login (2FA mandatory)
export interface PartialLoginResponse {
  totp_required: boolean
  otp_available: boolean
  partial_token: string
  otp_sent: boolean
  method: 'log' | 'email' | null
}

export interface TotpSetupResponse {
  qr_code: string            // base64 PNG
  secret: string
  provisioning_uri: string
  warning: string
}

export interface TotpStatusResponse {
  totp_enabled: boolean
  totp_verified_at: string | null
}

export interface OtpRequestResponse {
  otp_sent: boolean
  method: 'log' | 'email'
}

export const authLogin = (email: string, password: string) =>
  api.post<PartialLoginResponse>('/login', { email, password }).then((r) => r.data)

// Legacy email+code path — kept for back-compat (deprecated by /otp/login)
export const authVerifyOtp = (email: string, code: string) =>
  api.post<TokenResponse>('/verify-otp', { email, code }).then((r) => r.data)

// Second-factor completion (partial token)
export const authTotpLogin = (partial_token: string, code: string) =>
  api.post<TokenResponse>('/totp/login', { partial_token, code }).then((r) => r.data)

export const authOtpRequest = (partial_token: string) =>
  api.post<OtpRequestResponse>('/otp/request', { partial_token }).then((r) => r.data)

export const authOtpLogin = (partial_token: string, code: string) =>
  api.post<TokenResponse>('/otp/login', { partial_token, code }).then((r) => r.data)

// TOTP setup / management (uses the logged-in bearer token via the interceptor)
export const totpSetup = () =>
  api.post<TotpSetupResponse>('/totp/setup').then((r) => r.data)

export const totpVerifySetup = (code: string) =>
  api.post<TotpStatusResponse>('/totp/verify-setup', { code }).then((r) => r.data)

export const totpDisable = (password: string, code: string) =>
  api.post<TotpStatusResponse>('/totp/disable', { password, code }).then((r) => r.data)

export const totpStatus = () =>
  api.get<TotpStatusResponse>('/totp/status').then((r) => r.data)

export const authGetMe = () =>
  api.get<UserResponse>('/me').then((r) => r.data)

export const authChangePassword = (current_password: string, new_password: string) =>
  api.post('/change-password', { current_password, new_password }).then((r) => r.data)

export const authRegister = (email: string, password: string) =>
  api.post<{ message: string }>('/register', { email, password }).then((r) => r.data)

export const authListUsers = () =>
  api.get<UserResponse[]>('/users').then((r) => r.data)

export const authCreateUser = (data: UserCreate) =>
  api.post<UserResponse>('/users', data).then((r) => r.data)

export const authPatchUser = (id: number, data: { role?: 'admin' | 'monitor'; is_active?: boolean }) =>
  api.patch<UserResponse>(`/users/${id}`, data).then((r) => r.data)

export const authDeleteUser = (id: number) =>
  api.delete(`/users/${id}`).then((r) => r.data)
