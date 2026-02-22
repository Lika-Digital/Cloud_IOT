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

  unreadChatCount: 0,
  setUnreadChatCount: (count) => set({ unreadChatCount: count }),
  incrementUnreadChat: () => set((s) => ({ unreadChatCount: s.unreadChatCount + 1 })),

  lastChatMessage: null,
  setLastChatMessage: (msg) => set({ lastChatMessage: msg }),

  newErrorCount: 0,
  incrementNewErrors: () => set((s) => ({ newErrorCount: s.newErrorCount + 1 })),
  resetNewErrors: () => set({ newErrorCount: 0 }),
}))
