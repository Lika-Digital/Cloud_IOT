import { useState, useEffect, useRef } from 'react'
import { getChatMessages, sendOperatorReply, markChatRead, type ChatMessage } from '../../api/billing'
import { useStore } from '../../store'

interface ChatPanelProps {
  customerId: number
  customerName: string | null
  customerEmail: string
  onClose: () => void
}

export default function ChatPanel({ customerId, customerName, customerEmail, onClose }: ChatPanelProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [reply, setReply] = useState('')
  const [sending, setSending] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)
  const { lastChatMessage } = useStore()

  // Initial load
  useEffect(() => {
    getChatMessages(customerId).then((msgs) => {
      setMessages(msgs)
      markChatRead(customerId).catch(() => {})
    }).catch(() => {})
  }, [customerId])

  // Real-time: append incoming customer messages from WebSocket
  useEffect(() => {
    if (!lastChatMessage) return
    if (lastChatMessage.customer_id !== customerId) return
    // Only append from_customer — operator messages are added locally via sendOperatorReply
    if (lastChatMessage.direction !== 'from_customer') return

    setMessages((prev) => {
      // Deduplicate by created_at + message text to guard against double delivery
      const alreadyPresent = prev.some(
        (m) => m.created_at === lastChatMessage.created_at && m.message === lastChatMessage.message
      )
      if (alreadyPresent) return prev
      return [...prev, {
        id: Date.now(),
        customer_id: lastChatMessage.customer_id,
        message: lastChatMessage.message,
        direction: lastChatMessage.direction as ChatMessage['direction'],
        created_at: lastChatMessage.created_at,
        read_at: null,
      }]
    })
  }, [lastChatMessage, customerId])

  // Auto-scroll on new messages
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const handleSend = async () => {
    const text = reply.trim()
    if (!text) return
    setSending(true)
    try {
      const msg = await sendOperatorReply(customerId, text)
      setMessages((prev) => [...prev, msg])
      setReply('')
    } catch {
      // Message failed to send; input stays populated so operator can retry
    } finally {
      setSending(false)
    }
  }

  const displayName = customerName?.trim() || customerEmail

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
      <div className="bg-gray-900 border border-gray-700 rounded-xl w-full max-w-lg shadow-2xl flex flex-col" style={{ height: 520 }}>
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b border-gray-700">
          <div>
            <h3 className="text-white font-bold">{displayName}</h3>
            {customerName?.trim() && (
              <p className="text-gray-500 text-xs">{customerEmail}</p>
            )}
          </div>
          <button onClick={onClose} className="text-gray-500 hover:text-gray-300 text-xl leading-none">✕</button>
        </div>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto p-4 space-y-3">
          {messages.length === 0 && (
            <p className="text-gray-500 text-sm text-center mt-8">No messages yet.</p>
          )}
          {messages.map((m) => (
            <div key={m.id} className={`flex ${m.direction === 'from_operator' ? 'justify-end' : 'justify-start'}`}>
              <div className={`max-w-xs px-3 py-2 rounded-xl text-sm ${
                m.direction === 'from_operator'
                  ? 'bg-blue-600 text-white'
                  : 'bg-gray-700 text-gray-200'
              }`}>
                <p>{m.message}</p>
                <p className="text-xs opacity-60 mt-1">{new Date(m.created_at).toLocaleTimeString()}</p>
              </div>
            </div>
          ))}
          <div ref={bottomRef} />
        </div>

        {/* Input */}
        <div className="p-4 border-t border-gray-700 flex gap-2">
          <input
            className="flex-1 bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-gray-200 text-sm focus:outline-none focus:border-blue-500"
            placeholder="Type a reply…"
            value={reply}
            onChange={(e) => setReply(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend() } }}
          />
          <button
            className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50 transition-colors"
            onClick={handleSend}
            disabled={sending || !reply.trim()}
          >
            Send
          </button>
        </div>
      </div>
    </div>
  )
}
