import { create } from 'zustand'
import { persist } from 'zustand/middleware'

// v3.34 — operator roles. monitor_control sits between admin and monitor:
// it can control/configure every section EXCEPT the three admin-only ones
// (System Health, Settings, API Gateway).
// v3.35 — monitor_control_api = monitor_control PLUS the API Gateway configurator
// (still no System Health, Settings, or user management).
export type Role = 'admin' | 'monitor_control_api' | 'monitor_control' | 'monitor'

/** Can act (control/configure) in the non-admin sections. */
export const canControl = (role: Role | null): boolean =>
  role === 'admin' || role === 'monitor_control' || role === 'monitor_control_api'

/** Can manage the External API Gateway configuration. */
export const canManageApi = (role: Role | null): boolean =>
  role === 'admin' || role === 'monitor_control_api'

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
