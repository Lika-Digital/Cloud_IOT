import { useState, useEffect } from 'react'
import ConfigPanel from '../components/config/ConfigPanel'
import FieldHelp from '../components/config/FieldHelp'
import PedestalConfigForm from '../components/config/PedestalConfigForm'
import { getPedestals, configurePedestals } from '../api'
import { useStore, type Pedestal } from '../store'
import { authListUsers, authCreateUser, authDeleteUser, authPatchUser, type UserResponse } from '../api/auth'
import { getSmtpConfig, updateSmtpConfig, testSmtp, type SmtpConfig } from '../api/settings'

export default function Settings() {
  const { setPedestals } = useStore()
  const [pedestalCount, setPedestalCount] = useState(1)
  const [currentCount, setCurrentCount]   = useState(1)
  const [pedestals, setPedestalsList]     = useState<Pedestal[]>([])
  const [loading, setLoading]             = useState(false)
  const [message, setMessage]             = useState<{ type: 'success' | 'error'; text: string } | null>(null)

  useEffect(() => {
    getPedestals().then((data) => {
      setCurrentCount(data.length)
      setPedestalCount(data.length)
      setPedestalsList(data)
    })
  }, [])

  const handleApplyCount = async () => {
    setLoading(true)
    setMessage(null)
    try {
      const updated = await configurePedestals(pedestalCount)
      setPedestals(updated)
      setCurrentCount(updated.length)
      setPedestalsList(updated)
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

          {/* Per-pedestal extended configuration */}
          {pedestals.length > 0 && (
            <div className="card space-y-3">
              <h3 className="font-semibold text-white">Pedestal Configuration</h3>
              <p className="text-sm text-gray-400">
                Configure site IDs, MQTT credentials, camera settings, and sensors for each pedestal.
              </p>
              <div className="space-y-2">
                {pedestals.map((p) => (
                  <PedestalConfigForm key={p.id} pedestal={p} />
                ))}
              </div>
            </div>
          )}

          {/* SMTP / Communication */}
          <SmtpSettingsPanel />

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

// ── SMTP Settings Panel ────────────────────────────────────────────────────────

function SmtpSettingsPanel() {
  const [cfg, setCfg] = useState<SmtpConfig>({
    host: '', port: 587, tls: true, username: '', password: '', from_email: '',
    configured: false, source: 'none',
  })
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [msg, setMsg] = useState<{ type: 'success' | 'error'; text: string } | null>(null)

  useEffect(() => {
    getSmtpConfig()
      .then(setCfg)
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault()
    setSaving(true)
    setMsg(null)
    try {
      await updateSmtpConfig({
        host: cfg.host, port: cfg.port, tls: cfg.tls,
        username: cfg.username, password: cfg.password, from_email: cfg.from_email,
      })
    } catch {
      setMsg({ type: 'error', text: 'Failed to save SMTP settings.' })
      setSaving(false)
      return
    }
    // Refresh to get updated configured flag + masked password
    try {
      const updated = await getSmtpConfig()
      setCfg(updated)
    } catch {
      // ignore refresh errors — save succeeded
    }
    setMsg({ type: 'success', text: 'SMTP settings saved.' })
    setSaving(false)
  }

  const handleTest = async () => {
    setTesting(true)
    setMsg(null)
    try {
      const res = await testSmtp()
      setMsg({ type: 'success', text: res.message })
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setMsg({ type: 'error', text: detail ?? 'Test email failed.' })
    } finally {
      setTesting(false)
    }
  }

  if (loading) return null

  return (
    <div className="card space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="font-semibold text-white">Email / SMTP</h3>
        <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${
          cfg.configured
            ? 'bg-green-900/50 text-green-400'
            : 'bg-yellow-900/50 text-yellow-400'
        }`}>
          {cfg.configured ? 'Configured' : 'Not configured'}
        </span>
      </div>

      {!cfg.configured && (
        <div className="px-3 py-2.5 rounded-lg bg-yellow-900/20 border border-yellow-700/40 text-yellow-400 text-xs">
          SMTP is not configured — OTP codes are printed to the server console. Set SMTP below to enable email delivery.
        </div>
      )}

      {cfg.source === 'env' && (
        <div className="px-3 py-2 rounded-lg bg-blue-900/20 border border-blue-700/40 text-blue-400 text-xs">
          Using .env settings. Save below to override with database settings.
        </div>
      )}

      <form onSubmit={handleSave} className="space-y-3">
        <div className="grid grid-cols-2 gap-3">
          <div className="col-span-2 sm:col-span-1">
            <label className="block text-xs text-gray-400 mb-1">SMTP Host</label>
            <input
              required
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-gray-200 text-sm focus:outline-none focus:border-blue-500"
              value={cfg.host}
              onChange={(e) => setCfg((c) => ({ ...c, host: e.target.value }))}
              placeholder="smtp.gmail.com"
            />
          </div>
          <div>
            <label className="block text-xs text-gray-400 mb-1">Port</label>
            <input
              type="number"
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-gray-200 text-sm focus:outline-none focus:border-blue-500"
              value={cfg.port}
              onChange={(e) => setCfg((c) => ({ ...c, port: parseInt(e.target.value) || 587 }))}
            />
          </div>
        </div>

        <div className="flex items-center gap-2">
          <input
            type="checkbox"
            id="smtp-tls"
            checked={cfg.tls}
            onChange={(e) => setCfg((c) => ({ ...c, tls: e.target.checked }))}
            className="w-4 h-4"
          />
          <label htmlFor="smtp-tls" className="text-xs text-gray-400">Use STARTTLS</label>
        </div>

        <div>
          <label className="block text-xs text-gray-400 mb-1">Username</label>
          <input
            className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-gray-200 text-sm focus:outline-none focus:border-blue-500"
            value={cfg.username}
            onChange={(e) => setCfg((c) => ({ ...c, username: e.target.value }))}
            placeholder="your@email.com"
            autoComplete="off"
          />
        </div>

        <div>
          <label className="block text-xs text-gray-400 mb-1">Password</label>
          <input
            type="password"
            className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-gray-200 text-sm focus:outline-none focus:border-blue-500"
            value={cfg.password}
            onChange={(e) => setCfg((c) => ({ ...c, password: e.target.value }))}
            placeholder={cfg.configured ? '•••••• (unchanged)' : 'App password'}
            autoComplete="new-password"
          />
        </div>

        <div>
          <label className="block text-xs text-gray-400 mb-1">From Address</label>
          <input
            className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-gray-200 text-sm focus:outline-none focus:border-blue-500"
            value={cfg.from_email}
            onChange={(e) => setCfg((c) => ({ ...c, from_email: e.target.value }))}
            placeholder="noreply@yourdomain.com"
          />
        </div>

        {msg && (
          <div className={`text-xs px-3 py-2 rounded-lg ${
            msg.type === 'success' ? 'bg-green-900/30 text-green-400' : 'bg-red-900/30 text-red-400'
          }`}>
            {msg.text}
          </div>
        )}

        <div className="flex gap-2">
          <button
            type="submit"
            disabled={saving}
            className="btn-primary flex-1"
          >
            {saving ? 'Saving…' : 'Save Settings'}
          </button>
          <button
            type="button"
            onClick={handleTest}
            disabled={testing || !cfg.configured}
            className="px-4 py-2 bg-gray-700 text-gray-200 text-sm rounded-lg hover:bg-gray-600 transition-colors disabled:opacity-40"
            title={!cfg.configured ? 'Configure and save SMTP first' : 'Send test email to your admin address'}
          >
            {testing ? 'Sending…' : 'Test'}
          </button>
        </div>
      </form>
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

  const handleToggleRole = async (user: UserResponse) => {
    const newRole = user.role === 'admin' ? 'monitor' : 'admin'
    try {
      const updated = await authPatchUser(user.id, { role: newRole })
      setUsers((prev) => prev.map((u) => (u.id === updated.id ? updated : u)))
    } catch {
      setAddMsg({ type: 'error', text: 'Failed to update role.' })
    }
  }

  const handleToggleActive = async (user: UserResponse) => {
    try {
      const updated = await authPatchUser(user.id, { is_active: !user.is_active })
      setUsers((prev) => prev.map((u) => (u.id === updated.id ? updated : u)))
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setAddMsg({ type: 'error', text: msg ?? 'Failed to update status.' })
    }
  }

  const handleDelete = async (id: number, email: string) => {
    if (!confirm(`Delete user ${email}? This cannot be undone.`)) return
    try {
      await authDeleteUser(id)
      setUsers((prev) => prev.filter((u) => u.id !== id))
    } catch {
      setAddMsg({ type: 'error', text: 'Failed to delete user.' })
    }
  }

  return (
    <div className="card space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="font-semibold text-white">Operator Accounts</h3>
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
              maxLength={120}
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
              minLength={8}
              maxLength={128}
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-white text-sm"
              placeholder="Min 8 characters"
            />
            <FieldHelp example="min 8 chars" hint="User can change after first login" />
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
            className="flex items-start justify-between py-2 px-3 rounded-lg bg-gray-800/50 border border-gray-700/50"
          >
            <div className="min-w-0 flex-1">
              <p className={`text-sm truncate ${u.is_active ? 'text-gray-200' : 'text-gray-500 line-through'}`}>
                {u.email}
              </p>
              <p className="text-xs text-gray-600 mt-0.5">
                Joined {new Date(u.created_at).toLocaleDateString()}
              </p>
            </div>
            <div className="flex items-center gap-1 ml-2 flex-shrink-0">
              {/* Role badge / toggle */}
              <button
                onClick={() => handleToggleRole(u)}
                title={`Click to make ${u.role === 'admin' ? 'Monitor' : 'Admin'}`}
                className={`text-xs px-2 py-0.5 rounded-full border transition-colors ${
                  u.role === 'admin'
                    ? 'bg-blue-900/30 text-blue-400 border-blue-700/40 hover:bg-red-900/30 hover:text-red-400 hover:border-red-700/40'
                    : 'bg-green-900/30 text-green-400 border-green-700/40 hover:bg-blue-900/30 hover:text-blue-400 hover:border-blue-700/40'
                }`}
              >
                {u.role}
              </button>
              {/* Active toggle */}
              <button
                onClick={() => handleToggleActive(u)}
                title={u.is_active ? 'Deactivate account' : 'Activate account'}
                className={`text-xs px-2 py-0.5 rounded-full border transition-colors ${
                  u.is_active
                    ? 'bg-gray-700/50 text-gray-400 border-gray-600/40 hover:bg-red-900/30 hover:text-red-400 hover:border-red-700/40'
                    : 'bg-red-900/30 text-red-500 border-red-700/40 hover:bg-green-900/30 hover:text-green-400 hover:border-green-700/40'
                }`}
              >
                {u.is_active ? 'Active' : 'Inactive'}
              </button>
              {/* Delete */}
              <button
                onClick={() => handleDelete(u.id, u.email)}
                className="text-xs text-gray-600 hover:text-red-400 transition-colors px-1"
                title="Delete user permanently"
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
