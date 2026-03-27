import { useEffect, useRef } from 'react'
import { Platform, Alert } from 'react-native'
import { useAuthStore } from '../store/authStore'
import { useSessionStore } from '../store/sessionStore'

function resolveWsUrl(): string {
  if (Platform.OS === 'web' && typeof window !== 'undefined' && window.location.hostname === 'localhost') {
    return 'ws://localhost:8000/ws'
  }
  return process.env.EXPO_PUBLIC_WS_URL ?? 'ws://localhost:8000/ws'
}

const WS_BASE = resolveWsUrl()

export function useWebSocket(
  onChatMessage?: (msg: { customer_id: number; message: string; direction: string; created_at: string }) => void,
) {
  const { token } = useAuthStore()
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const attemptRef = useRef(0)
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
            if (msg.data.stopped_by === 'operator') {
              Alert.alert(
                'Session Stopped',
                'Your session was manually stopped by the marina operator.',
              )
            }
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
        attemptRef.current = 0
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
        const delay = Math.min(1000 * Math.pow(2, attemptRef.current), 30_000)
        attemptRef.current += 1
        reconnectRef.current = setTimeout(connect, delay)
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
