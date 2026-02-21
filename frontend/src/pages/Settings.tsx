import { useState, useEffect } from 'react'
import ConfigPanel from '../components/config/ConfigPanel'
import FieldHelp from '../components/config/FieldHelp'
import { getPedestals, configurePedestals } from '../api'
import { useStore } from '../store'
import { authListUsers, authCreateUser, authDeleteUser, type UserResponse } from '../api/auth'

export default function Settings() {
  const { setPedestals } = useStore()
  const [pedestalCount, setPedestalCount] = useState(1)
  const [currentCount, setCurrentCount]   = useState(1)
  const [loading, setLoading]             = useState(false)
  const [message, setMessage]             = useState<{ type: 'success' | 'error'; text: string } | null>(null)

  useEffect(() => {
    getPedestals().then((data) => {
      setCurrentCount(data.length)
      setPedestalCount(data.length)
    })
  }, [])

  const handleApplyCount = async () => {
    setLoading(true)
    setMessage(null)
    try {
      const updated = await configurePedestals(pedestalCount)
      setPedestals(updated)
      setCurrentCount(updated.length)
      setMessage({ type: 'success', text: `Fleet updated to ${updated.length} pedestal(s).` })
    } catch {
      setMessage({ type: 'error', text: 'Failed to update pedestal count.' })
    } finally {
      setLoading(false)
    }
  }

  return (
    <div>
      <h1 className="text-2xl font-bold text-white mb-6">Settings</h1>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">

        {/* Left column */}
        <div className="space-y-6">

          {/* Fleet size */}
          <div className="card space-y-4">
            <h3 className="font-semibold text-white">Fleet Configuration</h3>
            <p className="text-sm text-gray-400">
              Set how many pedestals are monitored. New pedestals are created automatically.
            </p>

            <div className="flex items-center gap-4">
              <div className="flex-1">
                <label className="block text-sm text-gray-400 mb-1">Number of pedestals</label>
                <input
                  type="number"
                  min={1}
                  max={20}
                  value={pedestalCount}
                  onChange={(e) => setPedestalCount(Math.max(1, Math.min(20, Number(e.target.value))))}
                  className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-white text-sm"
                />
                <FieldHelp example="1 – 20" hint="Whole number · new pedestals are auto-created" />
              </div>
              <div className="text-center">
                <p className="text-xs text-gray-500 mb-1">Currently</p>
                <p className="text-2xl font-bold text-blue-400">{currentCount}</p>
              </div>
            </div>

            {/* Visual count selector */}
            <div className="flex gap-2 flex-wrap">
              {[1, 2, 3, 4, 5, 6].map((n) => (
                <button
                  key={n}
                  onClick={() => setPedestalCount(n)}
                  className={`w-10 h-10 rounded-lg text-sm font-bold transition-colors ${
                    pedestalCount === n
                      ? 'bg-blue-600 text-white'
                      : 'bg-gray-800 text-gray-400 hover:bg-gray-700'
                  }`}
                >
                  {n}
                </button>
              ))}
            </div>

            {message && (
              <div className={`text-sm px-3 py-2 rounded-lg ${
                message.type === 'success'
                  ? 'bg-green-900/30 text-green-400'
                  : 'bg-red-900/30 text-red-400'
              }`}>
                {message.text}
              </div>
            )}

            <button
              className="btn-primary w-full"
              onClick={handleApplyCount}
              disabled={loading || pedestalCount === currentCount}
            >
              {loading ? 'Applying…' : `Apply (${pedestalCount} pedestal${pedestalCount !== 1 ? 's' : ''})`}
            </button>
          </div>

          {/* Pedestal mode config */}
          <ConfigPanel />

          {/* User Management */}
          <UserManagementPanel />
        </div>

        {/* Right column — info */}
        <div className="space-y-4">
          <div className="card">
            <h3 className="font-semibold text-white mb-3">Quick Start</h3>
            <ol className="text-sm text-gray-400 space-y-2 list-decimal list-inside">
              <li>Set number of pedestals above and click Apply</li>
              <li>Select <strong className="text-white">Synthetic Data</strong> mode and click Apply</li>
              <li>Go to Dashboard — pedestal cards appear</li>
              <li>Click a pedestal card to open its detail view</li>
              <li>Click socket zones to Allow / Deny / Stop sessions</li>
            </ol>
          </div>
          <div className="card">
            <h3 className="font-semibold text-white mb-3">MQTT Topics</h3>
            <div className="space-y-1 text-xs font-mono text-gray-400">
              <p className="text-gray-500">// Pedestal → Backend</p>
              <p>pedestal/{'{id}'}/socket/{'{1-4}'}/status</p>
              <p>pedestal/{'{id}'}/socket/{'{1-4}'}/power</p>
              <p>pedestal/{'{id}'}/water/flow</p>
              <p>pedestal/{'{id}'}/heartbeat</p>
              <p className="text-gray-500 mt-2">// Backend → Pedestal</p>
              <p>pedestal/{'{id}'}/socket/{'{1-4}'}/control</p>
              <p>pedestal/{'{id}'}/water/control</p>
            </div>
          </div>
          <div className="card">
            <h3 className="font-semibold text-white mb-3">User Roles</h3>
            <div className="space-y-2 text-sm text-gray-400">
              <div>
                <span className="text-blue-400 font-medium">Admin</span>
                <p className="text-xs mt-0.5">Full access — control sessions, configure pedestals, manage users</p>
              </div>
              <div>
                <span className="text-green-400 font-medium">Monitor</span>
                <p className="text-xs mt-0.5">Read-only — view dashboard, analytics, and history only</p>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

// ── User Management Panel ─────────────────────────────────────────────────────

function UserManagementPanel() {
  const [users, setUsers] = useState<UserResponse[]>([])
  const [showAdd, setShowAdd] = useState(false)
  const [newEmail, setNewEmail] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [newRole, setNewRole] = useState<'admin' | 'monitor'>('monitor')
  const [addMsg, setAddMsg] = useState<{ type: 'success' | 'error'; text: string } | null>(null)
  const [adding, setAdding] = useState(false)

  useEffect(() => {
    authListUsers().then(setUsers).catch(() => {})
  }, [])

  const handleAdd = async (e: React.FormEvent) => {
    e.preventDefault()
    setAdding(true)
    setAddMsg(null)
    try {
      const created = await authCreateUser({ email: newEmail, password: newPassword, role: newRole })
      setUsers((prev) => [...prev, created])
      setNewEmail('')
      setNewPassword('')
      setNewRole('monitor')
      setShowAdd(false)
      setAddMsg({ type: 'success', text: `User ${created.email} created.` })
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setAddMsg({ type: 'error', text: msg ?? 'Failed to create user.' })
    } finally {
      setAdding(false)
    }
  }

  const handleDelete = async (id: number, email: string) => {
    if (!confirm(`Delete user ${email}?`)) return
    try {
      await authDeleteUser(id)
      setUsers((prev) => prev.filter((u) => u.id !== id))
    } catch {
      alert('Failed to delete user.')
    }
  }

  return (
    <div className="card space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="font-semibold text-white">User Management</h3>
        <button
          onClick={() => setShowAdd((v) => !v)}
          className="text-xs px-3 py-1.5 rounded-lg bg-blue-700 hover:bg-blue-600 text-white transition-colors"
        >
          {showAdd ? 'Cancel' : '+ Add User'}
        </button>
      </div>

      {addMsg && (
        <div className={`text-sm px-3 py-2 rounded-lg ${
          addMsg.type === 'success' ? 'bg-green-900/30 text-green-400' : 'bg-red-900/30 text-red-400'
        }`}>
          {addMsg.text}
        </div>
      )}

      {showAdd && (
        <form onSubmit={handleAdd} className="space-y-3 p-3 bg-gray-800/50 rounded-lg border border-gray-700">
          <h4 className="text-sm font-medium text-gray-300">New User</h4>
          <div>
            <label className="block text-xs text-gray-400 mb-1">Email</label>
            <input
              type="email"
              required
              value={newEmail}
              onChange={(e) => setNewEmail(e.target.value)}
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-white text-sm"
              placeholder="user@example.com"
            />
            <FieldHelp example="user@example.com" hint="Email address used to log in" />
          </div>
          <div>
            <label className="block text-xs text-gray-400 mb-1">Password</label>
            <input
              type="password"
              required
              minLength={6}
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-white text-sm"
              placeholder="Min 6 characters"
            />
            <FieldHelp example="min 6 chars" hint="User can change after first login" />
          </div>
          <div>
            <label className="block text-xs text-gray-400 mb-1">Role</label>
            <select
              value={newRole}
              onChange={(e) => setNewRole(e.target.value as 'admin' | 'monitor')}
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-white text-sm"
            >
              <option value="monitor">Monitor — read only</option>
              <option value="admin">Admin — full access</option>
            </select>
          </div>
          <button type="submit" disabled={adding} className="btn-primary w-full">
            {adding ? 'Creating…' : 'Create User'}
          </button>
        </form>
      )}

      {/* User list */}
      <div className="space-y-2">
        {users.map((u) => (
          <div
            key={u.id}
            className="flex items-center justify-between py-2 px-3 rounded-lg bg-gray-800/50 border border-gray-700/50"
          >
            <div>
              <p className="text-sm text-gray-200">{u.email}</p>
              <p className="text-xs text-gray-500 capitalize">{u.role}</p>
            </div>
            <div className="flex items-center gap-2">
              <span className={`text-xs px-2 py-0.5 rounded-full border ${
                u.role === 'admin'
                  ? 'bg-blue-900/30 text-blue-400 border-blue-700/40'
                  : 'bg-green-900/30 text-green-400 border-green-700/40'
              }`}>
                {u.role}
              </span>
              <button
                onClick={() => handleDelete(u.id, u.email)}
                className="text-xs text-gray-600 hover:text-red-400 transition-colors px-1"
                title="Delete user"
              >
                ✕
              </button>
            </div>
          </div>
        ))}
        {users.length === 0 && (
          <p className="text-sm text-gray-600 text-center py-2">No users found.</p>
        )}
      </div>
    </div>
  )
}
