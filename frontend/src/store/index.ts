import { create } from 'zustand'

// --- Types ---

export interface Pedestal {
  id: number
  name: string
  location: string | null
  ip_address: string | null
  camera_ip: string | null
  data_mode: 'synthetic' | 'real'
  initialized: boolean
  mobile_enabled: boolean
  ai_enabled: boolean
}

export interface SensorReading {
  value: number
  alarm: boolean
  timestamp: string
}

export interface Session {
  id: number
  pedestal_id: number
  socket_id: number | null
  type: 'electricity' | 'water'
  status: 'pending' | 'active' | 'completed' | 'denied'
  started_at: string
  ended_at: string | null
  energy_kwh: number | null
  water_liters: number | null
  customer_id: number | null
  customer_name?: string | null
  deny_reason: string | null
}

export interface PowerReading {
  pedestal_id: number
  socket_id: number
  session_id: number | null
  watts: number
  kwh_total: number
  timestamp: string
}

export interface WaterReading {
  pedestal_id: number
  session_id: number | null
  lpm: number
  total_liters: number
  timestamp: string
}

export interface SocketLiveData {
  watts: number
  kwh_total: number
  lastUpdated: string
}

export interface BerthStatus {
  id: number
  name: string
  status: 'free' | 'occupied' | 'reserved'
  detected_status: string
  pedestal_id: number | null
  video_source: string | null
  background_image: string | null
  last_analyzed: string | null
  // ML pipeline outputs
  occupied_bit: number
  match_ok_bit: number
  state_code: number          // 0=FREE  1=OCCUPIED_CORRECT  2=OCCUPIED_WRONG
  alarm: number
  match_score: number | null
  analysis_error: string | null
  // Camera info (enriched from pedestal config)
  camera_stream_url?: string | null
  camera_reachable?: boolean
  reference_image_count?: number
  berth_type?: 'transit' | 'yearly'
  // ML confidence
  confidence?: number
  // Re-ID embedding
  sample_embedding_path?: string | null
  sample_updated_at?: string | null
  // Detection zone
  zone_x1?: number
  zone_y1?: number
  zone_x2?: number
  zone_y2?: number
  use_detection_zone?: number
  // User-assigned berth number
  berth_number?: number | null
}

export interface PedestalHealth {
  opta_connected: boolean
  last_heartbeat: string | null
  camera_reachable: boolean
  last_camera_check: string | null
}

export interface OptaSocketState {
  pedestal_id: number
  socket_name: string  // Q1, Q2, Q3, Q4
  state: string        // idle, active, fault, blocked
  hw_status: string
  session: unknown
  ts: number | null
  timestamp: string
}

export interface OptaWaterState {
  pedestal_id: number
  valve_name: string   // V1, V2
  state: string        // idle, active, fault
  hw_status: string
  total_l: number
  session_l: number
  ts: number | null
  timestamp: string
}

export interface OptaStatusInfo {
  cabinet_id: string
  seq: number
  uptime_ms: number
  door?: string
  timestamp: string
}

export interface OptaLogEntry {
  cabinet_id?: string
  payload: unknown
  timestamp: string
}

// --- Store ---

interface AppStore {
  // Pedestal
  pedestals: Pedestal[]
  setPedestals: (pedestals: Pedestal[]) => void
  updatePedestal: (pedestal: Pedestal) => void

  // Sessions
  pendingSessions: Session[]
  activeSessions: Session[]
  setPendingSessions: (sessions: Session[]) => void
  setActiveSessions: (sessions: Session[]) => void
  addSession: (session: Session) => void
  updateSession: (session: Partial<Session> & { id: number }) => void
  removeSession: (id: number) => void

  // Live readings per socket
  socketLiveData: Record<number, SocketLiveData>
  setSocketLiveData: (socketId: number, data: SocketLiveData) => void
  waterLiveData: { lpm: number; total_liters: number; lastUpdated: string } | null
  setWaterLiveData: (data: { lpm: number; total_liters: number; lastUpdated: string }) => void

  // Sensor data per pedestal
  temperatureData: Record<number, SensorReading>
  moistureData: Record<number, SensorReading>
  setSensorReading: (type: 'temperature' | 'moisture', pedestalId: number, reading: SensorReading) => void

  // Heartbeat
  pedestalOnline: boolean
  setOnline: (online: boolean) => void

  // WS connection
  wsConnected: boolean
  setWsConnected: (v: boolean) => void

  // Selected pedestal for detail view
  selectedPedestalId: number | null
  setSelectedPedestalId: (id: number | null) => void

  // Socket-level pending events from MQTT (before any DB session exists)
  pendingSockets: Record<string, { pedestal_id: number; socket_id: number }>
  addPendingSocket: (pedestal_id: number, socket_id: number) => void
  removePendingSocket: (pedestal_id: number, socket_id: number) => void

  // Computed socket state from the unified backend `socket_state_changed` WS
  // event. Keyed by `${pedestal_id}-${socket_id}`; values: idle|pending|active|fault.
  // Reflects plug-inserted + session + firmware fault state as a single source
  // of truth for SocketCard / ZoneButton coloring.
  socketComputedStates: Record<string, 'idle' | 'pending' | 'active' | 'fault'>
  setSocketComputedState: (pedestal_id: number, socket_id: number, state: 'idle' | 'pending' | 'active' | 'fault') => void

  // v3.5 — per-socket auto-activation config, keyed by `${pedestal_id}-${socket_id}`.
  // Populated when the Control Center opens (`getSocketConfigs`) and by the PATCH
  // optimistic update. Consumed by SocketCard (AUTO badge, toggle state) and
  // ZoneButton tooltip.
  socketAutoActivate: Record<string, boolean>
  setSocketAutoActivate: (pedestal_id: number, socket_id: number, value: boolean) => void

  // v3.5 — transient "auto-activate skipped" warning per socket. Populated by
  // the `socket_auto_activate_skipped` WS event and auto-cleared after 30 s.
  socketAutoSkipReasons: Record<string, { reason: string; ts: number }>
  setSocketAutoSkipReason: (pedestal_id: number, socket_id: number, reason: string) => void
  clearSocketAutoSkipReason: (pedestal_id: number, socket_id: number) => void

  // Chat unread count
  unreadChatCount: number
  setUnreadChatCount: (count: number) => void
  incrementUnreadChat: () => void

  // Last incoming chat message — ChatPanel watches this for real-time updates
  lastChatMessage: { customer_id: number; message: string; direction: string; created_at: string } | null
  setLastChatMessage: (msg: { customer_id: number; message: string; direction: string; created_at: string }) => void

  // System health — new error count since last visit
  newErrorCount: number
  incrementNewErrors: () => void
  resetNewErrors: () => void

  // Hardware alarm level (for nav indicator and WS events)
  hwAlarmLevel: 'none' | 'warning' | 'critical'
  setHwAlarmLevel: (level: 'none' | 'warning' | 'critical') => void

  // Berth occupancy
  berthOccupancy: BerthStatus[]
  setBerthOccupancy: (berths: BerthStatus[]) => void
  updateBerthOccupancy: (berths: BerthStatus[]) => void

  // Pedestal health (opta / camera)
  pedestalHealth: Record<number, PedestalHealth>
  setPedestalHealth: (health: Record<number, PedestalHealth>) => void
  updatePedestalHealthEntry: (pedestalId: number, update: Partial<PedestalHealth>) => void

  // Marina cabinet door state per pedestal
  marinaDoorState: Record<number, 'open' | 'closed'>
  setMarinaDoorState: (pedestalId: number, state: 'open' | 'closed') => void

  // OPTA live state (keyed by `${pedestal_id}-${socket_name}`)
  optaSocketStates: Record<string, OptaSocketState>
  setOptaSocketState: (key: string, data: OptaSocketState) => void

  optaWaterStates: Record<string, OptaWaterState>
  setOptaWaterState: (key: string, data: OptaWaterState) => void

  // OPTA status info (heartbeat details) per pedestal
  optaStatusInfo: Record<number, OptaStatusInfo>
  setOptaStatusInfo: (pedestalId: number, info: OptaStatusInfo) => void

  // Rolling event log per pedestal (last 30 entries)
  optaEvents: Record<number, OptaLogEntry[]>
  addOptaEvent: (pedestalId: number, entry: OptaLogEntry) => void

  // Rolling ACK log per pedestal (last 30 entries)
  optaAcks: Record<number, OptaLogEntry[]>
  addOptaAck: (pedestalId: number, entry: OptaLogEntry) => void
}

export const useStore = create<AppStore>((set) => ({
  pedestals: [],
  setPedestals: (pedestals) => set({ pedestals }),
  updatePedestal: (pedestal) =>
    set((s) => ({
      pedestals: s.pedestals.map((p) => (p.id === pedestal.id ? pedestal : p)),
    })),

  pendingSessions: [],
  activeSessions: [],
  setPendingSessions: (sessions) => set({ pendingSessions: sessions }),
  setActiveSessions: (sessions) => set({ activeSessions: sessions }),

  addSession: (session) =>
    set((s) => {
      // Idempotency: ignore if already tracked in either list
      const alreadyExists =
        s.pendingSessions.some((sess) => sess.id === session.id) ||
        s.activeSessions.some((sess) => sess.id === session.id)
      if (alreadyExists) return {}

      if (session.status === 'pending') {
        return { pendingSessions: [...s.pendingSessions, session] }
      }
      if (session.status === 'active') {
        return { activeSessions: [...s.activeSessions, session] }
      }
      return {}
    }),

  updateSession: (update) =>
    set((s) => {
      const mergeSession = (sessions: Session[]) =>
        sessions.map((sess) =>
          sess.id === update.id ? { ...sess, ...update } : sess
        )

      let pendingSessions = mergeSession(s.pendingSessions)
      let activeSessions = mergeSession(s.activeSessions)

      // Move between lists based on new status
      if (update.status === 'active') {
        const session = s.pendingSessions.find((sess) => sess.id === update.id)
        if (session) {
          pendingSessions = s.pendingSessions.filter((sess) => sess.id !== update.id)
          activeSessions = [...s.activeSessions, { ...session, ...update } as Session]
        }
      } else if (update.status === 'denied' || update.status === 'completed') {
        pendingSessions = s.pendingSessions.filter((sess) => sess.id !== update.id)
        activeSessions = s.activeSessions.filter((sess) => sess.id !== update.id)
      }

      return { pendingSessions, activeSessions }
    }),

  removeSession: (id) =>
    set((s) => ({
      pendingSessions: s.pendingSessions.filter((sess) => sess.id !== id),
      activeSessions: s.activeSessions.filter((sess) => sess.id !== id),
    })),

  socketLiveData: {},
  setSocketLiveData: (socketId, data) =>
    set((s) => ({ socketLiveData: { ...s.socketLiveData, [socketId]: data } })),

  waterLiveData: null,
  setWaterLiveData: (data) => set({ waterLiveData: data }),

  temperatureData: {},
  moistureData: {},
  setSensorReading: (type, pedestalId, reading) =>
    set((s) =>
      type === 'temperature'
        ? { temperatureData: { ...s.temperatureData, [pedestalId]: reading } }
        : { moistureData: { ...s.moistureData, [pedestalId]: reading } }
    ),

  pedestalOnline: false,
  setOnline: (online) => set({ pedestalOnline: online }),

  wsConnected: false,
  setWsConnected: (wsConnected) => set({ wsConnected }),

  selectedPedestalId: null,
  setSelectedPedestalId: (selectedPedestalId) => set({ selectedPedestalId }),

  pendingSockets: {},
  addPendingSocket: (pedestal_id, socket_id) =>
    set((s) => ({
      pendingSockets: {
        ...s.pendingSockets,
        [`${pedestal_id}-${socket_id}`]: { pedestal_id, socket_id },
      },
    })),
  removePendingSocket: (pedestal_id, socket_id) =>
    set((s) => {
      const next = { ...s.pendingSockets }
      delete next[`${pedestal_id}-${socket_id}`]
      return { pendingSockets: next }
    }),

  socketComputedStates: {},
  setSocketComputedState: (pedestal_id, socket_id, state) =>
    set((s) => ({
      socketComputedStates: {
        ...s.socketComputedStates,
        [`${pedestal_id}-${socket_id}`]: state,
      },
    })),

  socketAutoActivate: {},
  setSocketAutoActivate: (pedestal_id, socket_id, value) =>
    set((s) => ({
      socketAutoActivate: {
        ...s.socketAutoActivate,
        [`${pedestal_id}-${socket_id}`]: value,
      },
    })),

  socketAutoSkipReasons: {},
  setSocketAutoSkipReason: (pedestal_id, socket_id, reason) =>
    set((s) => ({
      socketAutoSkipReasons: {
        ...s.socketAutoSkipReasons,
        [`${pedestal_id}-${socket_id}`]: { reason, ts: Date.now() },
      },
    })),
  clearSocketAutoSkipReason: (pedestal_id, socket_id) =>
    set((s) => {
      const next = { ...s.socketAutoSkipReasons }
      delete next[`${pedestal_id}-${socket_id}`]
      return { socketAutoSkipReasons: next }
    }),

  unreadChatCount: 0,
  setUnreadChatCount: (count) => set({ unreadChatCount: count }),
  incrementUnreadChat: () => set((s) => ({ unreadChatCount: s.unreadChatCount + 1 })),

  lastChatMessage: null,
  setLastChatMessage: (msg) => set({ lastChatMessage: msg }),

  newErrorCount: 0,
  incrementNewErrors: () => set((s) => ({ newErrorCount: s.newErrorCount + 1 })),
  resetNewErrors: () => set({ newErrorCount: 0 }),

  hwAlarmLevel: 'none',
  setHwAlarmLevel: (level) => set({ hwAlarmLevel: level }),

  berthOccupancy: [],
  setBerthOccupancy: (berths) => set({ berthOccupancy: berths }),
  updateBerthOccupancy: (incoming) =>
    set((s) => {
      const map = new Map(s.berthOccupancy.map((b) => [b.id, b]))
      for (const b of incoming) map.set(b.id, b as BerthStatus)
      return { berthOccupancy: Array.from(map.values()) }
    }),

  pedestalHealth: {},
  setPedestalHealth: (health) => set({ pedestalHealth: health }),
  updatePedestalHealthEntry: (pedestalId, update) =>
    set((s) => ({
      pedestalHealth: {
        ...s.pedestalHealth,
        [pedestalId]: { ...(s.pedestalHealth[pedestalId] ?? {}), ...update } as PedestalHealth,
      },
    })),

  marinaDoorState: {},
  setMarinaDoorState: (pedestalId, state) =>
    set((s) => ({ marinaDoorState: { ...s.marinaDoorState, [pedestalId]: state } })),

  optaSocketStates: {},
  setOptaSocketState: (key, data) =>
    set((s) => ({ optaSocketStates: { ...s.optaSocketStates, [key]: data } })),

  optaWaterStates: {},
  setOptaWaterState: (key, data) =>
    set((s) => ({ optaWaterStates: { ...s.optaWaterStates, [key]: data } })),

  optaStatusInfo: {},
  setOptaStatusInfo: (pedestalId, info) =>
    set((s) => ({ optaStatusInfo: { ...s.optaStatusInfo, [pedestalId]: info } })),

  optaEvents: {},
  addOptaEvent: (pedestalId, entry) =>
    set((s) => {
      const prev = s.optaEvents[pedestalId] ?? []
      return { optaEvents: { ...s.optaEvents, [pedestalId]: [entry, ...prev].slice(0, 30) } }
    }),

  optaAcks: {},
  addOptaAck: (pedestalId, entry) =>
    set((s) => {
      const prev = s.optaAcks[pedestalId] ?? []
      return { optaAcks: { ...s.optaAcks, [pedestalId]: [entry, ...prev].slice(0, 30) } }
    }),
}))
