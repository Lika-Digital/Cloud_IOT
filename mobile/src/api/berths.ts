import { apiClient } from './client'

export interface BerthOut {
  id: number
  name: string
  pedestal_id: number | null
  status: 'free' | 'occupied' | 'reserved'
  detected_status: string
  video_source: string | null
  last_analyzed: string | null
}

export interface ReservationOut {
  id: number
  berth_id: number
  berth_name: string
  customer_id: number
  check_in_date: string
  check_out_date: string
  status: string
  notes: string | null
  created_at: string
}

export interface ReservePayload {
  berth_id: number
  check_in_date: string   // YYYY-MM-DD
  check_out_date: string  // YYYY-MM-DD
  notes?: string
}

export const getAvailableBerths = (checkIn: string, checkOut: string) =>
  apiClient.get<BerthOut[]>('/api/berths/availability', {
    params: { check_in: checkIn, check_out: checkOut },
  }).then((r) => r.data)

export const reserveBerth = (payload: ReservePayload) =>
  apiClient.post<ReservationOut>('/api/customer/berths/reserve', payload).then((r) => r.data)

export const getMyReservations = () =>
  apiClient.get<ReservationOut[]>('/api/customer/berths/mine').then((r) => r.data)

export const cancelReservation = (id: number) =>
  apiClient.delete(`/api/customer/berths/reservations/${id}`).then((r) => r.data)
