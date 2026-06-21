import { create } from 'zustand'
import { persist } from 'zustand/middleware'

// v3.35 — light/dark theme. The actual colour flip is a single `.light` class
// on <html> (see index.css ramp mirroring); this store just persists the choice
// and applies the class. Default dark (the marina dashboard's native look);
// light is for high-sun outdoor visibility.
export type Theme = 'dark' | 'light'

export function applyTheme(theme: Theme) {
  if (typeof document === 'undefined') return
  document.documentElement.classList.toggle('light', theme === 'light')
}

interface ThemeState {
  theme: Theme
  setTheme: (t: Theme) => void
  toggle: () => void
}

export const useThemeStore = create<ThemeState>()(
  persist(
    (set, get) => ({
      theme: 'dark',
      setTheme: (theme) => { applyTheme(theme); set({ theme }) },
      toggle: () => get().setTheme(get().theme === 'dark' ? 'light' : 'dark'),
    }),
    {
      name: 'theme',
      onRehydrateStorage: () => (state) => {
        // Re-apply the persisted choice to <html> once the store hydrates.
        if (state) applyTheme(state.theme)
      },
    }
  )
)
