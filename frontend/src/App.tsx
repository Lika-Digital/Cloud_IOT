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
import ApiGateway from './pages/ApiGateway'
// v3.44 — the marina Monitoring & Control profile. A separate route tree from the admin
// dashboard on purpose: the admin surface stays exactly as it is.
import MarinaDashboard from './pages/marina/MarinaDashboard'
import BerthDetail from './pages/marina/BerthDetail'
import MarinaWater from './pages/marina/MarinaWater'
import MarinaAlarms from './pages/marina/MarinaAlarms'
import MarinaGuard from './pages/marina/MarinaGuard'
import MarinaSetup from './pages/marina/MarinaSetup'
import LoginPage from './pages/LoginPage'
import Register from './pages/Register'
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
      <Route path="/register" element={<Register />} />
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
        {/* Marina profile. Three levels, no more, and back is always visible. */}
        <Route path="marina" element={<MarinaDashboard />} />
        <Route path="marina/berth/:berthId" element={<BerthDetail />} />
        <Route path="marina/water" element={<MarinaWater />} />
        <Route path="marina/alarms" element={<MarinaAlarms />} />
        <Route path="marina/guard" element={<MarinaGuard />} />
        {/* Installation. The BACKEND enforces admin on the write; this route being
            reachable is not what protects it. */}
        <Route path="marina/setup/:pedestalId" element={<MarinaSetup />} />
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
        {/* 2026-10-12 — Billing, Customers and Contracts are admin only (owner's decision:
            marina staff do not see customer data). The API enforces it; these guards keep
            staff from landing on a page of 403s. Berths stays shared. */}
        <Route path="billing" element={<ProtectedRoute adminOnly><Billing /></ProtectedRoute>} />
        <Route path="users" element={<ProtectedRoute adminOnly><Users /></ProtectedRoute>} />
        <Route
          path="system-health"
          element={
            <ProtectedRoute adminOnly>
              <SystemHealth />
            </ProtectedRoute>
          }
        />
        <Route path="contracts" element={<ProtectedRoute adminOnly><Contracts /></ProtectedRoute>} />
        <Route path="berths" element={<BerthOccupancy />} />
        <Route
          path="api-gateway"
          element={
            <ProtectedRoute apiConfig>
              <ApiGateway />
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
