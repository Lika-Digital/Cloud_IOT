import { NavLink, Outlet, useNavigate, useLocation } from 'react-router-dom'
import { useStore } from '../../store'
import { useAuthStore } from '../../store/authStore'
import { useThemeStore } from '../../store/themeStore'
import logo from '../../assets/logo.png'
import { useEffect, useState } from 'react'
import { getUnreadCount } from '../../api/billing'
import ToastContainer from '../ui/ToastContainer'

export default function Layout() {
  const { wsConnected, pedestalOnline, unreadChatCount, setUnreadChatCount, newErrorCount, hwAlarmLevel } = useStore()
  const { email, role, logout } = useAuthStore()
  const { theme, toggle: toggleTheme } = useThemeStore()
  const navigate = useNavigate()
  const location = useLocation()

  const isAdmin = role === 'admin'

  // v3.33 — mobile: the sidebar collapses into a slide-in drawer behind a
  // hamburger. Close it on every route change so a nav tap doesn't leave the
  // overlay covering the page.
  const [sidebarOpen, setSidebarOpen] = useState(false)
  useEffect(() => { setSidebarOpen(false) }, [location.pathname])

  // Customers is visible to every operator now, so poll the unread badge for all.
  useEffect(() => {
    getUnreadCount().then((r) => setUnreadChatCount(r.unread_customers)).catch(() => {})
    const interval = setInterval(() => {
      getUnreadCount().then((r) => setUnreadChatCount(r.unread_customers)).catch(() => {})
    }, 30_000)
    return () => clearInterval(interval)
  }, [])

  type NavItem = { to: string; label: string; icon: string; badge: number; hwAlarm?: 'none' | 'warning' | 'critical' | 'auto_stop' }
  // v3.34 — Dashboard/Analytics/History + Billing/Customers/Contracts/Berths are
  // shared by all operators; only the three admin sections are gated by isAdmin.
  const NAV_ITEMS: NavItem[] = [
    { to: '/dashboard', label: 'Dashboard', icon: '⚡', badge: 0 },
    { to: '/analytics', label: 'Analytics', icon: '📊', badge: 0 },
    { to: '/history', label: 'History', icon: '📋', badge: 0 },
    { to: '/billing', label: 'Billing', icon: '💰', badge: 0 },
    { to: '/users', label: 'Customers', icon: '👥', badge: unreadChatCount },
    { to: '/contracts', label: 'Contracts', icon: '📝', badge: 0 },
    { to: '/berths', label: 'Berth Occupancy', icon: '⚓', badge: 0 },
    ...(isAdmin ? [
      { to: '/system-health', label: 'System Health', icon: '🔧', badge: newErrorCount, hwAlarm: hwAlarmLevel },
      { to: '/api-gateway', label: 'API Gateway', icon: '🔌', badge: 0 },
      { to: '/settings', label: 'Settings', icon: '⚙️', badge: 0 },
    ] : []),
  ]

  const handleLogout = () => {
    logout()
    navigate('/login', { replace: true })
  }

  return (
    <div className="flex h-screen bg-gray-950">
      {/* Mobile backdrop — tap to close the drawer */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 z-30 bg-black/60 md:hidden"
          onClick={() => setSidebarOpen(false)}
          aria-hidden="true"
        />
      )}

      {/* Sidebar — static on md+, slide-in drawer on mobile */}
      <aside className={`fixed inset-y-0 left-0 z-40 w-56 bg-gray-900 border-r border-gray-800 flex flex-col transform transition-transform duration-200 md:static md:translate-x-0 ${
        sidebarOpen ? 'translate-x-0' : '-translate-x-full'
      }`}>
        {/* Logo */}
        <div className="p-4 border-b border-gray-800">
          <img src={logo} alt="Company Logo" className="w-full h-12 object-contain rounded-lg" />
          <p className="text-xs text-gray-500 mt-2 text-center">IoT Dashboard</p>
        </div>

        {/* Nav — scrolls when the list is taller than the viewport (small
            screens) so the pinned user/sign-out block below stays reachable.
            min-h-0 lets this flex child shrink below its content height. */}
        <nav className="flex-1 min-h-0 overflow-y-auto p-3 space-y-1">
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
              <span className="flex-1">{item.label}</span>
              {item.hwAlarm && item.hwAlarm !== 'none' && (
                <span className={`w-2.5 h-2.5 rounded-full animate-pulse flex-shrink-0 ${
                  // v3.12 — auto_stop is the highest severity (rendered as a
                  // brighter red ring so it's distinct from a regular critical).
                  item.hwAlarm === 'auto_stop' ? 'bg-red-500 ring-2 ring-red-300' :
                  item.hwAlarm === 'critical' ? 'bg-red-500' : 'bg-yellow-400'
                }`} title={
                  item.hwAlarm === 'auto_stop'
                    ? 'Socket auto-stopped — overload alarm pending acknowledgment'
                    : `HW ${item.hwAlarm} alarm active`
                } />
              )}
              {item.badge > 0 && (
                <span className="bg-red-500 text-white text-xs font-bold rounded-full w-5 h-5 flex items-center justify-center">
                  {item.badge > 9 ? '9+' : item.badge}
                </span>
              )}
            </NavLink>
          ))}
        </nav>

        {/* Status + user info — pinned to the bottom, never collapses so the
            Sign out button is always visible. */}
        <div className="flex-shrink-0 p-4 border-t border-gray-800 space-y-3">
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
              onClick={toggleTheme}
              className="w-full flex items-center gap-2 text-xs text-gray-400 hover:text-gray-200 transition-colors py-1 rounded text-left"
              title="Toggle light/dark theme"
            >
              <span>{theme === 'dark' ? '☀️' : '🌙'}</span>
              <span>{theme === 'dark' ? 'Light mode' : 'Dark mode'}</span>
            </button>
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
      <main className="flex-1 overflow-auto flex flex-col min-w-0">
        {/* Mobile top bar — hamburger + brand (hidden on md+ where the sidebar is always visible) */}
        <header className="md:hidden sticky top-0 z-20 flex items-center gap-3 px-4 h-14 bg-gray-900 border-b border-gray-800">
          <button
            onClick={() => setSidebarOpen(true)}
            className="p-2 -ml-2 text-gray-300 hover:text-gray-100"
            aria-label="Open menu"
          >
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              <line x1="3" y1="6" x2="21" y2="6" />
              <line x1="3" y1="12" x2="21" y2="12" />
              <line x1="3" y1="18" x2="21" y2="18" />
            </svg>
          </button>
          <span className="text-sm font-semibold text-gray-100">IoT Dashboard</span>
          <button
            onClick={toggleTheme}
            className="ml-auto p-2 text-gray-300 hover:text-gray-100"
            aria-label={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
            title={theme === 'dark' ? 'Light mode (high sun)' : 'Dark mode'}
          >
            {theme === 'dark' ? '☀️' : '🌙'}
          </button>
          <span className={`w-2 h-2 rounded-full ${wsConnected ? 'bg-green-400 animate-pulse' : 'bg-gray-600'}`} title={wsConnected ? 'Online' : 'Offline'} />
        </header>

        <div className="p-4 sm:p-6 max-w-7xl mx-auto w-full">
          <Outlet />
        </div>
      </main>

      {/* v3.7 — global toast tray (new-pedestal discovery + ad-hoc banners) */}
      <ToastContainer />
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
