import { apiClient } from './client'

export interface ReviewSubmit {
  stars: number
  comment?: string
  session_id?: number
  service_order_id?: number
}

export interface Review {
  id: number
  customer_id: number
  stars: number
  comment: string | null
  session_id: number | null
  service_order_id: number | null
  created_at: string
}

export const submitReview = (data: ReviewSubmit): Promise<Review> =>
  apiClient.post('/api/customer/reviews/', data).then((r) => r.data)

export const getMyReviews = (): Promise<Review[]> =>
  apiClient.get('/api/customer/reviews/mine').then((r) => r.data)
