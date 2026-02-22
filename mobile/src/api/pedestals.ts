import { apiClient } from './client'

export interface PedestalStatus {
  id: number
  name: string
  location: string | null
  occupied_sockets: number[]
  water_occupied: boolean
}

export const getPedestalStatus = () =>
  apiClient.get<PedestalStatus[]>('/api/customer/sessions/pedestal-status').then((r) => r.data)
