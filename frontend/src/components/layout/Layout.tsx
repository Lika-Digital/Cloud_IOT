import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { useStore } from '../../store'
import { useAuthStore } from '../../store/authStore'
import logo from '../../assets/logo.png'

export default function Layout() {
  const { wsConnected, pedestalOnline } = useStore()
  const { email, role, logout } = useAuthStore()
  const navigate = useNavigate()

  const isAdmin = role === 'admin'

  const NAV_ITEMS = [
    { to: '/dashboard', label: 'Dashboard', icon: '⚡' },
    { to: '/analytics', label: 'Analytics', icon: '📊' },
    { to: '/history', label: 'History', icon: '📋' },
    ...(isAdmin ? [{ to: '/settings', label: 'Settings', icon: '⚙️' }] : []),
  ]

  const handleLogout = () => {
    logout()
    navigate('/login', { replace: true })
  }

  return (
    <div className="flex h-screen bg-gray-950">
      {/* Sidebar */}
      <aside className="w-56 bg-gray-900 border-r border-gray-800 flex flex-col">
        {/* Logo */}
        <div className="p-4 border-b border-gray-800">
          <img src={logo} alt="Company Logo" className="w-full h-12 object-contain rounded-lg" />
          <p className="text-xs text-gray-500 mt-2 text-center">IoT Dashboard</p>
        </div>

        {/* Nav */}
        <nav className="flex-1 p-3 space-y-1">
          {NAV_ITEMS.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                `flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors ${
                  isActive
                    ? 'bg-blue-600/20 text-blue-400 border border-blue-600/30'
                    : 'text-gray-400 hover:text-gray-200 hover:bg-gray-800'
                }`
              }
            >
              <span>{item.icon}</span>
              {item.label}
            </NavLink>
          ))}
        </nav>

        {/* Status + user info */}
        <div className="p-4 border-t border-gray-800 space-y-3">
          <StatusDot label="WebSocket" active={wsConnected} />
          <StatusDot label="Pedestal" active={pedestalOnline} />

          {/* User info */}
          <div className="pt-2 border-t border-gray-800">
            <div className="flex items-center gap-2 mb-2">
              <div className="w-7 h-7 rounded-full bg-blue-700 flex items-center justify-center text-white text-xs font-bold">
                {email?.[0]?.toUpperCase() ?? '?'}
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-xs text-gray-300 truncate">{email}</p>
                <p className="text-xs text-gray-600 capitalize">{role}</p>
              </div>
            </div>
            <button
              onClick={handleLogout}
              className="w-full text-xs text-gray-500 hover:text-red-400 transition-colors py-1 rounded text-left"
            >
              Sign out
            </button>
          </div>
        </div>
      </aside>

      {/* Main content */}
      <main className="flex-1 overflow-auto">
        <div className="p-6 max-w-7xl mx-auto">
          <Outlet />
        </div>
      </main>
    </div>
  )
}

function StatusDot({ label, active }: { label: string; active: boolean }) {
  return (
    <div className="flex items-center gap-2 text-xs text-gray-400">
      <span className={`w-2 h-2 rounded-full ${active ? 'bg-green-400 animate-pulse' : 'bg-gray-600'}`} />
      {label}
      <span className={active ? 'text-green-400' : 'text-gray-600'}>
        {active ? 'Online' : 'Offline'}
      </span>
    </div>
  )
}
