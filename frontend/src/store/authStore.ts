import { create } from 'zustand'
import { persist } from 'zustand/middleware'

interface AuthState {
  token: string | null
  role: 'admin' | 'monitor' | null
  email: string | null
  isAuthenticated: boolean
  setAuth: (token: string, role: 'admin' | 'monitor', email: string) => void
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
        localStorage.setItem('auth_token', token)
        set({ token, role, email, isAuthenticated: true })
      },

      logout: () => {
        localStorage.removeItem('auth_token')
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
