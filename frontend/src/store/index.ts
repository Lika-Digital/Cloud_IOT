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
}

export interface PedestalHealth {
  opta_connected: boolean
  last_heartbeat: string | null
  camera_reachable: boolean
  last_camera_check: string | null
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

  // Berth occupancy
  berthOccupancy: BerthStatus[]
  setBerthOccupancy: (berths: BerthStatus[]) => void
  updateBerthOccupancy: (berths: BerthStatus[]) => void

  // Pedestal health (opta / camera)
  pedestalHealth: Record<number, PedestalHealth>
  setPedestalHealth: (health: Record<number, PedestalHealth>) => void
  updatePedestalHealthEntry: (pedestalId: number, update: Partial<PedestalHealth>) => void
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

  unreadChatCount: 0,
  setUnreadChatCount: (count) => set({ unreadChatCount: count }),
  incrementUnreadChat: () => set((s) => ({ unreadChatCount: s.unreadChatCount + 1 })),

  lastChatMessage: null,
  setLastChatMessage: (msg) => set({ lastChatMessage: msg }),

  newErrorCount: 0,
  incrementNewErrors: () => set((s) => ({ newErrorCount: s.newErrorCount + 1 })),
  resetNewErrors: () => set({ newErrorCount: 0 }),

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
}))
