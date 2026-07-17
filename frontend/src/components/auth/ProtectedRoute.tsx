import { Navigate } from 'react-router-dom'
import { useAuthStore, canManageApi } from '../../store/authStore'

interface ProtectedRouteProps {
  children: React.ReactNode
  adminOnly?: boolean
  // v3.35 — gate for the API Gateway page: admin or monitor_control_api.
  apiConfig?: boolean
}

export default function ProtectedRoute({ children, adminOnly = false, apiConfig = false }: ProtectedRouteProps) {
  const { isAuthenticated, role } = useAuthStore()

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />
  }

  if (adminOnly && role !== 'admin') {
    return <Navigate to="/dashboard" replace />
  }

  if (apiConfig && !canManageApi(role)) {
    return <Navigate to="/dashboard" replace />
  }

  return <>{children}</>
}
