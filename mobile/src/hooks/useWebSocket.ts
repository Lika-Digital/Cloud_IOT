import { useEffect, useRef } from 'react'
import { useAuthStore } from '../store/authStore'
import { useSessionStore } from '../store/sessionStore'

const WS_BASE = process.env.EXPO_PUBLIC_WS_URL ?? 'ws://localhost:8000/ws'

export function useWebSocket(
  onChatMessage?: (msg: { customer_id: number; message: string; direction: string; created_at: string }) => void,
) {
  const { token } = useAuthStore()
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  // Keep a ref to the callback so the effect doesn't need to re-run when it changes
  const onChatRef = useRef(onChatMessage)
  useEffect(() => { onChatRef.current = onChatMessage }, [onChatMessage])

  useEffect(() => {
    if (!token) return

    function handleMessage(msg: { event: string; data: Record<string, unknown> }) {
      // Read FRESH state every time — avoids stale closure on activeSession
      const { activeSession, setActiveSession, updateLivePower, updateLiveWater, clearLive } =
        useSessionStore.getState()

      switch (msg.event) {
        case 'session_updated': {
          if (!activeSession || msg.data.session_id !== activeSession.id) break
          const status = msg.data.status as string
          if (status === 'active') {
            setActiveSession({ ...activeSession, status: 'active' })
          } else if (status === 'denied') {
            setActiveSession(null)
            clearLive()
          }
          break
        }
        case 'session_completed': {
          if (activeSession && msg.data.session_id === activeSession.id) {
            setActiveSession(null)
            clearLive()
          }
          break
        }
        case 'power_reading': {
          if (activeSession?.type === 'electricity' && msg.data.session_id === activeSession.id) {
            updateLivePower(msg.data.watts as number, msg.data.kwh_total as number)
          }
          break
        }
        case 'water_reading': {
          if (activeSession?.type === 'water' && msg.data.session_id === activeSession.id) {
            updateLiveWater(msg.data.lpm as number, msg.data.total_liters as number)
          }
          break
        }
        case 'chat_message': {
          onChatRef.current?.({
            customer_id: msg.data.customer_id as number,
            message: msg.data.message as string,
            direction: msg.data.direction as string,
            created_at: msg.data.created_at as string,
          })
          break
        }
      }
    }

    function connect() {
      const url = `${WS_BASE}?token=${token}`
      const ws = new WebSocket(url)
      wsRef.current = ws

      ws.onopen = () => {
        const ping = setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) ws.send('ping')
        }, 20_000)
        ;(ws as any)._ping = ping
      }

      ws.onmessage = (event) => {
        if (event.data === 'pong') return
        try {
          const msg = JSON.parse(event.data)
          handleMessage(msg)
        } catch {}
      }

      ws.onclose = () => {
        clearInterval((ws as any)._ping)
        reconnectRef.current = setTimeout(connect, 3000)
      }

      ws.onerror = () => ws.close()
    }

    connect()

    return () => {
      if (reconnectRef.current) clearTimeout(reconnectRef.current)
      wsRef.current?.close()
    }
  }, [token])
}
