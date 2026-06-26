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

export interface IncomingChatMessage {
  customer_id: number
  message: string
  direction: string
  created_at: string
}

// Set after a successful NFC scan, while we wait for the user to plug in and the
// backend to broadcast session_created. The WS hook matches an incoming
// session_created against this (by nfc user id + socket) to adopt the session.
export interface NfcPending {
  cabinet_id: string
  socket_id: string // "Q1".."Q4"
  socketNum: number | null
  user_id: string // what we sent to /api/nfc/scan (echoed back as nfc_user_id)
  expires_at: string
}

interface SessionState {
  activeSession: ActiveSession | null
  liveKwh: number
  liveWatts: number
  liveLpm: number
  liveLiters: number
  latestChatMsg: IncomingChatMessage | null
  nfcPending: NfcPending | null
  setActiveSession: (s: ActiveSession | null) => void
  updateLivePower: (watts: number, kwh: number) => void
  updateLiveWater: (lpm: number, liters: number) => void
  clearLive: () => void
  setLatestChatMsg: (msg: IncomingChatMessage) => void
  setNfcPending: (p: NfcPending | null) => void
}

export const useSessionStore = create<SessionState>((set) => ({
  activeSession: null,
  liveKwh: 0,
  liveWatts: 0,
  liveLpm: 0,
  liveLiters: 0,
  latestChatMsg: null,
  nfcPending: null,

  setActiveSession: (s) => set({ activeSession: s }),
  updateLivePower: (watts, kwh) => set({ liveWatts: watts, liveKwh: kwh }),
  updateLiveWater: (lpm, liters) => set({ liveLpm: lpm, liveLiters: liters }),
  clearLive: () => set({ liveKwh: 0, liveWatts: 0, liveLpm: 0, liveLiters: 0 }),
  setLatestChatMsg: (msg) => set({ latestChatMsg: msg }),
  setNfcPending: (p) => set({ nfcPending: p }),
}))
