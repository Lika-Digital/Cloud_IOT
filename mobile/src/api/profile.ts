import { apiClient } from './client'

export interface ProfileUpdate {
  name?: string
  ship_name?: string
}

export const updateProfile = (data: ProfileUpdate) =>
  apiClient.patch('/api/customer/auth/profile', data).then((r) => r.data)

export const registerPushToken = (token: string) =>
  apiClient.post('/api/customer/auth/push-token', { token }).then((r) => r.data)
