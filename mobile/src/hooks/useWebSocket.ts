import { useEffect, useRef } from 'react'
import { Platform, Alert } from 'react-native'
import { useAuthStore } from '../store/authStore'
import { useSessionStore, type IncomingChatMessage } from '../store/sessionStore'

function resolveWsUrl(): string {
  if (Platform.OS === 'web' && typeof window !== 'undefined' && window.location.hostname === 'localhost') {
    return 'ws://localhost:8000/ws'
  }
  return process.env.EXPO_PUBLIC_WS_URL ?? 'ws://localhost:8000/ws'
}

const WS_BASE = resolveWsUrl()

export function useWebSocket(
  // Was an inline type with `direction: string`, which is looser than both the store's
  // IncomingChatMessage and the API's ChatMessage. Two structurally-similar shapes for one
  // payload is how the mismatch got in; there is one now.
  onChatMessage?: (msg: IncomingChatMessage) => void,
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
      const { activeSession, setActiveSession, updateLivePower, updateLiveWater, clearLive,
              nfcPending, setNfcPending } =
        useSessionStore.getState()

      switch (msg.event) {
        case 'session_created': {
          // NFC flow: after our /api/nfc/scan, the socket activates on plug-in and
          // the backend broadcasts session_created with our nfc_user_id. Adopt it
          // so the Scan screen flips to "active" and live power_reading flows in.
          if (!nfcPending) break
          const nfcUser = (msg.data.nfc_user_id as string | null) ?? null
          const sock = (msg.data.socket_id as number | null) ?? null
          const sessionType = ((msg.data.type as string) === 'water' ? 'water' : 'electricity')
          const userMatches = nfcUser != null && nfcUser === nfcPending.user_id
          const outletMatches = nfcPending.outletNum == null || sock === nfcPending.outletNum
          // v3.43 — the type is part of the match, because the number is not enough. V1 and Q1
          // both broadcast socket_id=1, so someone who scanned the water tag would otherwise
          // adopt an electricity session on socket 1 and watch its kWh as if it were theirs.
          const typeMatches = sessionType === nfcPending.sessionType
          if (userMatches && outletMatches && typeMatches) {
            setActiveSession({
              id: msg.data.session_id as number,
              pedestal_id: msg.data.pedestal_id as number,
              socket_id: sock,
              type: sessionType,
              status: 'active',
              started_at: msg.data.started_at as string,
              customer_id: null,
            })
            clearLive()
            setNfcPending(null)
          }
          break
        }
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
          // The backend sends one of two values. Narrowed here rather than asserted as
          // `string`: an unexpected value becomes 'from_operator', which is the safe
          // default — a message shown as coming from the marina when it did not is a
          // display error, whereas the reverse would attribute the marina's words to the
          // customer in their own chat history.
          const raw = msg.data.direction
          const direction: IncomingChatMessage['direction'] =
            raw === 'from_customer' ? 'from_customer' : 'from_operator'
          onChatRef.current?.({
            customer_id: msg.data.customer_id as number,
            message: msg.data.message as string,
            direction,
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
