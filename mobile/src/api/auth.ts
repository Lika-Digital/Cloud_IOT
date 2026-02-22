import { apiClient } from './client'

export interface RegisterBody {
  email: string
  password: string
  name?: string
  vat_number?: string
  ship_name?: string
  ship_registration?: string
}

export interface TokenResponse {
  access_token: string
  token_type: string
}

export interface CustomerProfile {
  id: number
  email: string
  name: string | null
  ship_name: string | null
  vat_number: string | null
  ship_registration: string | null
}

export const register = (body: RegisterBody) =>
  apiClient.post<TokenResponse>('/api/customer/auth/register', body).then((r) => r.data)

export const login = (email: string, password: string) =>
  apiClient.post<TokenResponse>('/api/customer/auth/login', { email, password }).then((r) => r.data)

export const getMe = () =>
  apiClient.get<CustomerProfile>('/api/customer/auth/me').then((r) => r.data)
