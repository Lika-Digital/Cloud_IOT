import { apiClient } from './client'

export interface ChatMessage {
  id: number
  customer_id: number
  message: string
  direction: 'from_customer' | 'from_operator'
  created_at: string
  read_at: string | null
}

export const sendMessage = (message: string) =>
  apiClient.post<ChatMessage>('/api/chat/send', { message }).then((r) => r.data)

export const getMyMessages = () =>
  apiClient.get<ChatMessage[]>('/api/chat/my-messages').then((r) => r.data)
