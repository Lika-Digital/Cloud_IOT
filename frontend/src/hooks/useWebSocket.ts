import { useEffect, useRef } from 'react'
import { useStore } from '../store'

const WS_URL = `ws://${window.location.host}/ws`
const RECONNECT_DELAY_MS = 3000

export function useWebSocket() {
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const {
    addSession,
    updateSession,
    setSocketLiveData,
    setWaterLiveData,
    setSensorReading,
    setOnline,
    setWsConnected,
  } = useStore()

  useEffect(() => {
    function connect() {
      const ws = new WebSocket(WS_URL)
      wsRef.current = ws

      ws.onopen = () => {
        setWsConnected(true)
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
        reconnectTimer.current = setTimeout(connect, RECONNECT_DELAY_MS)
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
          })
          break
        }
        case 'session_updated': {
          updateSession({
            id: msg.data.session_id as number,
            status: msg.data.status as 'active' | 'denied',
            socket_id: msg.data.socket_id as number | null,
            type: msg.data.type as 'electricity' | 'water',
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
      }
    }

    connect()

    return () => {
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current)
      wsRef.current?.close()
    }
  }, [])
}
