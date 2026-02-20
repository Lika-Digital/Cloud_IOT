import { NavLink, Outlet } from 'react-router-dom'
import { useStore } from '../../store'
import logo from '../../assets/logo.png'

const NAV_ITEMS = [
  { to: '/dashboard', label: 'Dashboard', icon: '⚡' },
  { to: '/analytics', label: 'Analytics', icon: '📊' },
  { to: '/history', label: 'History', icon: '📋' },
  { to: '/settings', label: 'Settings', icon: '⚙️' },
]

export default function Layout() {
  const { wsConnected, pedestalOnline } = useStore()

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

        {/* Status indicators */}
        <div className="p-4 border-t border-gray-800 space-y-2">
          <StatusDot label="WebSocket" active={wsConnected} />
          <StatusDot label="Pedestal" active={pedestalOnline} />
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
