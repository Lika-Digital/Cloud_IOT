import { create } from 'zustand'
import AsyncStorage from '@react-native-async-storage/async-storage'

export type ThemeMode = 'light' | 'dark' | 'system'

interface ThemeState {
  mode: ThemeMode
  loaded: boolean
  setMode: (mode: ThemeMode) => void
  loadFromStorage: () => Promise<void>
}

export const useThemeStore = create<ThemeState>((set) => ({
  mode: 'system',
  loaded: false,

  setMode: (mode) => {
    set({ mode })
    AsyncStorage.setItem('theme_mode', mode)
  },

  loadFromStorage: async () => {
    const stored = await AsyncStorage.getItem('theme_mode')
    if (stored === 'light' || stored === 'dark' || stored === 'system') {
      set({ mode: stored, loaded: true })
    } else {
      set({ loaded: true })
    }
  },
}))
