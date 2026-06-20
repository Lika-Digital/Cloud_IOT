import axios from 'axios'

const api = axios.create({ baseURL: '/api/auth' })

export interface TokenResponse {
  access_token: string
  token_type: string
  role: 'admin' | 'monitor_control' | 'monitor'
  email: string
}

export interface UserResponse {
  id: number
  email: string
  role: 'admin' | 'monitor_control' | 'monitor'
  is_active: boolean
  created_at: string
}

export interface UserCreate {
  email: string
  password: string
  role: 'admin' | 'monitor_control' | 'monitor'
}

import { useAuthStore } from '../store/authStore'

api.interceptors.request.use((config) => {
  const token = useAuthStore.getState().token
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

// v3.33 — two-step login, TOTP is the ONLY second factor (email OTP removed).
// /login returns a partial token + next-step flags; the caller then (in order)
// changes the password if required, then enrolls TOTP (first login) or enters
// the authenticator code.
export interface LoginResponse {
  partial_token: string
  must_change_password: boolean
  totp_enabled: boolean
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

export const authLogin = (email: string, password: string) =>
  api.post<LoginResponse>('/login', { email, password }).then((r) => r.data)

// First-login forced password change (authorized by the partial token).
export const authFirstPassword = (partial_token: string, new_password: string) =>
  api.post<{ ok: boolean; totp_enabled: boolean }>('/first-password', { partial_token, new_password }).then((r) => r.data)

// Second-factor completion for an existing TOTP user (partial token + code).
export const authTotpLogin = (partial_token: string, code: string) =>
  api.post<TokenResponse>('/totp/login', { partial_token, code }).then((r) => r.data)

// First-login TOTP enrolment: get a QR for a half-logged-in user, then confirm.
export const authTotpEnroll = (partial_token: string) =>
  api.post<TotpSetupResponse>('/totp/enroll', { partial_token }).then((r) => r.data)

export const authTotpEnrollVerify = (partial_token: string, code: string) =>
  api.post<TokenResponse>('/totp/enroll-verify', { partial_token, code }).then((r) => r.data)

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

export const authPatchUser = (id: number, data: { role?: 'admin' | 'monitor_control' | 'monitor'; is_active?: boolean }) =>
  api.patch<UserResponse>(`/users/${id}`, data).then((r) => r.data)

export const authDeleteUser = (id: number) =>
  api.delete(`/users/${id}`).then((r) => r.data)

// v3.33 — admin recovery: clear a user's TOTP so they re-enrol on next login.
export const authResetUser2fa = (id: number) =>
  api.post<UserResponse>(`/users/${id}/reset-2fa`).then((r) => r.data)
