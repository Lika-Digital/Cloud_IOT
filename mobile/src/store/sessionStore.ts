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
  // The same union as ChatMessage.direction in src/api/chat.ts. It was `string`, which
  // is why appending a websocket message to the ChatMessage[] state did not typecheck —
  // and that error sat unread in the mobile baseline alongside three others.
  direction: 'from_customer' | 'from_operator'
  created_at: string
}

// Set after a successful NFC scan, while we wait for the user to plug in and the
// backend to broadcast session_created. The WS hook matches an incoming
// session_created against this (by nfc user id + outlet + type) to adopt the session.
export interface NfcPending {
  cabinet_id: string
  outlet_id: string // "Q1".."Q4" for a socket, "V1"/"V2" for a water outlet
  outletNum: number | null
  // v3.43 — REQUIRED for adoption, not decoration. A water session on V1 and an electricity
  // session on Q1 both arrive as socket_id=1, so the number alone cannot tell them apart:
  // matching on it would adopt whichever landed first. The backend returns this from /scan.
  sessionType: 'electricity' | 'water'
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
