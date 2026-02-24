import { Component, type ReactNode } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import Layout from './components/layout/Layout'
import Dashboard from './pages/Dashboard'
import Analytics from './pages/Analytics'
import History from './pages/History'
import Settings from './pages/Settings'
import Billing from './pages/Billing'
import Users from './pages/Users'
import SystemHealth from './pages/SystemHealth'
import Contracts from './pages/Contracts'
import BerthOccupancy from './pages/BerthOccupancy'
import LoginPage from './pages/LoginPage'
import ProtectedRoute from './components/auth/ProtectedRoute'
import { useWebSocket } from './hooks/useWebSocket'

class ErrorBoundary extends Component<{ children: ReactNode }, { hasError: boolean }> {
  constructor(props: { children: ReactNode }) {
    super(props)
    this.state = { hasError: false }
  }
  static getDerivedStateFromError() {
    return { hasError: true }
  }
  render() {
    if (this.state.hasError) {
      return (
        <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', backgroundColor: '#030712', color: '#f9fafb', flexDirection: 'column', gap: 16 }}>
          <p style={{ fontSize: 24, fontWeight: 700 }}>Something went wrong</p>
          <button
            onClick={() => window.location.reload()}
            style={{ padding: '10px 24px', background: '#2563eb', color: '#fff', borderRadius: 8, border: 'none', cursor: 'pointer', fontSize: 14, fontWeight: 600 }}
          >
            Reload
          </button>
        </div>
      )
    }
    return this.props.children
  }
}

function AppInner() {
  useWebSocket()
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        path="/"
        element={
          <ProtectedRoute>
            <Layout />
          </ProtectedRoute>
        }
      >
        <Route index element={<Navigate to="/dashboard" replace />} />
        <Route path="dashboard" element={<Dashboard />} />
        <Route path="analytics" element={<Analytics />} />
        <Route path="history" element={<History />} />
        <Route
          path="settings"
          element={
            <ProtectedRoute adminOnly>
              <Settings />
            </ProtectedRoute>
          }
        />
        <Route
          path="billing"
          element={
            <ProtectedRoute adminOnly>
              <Billing />
            </ProtectedRoute>
          }
        />
        <Route
          path="users"
          element={
            <ProtectedRoute adminOnly>
              <Users />
            </ProtectedRoute>
          }
        />
        <Route
          path="system-health"
          element={
            <ProtectedRoute adminOnly>
              <SystemHealth />
            </ProtectedRoute>
          }
        />
        <Route
          path="contracts"
          element={
            <ProtectedRoute adminOnly>
              <Contracts />
            </ProtectedRoute>
          }
        />
        <Route
          path="berths"
          element={
            <ProtectedRoute adminOnly>
              <BerthOccupancy />
            </ProtectedRoute>
          }
        />
      </Route>
      <Route path="*" element={<Navigate to="/dashboard" replace />} />
    </Routes>
  )
}

export default function App() {
  return (
    <ErrorBoundary>
      <BrowserRouter>
        <AppInner />
      </BrowserRouter>
    </ErrorBoundary>
  )
}
