import { useEffect, useRef } from 'react'
import { useStore } from '../store'
import { useAuthStore } from '../store/authStore'

const WS_URL = `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}/ws`

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
    updatePedestalHealthEntry,
    addPendingSocket,
    removePendingSocket,
    setMarinaDoorState,
    setHwAlarmLevel,
    setOptaSocketState,
    setOptaWaterState,
    setOptaStatusInfo,
    addOptaEvent,
    addOptaAck,
    setSocketComputedState,
    setSocketAutoSkipReason,
    clearSocketAutoSkipReason,
    addToast,
    setBreakerState,
    addBreakerAlarm,
    addValveFlowWarning,
    setHardwareConfig,
    setLoadState,
    addLoadAlarm,
    clearLoadAlarm,
    addAutoStopAlarm,
    acknowledgeAutoStopAlarm,
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
        case 'socket_pending': {
          addPendingSocket(msg.data.pedestal_id as number, msg.data.socket_id as number)
          break
        }
        case 'socket_rejected': {
          removePendingSocket(msg.data.pedestal_id as number, msg.data.socket_id as number)
          break
        }
        case 'user_plugged_in': {
          // Informational: firmware reports a physical plug-in. Treat the
          // socket as connected so legacy ZoneButton logic still flips amber.
          // The canonical signal is `socket_state_changed`; this case is kept
          // for backwards-compat with older event consumers.
          const pedId = msg.data.pedestal_id as number
          const sockId = msg.data.socket_id as number | null | undefined
          if (sockId != null) {
            addPendingSocket(pedId, sockId)
          }
          break
        }
        case 'socket_state_changed': {
          // Unified state broadcast: idle | pending | active | fault.
          // Powers the yellow pending indicator in Control Center + the
          // pedestal picture zone circle.
          const pedId = msg.data.pedestal_id as number
          const sockId = msg.data.socket_id as number | null | undefined
          const state = msg.data.state as 'idle' | 'pending' | 'active' | 'fault' | undefined
          if (sockId != null && state) {
            setSocketComputedState(pedId, sockId, state)
            // Any state transition other than pending also clears the
            // transient "auto-activate skipped" warning — it only makes
            // sense while the socket is still sitting pending.
            if (state !== 'pending') {
              clearSocketAutoSkipReason(pedId, sockId)
            }
            // Keep pendingSockets in sync so ZoneButton logic (which already
            // reads pendingSockets for amber) produces matching visuals.
            if (state === 'pending') addPendingSocket(pedId, sockId)
            else removePendingSocket(pedId, sockId)
          }
          break
        }
        case 'pedestal_registered': {
          // v3.7 — a cabinet has just been auto-discovered (is_new=true)
          // or is re-announcing itself after a reconnect (is_new=false,
          // throttled to 60s per pedestal). Only the first-contact case
          // raises an operator-facing toast.
          if (msg.data.is_new === true) {
            const name = (msg.data.name as string | undefined) ?? 'Unknown'
            const cab = (msg.data.cabinet_id as string | undefined) ?? ''
            const pid = msg.data.pedestal_id as number | undefined
            addToast({
              id: `pedestal-registered-${cab}`,
              message: `New pedestal discovered: ${name} (${cab})`,
              variant: 'info',
              actionLabel: 'View',
              actionHref: pid ? `/dashboard?pedestal=${pid}` : '/dashboard',
            })
          }
          break
        }
        case 'socket_auto_activate_skipped': {
          // v3.5 — backend rejected an auto-activation. Show the amber warning
          // on the socket card; it auto-clears after 30 s or when the next
          // `socket_state_changed` transitions away from pending.
          const pedId = msg.data.pedestal_id as number
          const sockId = msg.data.socket_id as number | null | undefined
          const reason = msg.data.reason as string | undefined
          if (sockId != null && reason) {
            setSocketAutoSkipReason(pedId, sockId, reason)
            setTimeout(() => clearSocketAutoSkipReason(pedId, sockId), 30_000)
          }
          break
        }
        case 'session_created': {
          // When a session becomes active, clear the socket-level pending flag
          if (msg.data.status === 'active') {
            removePendingSocket(msg.data.pedestal_id as number, msg.data.socket_id as number)
          }
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
        case 'pedestal_health_updated': {
          const pedestalId = msg.data.pedestal_id as number
          updatePedestalHealthEntry(pedestalId, {
            opta_connected: msg.data.opta_connected as boolean | undefined,
            last_heartbeat: msg.data.last_heartbeat as string | null | undefined,
            camera_reachable: msg.data.camera_reachable as boolean | undefined,
            last_camera_check: msg.data.last_camera_check as string | null | undefined,
          } as Partial<import('../store').PedestalHealth>)
          break
        }
        case 'marina_door': {
          const pedestalId = msg.data.pedestal_id as number
          const door = msg.data.door as 'open' | 'closed'
          setMarinaDoorState(pedestalId, door)
          if (role === 'admin' && door === 'open') {
            const cabinetId = msg.data.cabinet_id as string
            if (typeof Notification !== 'undefined' && Notification.permission === 'granted') {
              new Notification('Cabinet Door Open', {
                body: `Cabinet ${cabinetId} door opened`,
                icon: '/vite.svg',
              })
            }
          }
          break
        }
        case 'opta_socket_status': {
          const pedestalId = msg.data.pedestal_id as number
          const socketName = msg.data.socket_name as string
          setOptaSocketState(`${pedestalId}-${socketName}`, {
            pedestal_id: pedestalId,
            socket_name: socketName,
            state: msg.data.state as string,
            hw_status: msg.data.hw_status as string,
            session: msg.data.session,
            ts: msg.data.ts as number | null,
            timestamp: msg.data.timestamp as string,
          })
          break
        }
        case 'opta_water_status': {
          const pedestalId = msg.data.pedestal_id as number
          const valveName = msg.data.valve_name as string
          setOptaWaterState(`${pedestalId}-${valveName}`, {
            pedestal_id: pedestalId,
            valve_name: valveName,
            state: msg.data.state as string,
            hw_status: msg.data.hw_status as string,
            total_l: msg.data.total_l as number,
            session_l: msg.data.session_l as number,
            ts: msg.data.ts as number | null,
            timestamp: msg.data.timestamp as string,
          })
          break
        }
        case 'opta_status': {
          const pedestalId = msg.data.pedestal_id as number
          setOptaStatusInfo(pedestalId, {
            cabinet_id: msg.data.cabinet_id as string,
            seq: msg.data.seq as number,
            uptime_ms: msg.data.uptime_ms as number,
            door: msg.data.door as string | undefined,
            timestamp: msg.data.timestamp as string,
          })
          // Heartbeat carries door field — sync marinaDoorState so the
          // pedestal view always has current state regardless of when the
          // browser connected (retained door/state message may have been
          // broadcast before the WS client connected)
          if (msg.data.door) {
            setMarinaDoorState(pedestalId, msg.data.door as 'open' | 'closed')
          }
          break
        }
        case 'marina_ack': {
          const pedestalId = msg.data.pedestal_id as number
          if (pedestalId) {
            addOptaAck(pedestalId, {
              cabinet_id: msg.data.cabinet_id as string,
              payload: msg.data.payload,
              timestamp: msg.data.timestamp as string,
            })
          }
          break
        }
        case 'marina_event': {
          const pedestalId = msg.data.pedestal_id as number
          if (pedestalId) {
            updatePedestalHealthEntry(pedestalId, {})
            addOptaEvent(pedestalId, {
              payload: msg.data.payload,
              timestamp: msg.data.timestamp as string,
            })
          }
          break
        }
        case 'hardware_alarm': {
          if (role === 'admin') {
            const level = msg.data.alarm_level as 'warning' | 'critical'
            setHwAlarmLevel(level)
          }
          break
        }
        case 'breaker_state_changed': {
          // v3.8 — merge patch into the per-socket breaker state. Undefined
          // fields are preserved (matches the backend "no-overwrite-with-null"
          // rule in mqtt_handlers._handle_opta_breaker_status).
          const d = msg.data
          if (typeof d?.pedestal_id === 'number' && typeof d?.socket_id === 'number') {
            const patch: Record<string, unknown> = {}
            if (d.breaker_state !== undefined) patch.breaker_state = d.breaker_state
            if (d.trip_cause !== undefined) patch.trip_cause = d.trip_cause
            if (d.breaker_type !== undefined) patch.breaker_type = d.breaker_type
            if (d.breaker_rating !== undefined) patch.breaker_rating = d.breaker_rating
            if (d.breaker_poles !== undefined) patch.breaker_poles = d.breaker_poles
            if (d.breaker_rcd !== undefined) patch.breaker_rcd = d.breaker_rcd
            if (d.breaker_rcd_sensitivity !== undefined) patch.breaker_rcd_sensitivity = d.breaker_rcd_sensitivity
            setBreakerState(d.pedestal_id, d.socket_id, patch)
            // When the socket transitions back to closed, auto-clear any
            // outstanding alarm flag for it so the banner disappears without
            // needing an acknowledgement.
            if (d.breaker_state === 'closed') {
              useStore.getState().clearBreakerAlarm(`${d.pedestal_id}-${d.socket_id}`)
            }
          }
          break
        }
        case 'breaker_alarm': {
          // v3.8 — persistent alarm banner + admin Browser Notification per D9.
          const d = msg.data
          if (typeof d?.pedestal_id === 'number' && typeof d?.socket_id === 'number') {
            addBreakerAlarm(`${d.pedestal_id}-${d.socket_id}`)
            if (role === 'admin'
                && typeof Notification !== 'undefined'
                && Notification.permission === 'granted') {
              const cause = d.trip_cause ?? 'unknown'
              new Notification('Breaker Tripped', {
                body: `Pedestal ${d.pedestal_id} socket Q${d.socket_id} — cause: ${cause}`,
                icon: '/vite.svg',
              })
            }
          }
          break
        }
        case 'led_changed': {
          // v3.10 — LED state changed (manual OR scheduled). Skip the toast
          // for manual changes since the admin who clicked already saw the
          // local feedback toast — only surface scheduler-driven events to
          // confirm the schedule fired.
          const d = msg.data
          if (role === 'admin' && d?.source === 'scheduler') {
            const color = typeof d.color === 'string' ? d.color : 'led'
            const state = d.state === 'off' ? 'OFF' : 'ON'
            addToast({
              message: `Pedestal ${d.pedestal_id}: LED ${color} → ${state} (scheduled)`,
              variant: 'info',
            })
          }
          break
        }
        case 'hardware_config_updated': {
          // v3.11 — broadcast contains parsed sockets[] from opta/config/hardware.
          // We patch the store entry per-socket so the SocketLoadMeterPanel
          // refreshes its Hardware Info section without a page reload.
          const d = msg.data
          if (typeof d?.pedestal_id === 'number' && Array.isArray(d.sockets)) {
            for (const s of d.sockets) {
              if (typeof s?.socket_id === 'number') {
                setHardwareConfig(d.pedestal_id, s.socket_id, {
                  meter_type: s.meter_type ?? null,
                  phases: s.phases ?? null,
                  rated_amps: s.rated_amps ?? null,
                  modbus_address: s.modbus_address ?? null,
                  hw_config_received_at: s.hw_config_received_at ?? null,
                })
              }
            }
          }
          break
        }
        case 'meter_telemetry_received': {
          // v3.11 — low-volume per-tick update. Refreshes load bar without
          // hitting the API. Single-phase rows leave L1/L2/L3 untouched.
          const d = msg.data
          if (typeof d?.pedestal_id === 'number' && typeof d?.socket_id === 'number') {
            const patch: Record<string, unknown> = {
              current_amps: d.current_amps ?? null,
              load_pct: d.load_pct ?? null,
              load_status: d.load_status ?? 'unknown',
            }
            if (d.current_l1 !== undefined) patch.current_l1 = d.current_l1
            if (d.current_l2 !== undefined) patch.current_l2 = d.current_l2
            if (d.current_l3 !== undefined) patch.current_l3 = d.current_l3
            setLoadState(d.pedestal_id, d.socket_id, patch as Parameters<typeof setLoadState>[2])
          }
          break
        }
        case 'meter_load_warning': {
          const d = msg.data
          if (typeof d?.pedestal_id === 'number' && typeof d?.socket_id === 'number') {
            addLoadAlarm('warning', `${d.pedestal_id}-${d.socket_id}`)
          }
          break
        }
        case 'meter_load_critical': {
          // v3.11 D8 — admin-only Browser Notification. Mirrors breaker_alarm.
          const d = msg.data
          if (typeof d?.pedestal_id === 'number' && typeof d?.socket_id === 'number') {
            addLoadAlarm('critical', `${d.pedestal_id}-${d.socket_id}`)
            if (role === 'admin'
                && typeof Notification !== 'undefined'
                && Notification.permission === 'granted') {
              const loadPct = typeof d.load_pct === 'number' ? `${d.load_pct.toFixed(0)}%` : 'over critical'
              new Notification('Critical Load — act now', {
                body: `Pedestal ${d.pedestal_id} socket Q${d.socket_id} at ${loadPct} of rated current`,
                icon: '/vite.svg',
              })
            }
          }
          break
        }
        case 'meter_load_resolved': {
          const d = msg.data
          if (typeof d?.pedestal_id === 'number' && typeof d?.socket_id === 'number') {
            clearLoadAlarm(`${d.pedestal_id}-${d.socket_id}`)
          }
          break
        }
        case 'meter_load_auto_stop': {
          // v3.12 — 90% threshold tripped an automatic socket stop. The
          // backend has already published the stop command and ended the
          // session; this handler updates the dashboard latch + collects
          // alarm data for the System Health panel and fires an admin
          // Browser Notification (highest severity).
          const d = msg.data
          if (typeof d?.pedestal_id === 'number' && typeof d?.socket_id === 'number') {
            const key = `${d.pedestal_id}-${d.socket_id}`
            addAutoStopAlarm({
              key,
              pedestal_id: d.pedestal_id,
              socket_id: d.socket_id,
              current_amps: typeof d.current_amps === 'number' ? d.current_amps : null,
              rated_amps: typeof d.rated_amps === 'number' ? d.rated_amps : null,
              load_pct: typeof d.load_pct === 'number' ? d.load_pct : null,
              session_id: typeof d.session_id === 'number' ? d.session_id : null,
              triggered_at: (typeof d.timestamp === 'string' ? d.timestamp : new Date().toISOString()),
            })
            if (role === 'admin'
                && typeof Notification !== 'undefined'
                && Notification.permission === 'granted') {
              const loadPct = typeof d.load_pct === 'number' ? `${d.load_pct.toFixed(0)}%` : 'over 90%'
              new Notification('⚡ Socket auto-stopped — overload protection', {
                body: `Pedestal ${d.pedestal_id} socket Q${d.socket_id} stopped at ${loadPct} of rated capacity`,
                icon: '/vite.svg',
              })
            }
          }
          break
        }
        case 'meter_load_auto_stop_acknowledged': {
          // v3.12 — operator (or ERP) cleared the latch. Drop the alarm
          // from the System Health panel and stop blocking the socket's
          // Activate button in Control Center.
          const d = msg.data
          if (typeof d?.pedestal_id === 'number' && typeof d?.socket_id === 'number') {
            acknowledgeAutoStopAlarm(d.pedestal_id, d.socket_id)
          }
          break
        }
        case 'valve_flow_warning': {
          // v3.9 — post-diagnostic auto-open reported zero flow after 30 s.
          // Informational only; valve remains open. Shows a banner and fires
          // a Browser Notification for admin so an operator on another page
          // still sees it.
          const d = msg.data
          if (typeof d?.pedestal_id === 'number' && typeof d?.valve_id === 'number') {
            addValveFlowWarning(`${d.pedestal_id}-${d.valve_id}`)
            if (role === 'admin'
                && typeof Notification !== 'undefined'
                && Notification.permission === 'granted') {
              const body: string = (typeof d.message === 'string' && d.message)
                ? d.message
                : `Valve V${d.valve_id} on pedestal ${d.pedestal_id} reports zero flow`
              new Notification('Valve zero-flow warning', {
                body,
                icon: '/vite.svg',
              })
            }
          }
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
