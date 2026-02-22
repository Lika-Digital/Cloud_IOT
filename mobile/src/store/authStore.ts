import { create } from 'zustand'
import AsyncStorage from '@react-native-async-storage/async-storage'

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

// Synchronous token getter for axios interceptor
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
      AsyncStorage.setItem('customer_token', token)
    } else {
      AsyncStorage.removeItem('customer_token')
    }
  },

  setProfile: (profile) => set({ profile }),

  logout: () => {
    _token = null
    set({ token: null, profile: null })
    AsyncStorage.removeItem('customer_token')
  },

  loadFromStorage: async () => {
    const stored = await AsyncStorage.getItem('customer_token')
    if (stored) {
      _token = stored
      set({ token: stored, loaded: true })
    } else {
      set({ loaded: true })
    }
  },
}))
