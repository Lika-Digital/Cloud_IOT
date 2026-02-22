import { create } from 'zustand'

export interface ActiveSession {
  id: number
  pedestal_id: number
  socket_id: number | null
  type: 'electricity' | 'water'
  status: string
  started_at: string
  customer_id: number | null
}

interface SessionState {
  activeSession: ActiveSession | null
  liveKwh: number
  liveWatts: number
  liveLpm: number
  liveLiters: number
  setActiveSession: (s: ActiveSession | null) => void
  updateLivePower: (watts: number, kwh: number) => void
  updateLiveWater: (lpm: number, liters: number) => void
  clearLive: () => void
}

export const useSessionStore = create<SessionState>((set) => ({
  activeSession: null,
  liveKwh: 0,
  liveWatts: 0,
  liveLpm: 0,
  liveLiters: 0,

  setActiveSession: (s) => set({ activeSession: s }),
  updateLivePower: (watts, kwh) => set({ liveWatts: watts, liveKwh: kwh }),
  updateLiveWater: (lpm, liters) => set({ liveLpm: lpm, liveLiters: liters }),
  clearLive: () => set({ liveKwh: 0, liveWatts: 0, liveLpm: 0, liveLiters: 0 }),
}))
