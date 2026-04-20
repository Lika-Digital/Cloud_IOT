import { create } from 'zustand'
import { readToken, writeToken, clearToken } from './secureTokenStorage'

interface CustomerProfile {
  id: number
  email: string
  name: string | null
  ship_name: string | null
}

interface AuthState {
  token: string | null
  profile: CustomerProfile | null
  loaded: boolean
  setToken: (token: string | null) => void
  setProfile: (profile: CustomerProfile | null) => void
  logout: () => void
  loadFromStorage: () => Promise<void>
}

// Synchronous token getter for the axios interceptor. Mirrors the in-memory
// Zustand value; the SecureStore read is async so we cannot call it from
// every request interceptor, hence the cached variable.
let _token: string | null = null
export const getToken = () => _token

export const useAuthStore = create<AuthState>((set) => ({
  token: null,
  profile: null,
  loaded: false,

  setToken: (token) => {
    _token = token
    set({ token })
    if (token) {
      // Fire-and-forget; failures are non-fatal (user re-logs in on next launch).
      void writeToken(token)
    } else {
      void clearToken()
    }
  },

  setProfile: (profile) => set({ profile }),

  logout: () => {
    _token = null
    set({ token: null, profile: null })
    void clearToken()
  },

  loadFromStorage: async () => {
    // readToken() transparently migrates AsyncStorage → SecureStore on first
    // run after the upgrade, so existing logged-in users keep their session.
    const stored = await readToken()
    if (stored) {
      _token = stored
      set({ token: stored, loaded: true })
    } else {
      set({ loaded: true })
    }
  },
}))
