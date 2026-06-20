import { create } from 'zustand'
import { persist } from 'zustand/middleware'

// v3.34 — three operator roles. monitor_control sits between admin and monitor:
// it can control/configure every section EXCEPT the three admin-only ones
// (System Health, Settings, API Gateway).
export type Role = 'admin' | 'monitor_control' | 'monitor'

/** Can act (control/configure) in the non-admin sections. */
export const canControl = (role: Role | null): boolean =>
  role === 'admin' || role === 'monitor_control'

interface AuthState {
  token: string | null
  role: Role | null
  email: string | null
  isAuthenticated: boolean
  setAuth: (token: string, role: Role, email: string) => void
  logout: () => void
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      token: null,
      role: null,
      email: null,
      isAuthenticated: false,

      setAuth: (token, role, email) => {
        set({ token, role, email, isAuthenticated: true })
      },

      logout: () => {
        set({ token: null, role: null, email: null, isAuthenticated: false })
      },
    }),
    {
      name: 'auth-store',
      partialize: (state) => ({
        token: state.token,
        role: state.role,
        email: state.email,
        isAuthenticated: state.isAuthenticated,
      }),
    }
  )
)
