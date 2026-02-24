import { useEffect, useRef } from 'react'
import { useStore } from '../store'
import { useAuthStore } from '../store/authStore'

const WS_URL = `ws://${window.location.host}/ws`

export function useWebSocket() {
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const attemptRef = useRef(0)

  const {
    addSession,
    updateSession,
    setSocketLiveData,
    setWaterLiveData,
    setSensorReading,
    setOnline,
    setWsConnected,
    incrementUnreadChat,
    setLastChatMessage,
    incrementNewErrors,
    updateBerthOccupancy,
  } = useStore()
  const { role } = useAuthStore()

  // Request browser notification permission for admin users
  useEffect(() => {
    if (role === 'admin' && typeof Notification !== 'undefined' && Notification.permission === 'default') {
      Notification.requestPermission().catch(() => {})
    }
  }, [role])

  useEffect(() => {
    function connect() {
      const ws = new WebSocket(WS_URL)
      wsRef.current = ws

      ws.onopen = () => {
        setWsConnected(true)
        attemptRef.current = 0
        // Heartbeat ping every 20s
        const ping = setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) ws.send('ping')
        }, 20_000)
        ;(ws as any)._pingInterval = ping
      }

      ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data)
          handleMessage(msg)
        } catch {
          // pong or unknown text
        }
      }

      ws.onclose = () => {
        setWsConnected(false)
        clearInterval((ws as any)._pingInterval)
        const delay = Math.min(1000 * Math.pow(2, attemptRef.current), 30_000)
        attemptRef.current += 1
        reconnectTimer.current = setTimeout(connect, delay)
      }

      ws.onerror = () => {
        ws.close()
      }
    }

    function handleMessage(msg: { event: string; data: Record<string, unknown> }) {
      switch (msg.event) {
        case 'session_created': {
          addSession({
            id: msg.data.session_id as number,
            pedestal_id: msg.data.pedestal_id as number,
            socket_id: msg.data.socket_id as number | null,
            type: msg.data.type as 'electricity' | 'water',
            status: msg.data.status as 'pending',
            started_at: msg.data.started_at as string,
            ended_at: null,
            energy_kwh: null,
            water_liters: null,
            customer_id: (msg.data.customer_id as number | null) ?? null,
            customer_name: (msg.data.customer_name as string | null) ?? null,
            deny_reason: null,
          })
          // Browser push notification for operators
          if (role === 'admin' && typeof Notification !== 'undefined' && Notification.permission === 'granted') {
            const customerName = (msg.data.customer_name as string | null) ?? 'A customer'
            const sessionType = msg.data.type as string
            const pedestalId = msg.data.pedestal_id as number
            new Notification('New Pending Session', {
              body: `${customerName} requested ${sessionType} on Pedestal ${pedestalId}`,
              icon: '/vite.svg',
            })
          }
          break
        }
        case 'session_updated': {
          updateSession({
            id: msg.data.session_id as number,
            status: msg.data.status as 'active' | 'denied',
            socket_id: msg.data.socket_id as number | null,
            type: msg.data.type as 'electricity' | 'water',
            customer_id: (msg.data.customer_id as number | null) ?? null,
            deny_reason: (msg.data.deny_reason as string | null) ?? null,
          })
          break
        }
        case 'session_completed': {
          updateSession({
            id: msg.data.session_id as number,
            status: 'completed',
            energy_kwh: msg.data.energy_kwh as number | null,
            water_liters: msg.data.water_liters as number | null,
          })
          break
        }
        case 'power_reading': {
          const socketId = msg.data.socket_id as number
          setSocketLiveData(socketId, {
            watts: msg.data.watts as number,
            kwh_total: msg.data.kwh_total as number,
            lastUpdated: msg.data.timestamp as string,
          })
          break
        }
        case 'water_reading': {
          setWaterLiveData({
            lpm: msg.data.lpm as number,
            total_liters: msg.data.total_liters as number,
            lastUpdated: msg.data.timestamp as string,
          })
          break
        }
        case 'temperature_reading': {
          setSensorReading('temperature', msg.data.pedestal_id as number, {
            value: msg.data.value as number,
            alarm: msg.data.alarm as boolean,
            timestamp: msg.data.timestamp as string,
          })
          break
        }
        case 'moisture_reading': {
          setSensorReading('moisture', msg.data.pedestal_id as number, {
            value: msg.data.value as number,
            alarm: msg.data.alarm as boolean,
            timestamp: msg.data.timestamp as string,
          })
          break
        }
        case 'heartbeat': {
          setOnline(msg.data.online as boolean)
          break
        }
        case 'chat_message': {
          const direction = msg.data.direction as string
          if (role === 'admin' && direction === 'from_customer') {
            incrementUnreadChat()
          }
          // Forward to store so open ChatPanel can append it in real-time
          setLastChatMessage({
            customer_id: msg.data.customer_id as number,
            message: msg.data.message as string,
            direction,
            created_at: msg.data.created_at as string,
          })
          break
        }
        case 'error_logged': {
          // Only count errors/warnings for the nav badge (admins only)
          if (role === 'admin') {
            const level = msg.data.level as string
            if (level === 'error' || level === 'warning') {
              incrementNewErrors()
            }
          }
          break
        }
        case 'berth_occupancy_updated': {
          const berths = msg.data.berths as import('../store').BerthStatus[]
          updateBerthOccupancy(berths)
          break
        }
      }
    }

    connect()

    return () => {
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current)
      wsRef.current?.close()
    }
  }, [role])
}
