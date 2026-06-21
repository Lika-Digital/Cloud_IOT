import { useState, useEffect } from 'react'
import ConfigPanel from '../components/config/ConfigPanel'
import FieldHelp from '../components/config/FieldHelp'
import DevicesPanel from '../components/config/DevicesPanel'
import { authListUsers, authCreateUser, authDeleteUser, authPatchUser, authResetUser2fa, type UserResponse } from '../api/auth'
import {
  getSmtpConfig, updateSmtpConfig, testSmtp, type SmtpConfig,
  getNetworkInfo, type NetworkInfo,
  getSnmpConfig, updateSnmpConfig, type SnmpConfig,
  getActivePedestals, type ActivePedestalsInfo,
  getPilotAssignments, createPilotAssignment, deletePilotAssignment, type PilotAssignment,
} from '../api/settings'
import {
  exportConfig, getSupportBundle, listBackups, importConfig,
  type BackupMeta, type ConfigBundle, type RestoreReport,
} from '../api/configBackup'
import {
  totpStatus, totpSetup, totpVerifySetup, totpDisable,
  type TotpStatusResponse, type TotpSetupResponse,
} from '../api/auth'

export default function Settings() {
  return (
    <div>
      <h1 className="text-2xl font-bold text-gray-100 mb-6">Settings</h1>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">

        {/* Left column */}
        <div className="space-y-6">

          {/* Pedestal mode config */}
          <ConfigPanel />

          {/* Per-pedestal device configuration */}
          <DevicesPanel />

          {/* SMTP / Communication */}
          <SmtpSettingsPanel />

          {/* User Management */}
          <UserManagementPanel />

          {/* Two-Factor Authentication (TOTP) */}
          <TwoFactorPanel />
        </div>

        {/* Right column — info */}
        <div className="space-y-4">

          {/* Application IP */}
          <NetworkInfoPanel />

          {/* SNMP Trap Config */}
          <SnmpConfigPanel />

          {/* Active MQTT Clients */}
          <ActivePedestalsPanel />

          {/* Pilot Mode Assignments */}
          <PilotModePanel />

          {/* Configuration Backup / Restore */}
          <BackupRestorePanel />

          <div className="card">
            <h3 className="font-semibold text-gray-100 mb-3">Quick Start</h3>
            <ol className="text-sm text-gray-400 space-y-2 list-decimal list-inside">
              <li>Connect the Arduino to the MQTT broker — it sends a <strong className="text-gray-100">register</strong> message automatically</li>
              <li>The pedestal appears on the Dashboard once the first MQTT message is received</li>
              <li>Select the pedestal in <strong className="text-gray-100">Pedestal Settings</strong> (left) to configure camera and connection details</li>
              <li>Click <strong className="text-gray-100">Run Diagnostics</strong> to verify all devices are reachable</li>
              <li>Enable <strong className="text-gray-100">Mobile App Access</strong> to make the pedestal visible in the customer app</li>
              <li>Click socket zones on the Dashboard to Allow / Deny / Stop sessions</li>
            </ol>
          </div>
          <div className="card">
            <h3 className="font-semibold text-gray-100 mb-3">MQTT Topics</h3>
            <div className="space-y-1 text-xs font-mono text-gray-400">

              <p className="text-purple-400 font-semibold mt-1">// Opta firmware (Arduino → NUC)</p>
              <p>opta/status</p>
              <p className="text-gray-600 ml-2">{'{'}"cabinetId":"…","seq":N,"uptime_ms":N{"}"}</p>
              <p className="mt-1">opta/sockets/Q{'{1-4}'}/status</p>
              <p className="text-gray-600 ml-2">{'{'}"cabinetId":"…","state":"idle|active","ts":"…"{"}"}</p>
              <p className="mt-1">opta/sockets/Q{'{1-4}'}/power</p>
              <p className="text-gray-600 ml-2">{'{'}"cabinetId":"…","watts":N,"kwh_total":N{"}"}</p>
              <p className="mt-1">opta/water/V{'{1-2}'}/status</p>
              <p className="text-gray-600 ml-2">{'{'}"cabinetId":"…","state":"idle","total_l":N,"session_l":N{"}"}</p>
              <p className="mt-1">opta/door/status</p>
              <p className="text-gray-600 ml-2">{'{'}"cabinetId":"…","door":"open|closed","ts":"…"{"}"}</p>
              <p className="mt-1">opta/events</p>
              <p className="text-gray-600 ml-2">{'{'}"cabinetId":"…", …event data…{"}"}</p>
              <p className="mt-1">opta/acks</p>
              <p className="text-gray-600 ml-2">{'{'}"cabinetId":"…","cmd":"…","status":"ok|err"{"}"}</p>

              <p className="text-purple-400 font-semibold mt-3">// Opta firmware (NUC → Arduino)</p>
              <p>opta/cmd/socket/Q{'{1-4}'}</p>
              <p className="text-gray-600 ml-2">{'{'}"cabinetId":"…","cmd":"enable|disable|stop"{"}"}</p>
              <p className="mt-1">opta/cmd/water/V{'{1-2}'}</p>
              <p className="text-gray-600 ml-2">{'{'}"cabinetId":"…","cmd":"open|close|stop"{"}"}</p>
              <p className="mt-1">opta/cmd/reset</p>
              <p className="text-gray-600 ml-2">{'{'}"cabinetId":"…","cmd":"reset"{"}"}</p>
              <p className="mt-1">opta/cmd/led</p>
              <p className="text-gray-600 ml-2">{'{'}"cabinetId":"…","color":"red|green|blue|off","state":"on|off|blink"{"}"}</p>

              <p className="text-blue-400 font-semibold mt-3">// Marina cabinet firmware (Arduino → NUC)</p>
              <p>marina/cabinet/{'{cabinetId}'}/status</p>
              <p>marina/cabinet/{'{cabinetId}'}/sockets/{'{socketName}'}/state</p>
              <p>marina/cabinet/{'{cabinetId}'}/water/{'{waterName}'}/state</p>
              <p>marina/cabinet/{'{cabinetId}'}/door/state</p>
              <p>marina/cabinet/{'{cabinetId}'}/events</p>
              <p>marina/cabinet/{'{cabinetId}'}/acks</p>

              <p className="text-blue-400 font-semibold mt-3">// Marina cabinet firmware (NUC → Arduino)</p>
              <p>marina/cabinet/{'{cabinetId}'}/cmd/socket/E{'{1-4}'}</p>
              <p className="text-gray-600 ml-2">{'{'}"cmd":"enable|disable"{"}"}</p>
              <p className="mt-1">marina/cabinet/{'{cabinetId}'}/outlet/PWR-{'{n}'}/cmd/stop</p>
              <p className="mt-1">marina/cabinet/{'{cabinetId}'}/outlet/WTR-{'{n}'}/cmd/stop</p>

              <p className="text-gray-500 font-semibold mt-3">// Legacy (simulator / test tool)</p>
              <p>pedestal/{'{id}'}/socket/{'{1-4}'}/status</p>
              <p>pedestal/{'{id}'}/socket/{'{1-4}'}/power</p>
              <p>pedestal/{'{id}'}/water/flow</p>
              <p>pedestal/{'{id}'}/heartbeat</p>
              <p>pedestal/{'{id}'}/sensors/temperature</p>
              <p>pedestal/{'{id}'}/sensors/moisture</p>
              <p>pedestal/{'{id}'}/diagnostics/response</p>
              <p>pedestal/{'{id}'}/register</p>
              <p className="text-gray-500 mt-1">// Legacy → pedestal</p>
              <p>pedestal/{'{id}'}/socket/{'{1-4}'}/control</p>
              <p>pedestal/{'{id}'}/water/control</p>
            </div>
          </div>
          <div className="card">
            <h3 className="font-semibold text-gray-100 mb-3">User Roles</h3>
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

// ── Pilot Mode Panel ──────────────────────────────────────────────────────────

function PilotModePanel() {
  const [assignments, setAssignments] = useState<PilotAssignment[]>([])
  const [showAdd, setShowAdd] = useState(false)
  const [newUsername, setNewUsername] = useState('')
  const [newPedestalId, setNewPedestalId] = useState('')
  const [newSocketId, setNewSocketId] = useState('1')
  const [saving, setSaving] = useState(false)
  const [msg, setMsg] = useState<{ type: 'success' | 'error'; text: string } | null>(null)

  const load = () => getPilotAssignments().then(setAssignments).catch(() => {})

  useEffect(() => { load() }, [])

  const handleAdd = async (e: React.FormEvent) => {
    e.preventDefault()
    setSaving(true); setMsg(null)
    try {
      const a = await createPilotAssignment({
        username: newUsername.trim(),
        pedestal_id: parseInt(newPedestalId),
        socket_id: parseInt(newSocketId),
      })
      setAssignments((prev) => [...prev, a])
      setNewUsername(''); setNewPedestalId(''); setNewSocketId('1')
      setShowAdd(false)
      setMsg({ type: 'success', text: 'Assignment created.' })
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setMsg({ type: 'error', text: detail ?? 'Failed to create assignment.' })
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async (id: number) => {
    if (!confirm('Remove this pilot assignment?')) return
    try {
      await deletePilotAssignment(id)
      setAssignments((prev) => prev.filter((a) => a.id !== id))
    } catch {
      setMsg({ type: 'error', text: 'Failed to remove assignment.' })
    }
  }

  return (
    <div className="card space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="font-semibold text-gray-100">Pilot Mode Assignments</h3>
        <button
          onClick={() => setShowAdd((v) => !v)}
          className="text-xs px-3 py-1.5 rounded-lg bg-blue-700 hover:bg-blue-600 text-white transition-colors"
        >
          {showAdd ? 'Cancel' : '+ Add'}
        </button>
      </div>
      <p className="text-xs text-gray-400">
        Assign a customer username to a specific pedestal and socket. The customer's mobile app
        will show only that pedestal and require a physical plug-in within 3 minutes before starting.
      </p>

      {msg && (
        <div className={`text-sm px-3 py-2 rounded-lg ${msg.type === 'success' ? 'bg-green-900/30 text-green-400' : 'bg-red-900/30 text-red-400'}`}>
          {msg.text}
        </div>
      )}

      {showAdd && (
        <form onSubmit={handleAdd} className="space-y-3 p-3 bg-gray-800/50 rounded-lg border border-gray-700">
          <h4 className="text-sm font-medium text-gray-300">New Assignment</h4>
          <div>
            <label className="block text-xs text-gray-400 mb-1">Customer Username (name)</label>
            <input
              required
              maxLength={120}
              value={newUsername}
              onChange={(e) => setNewUsername(e.target.value)}
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-gray-100 text-sm"
              placeholder="e.g. John Smith"
            />
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label className="block text-xs text-gray-400 mb-1">Pedestal ID</label>
              <input
                required
                type="number"
                min={1}
                value={newPedestalId}
                onChange={(e) => setNewPedestalId(e.target.value)}
                className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-gray-100 text-sm font-mono"
                placeholder="1"
              />
            </div>
            <div>
              <label className="block text-xs text-gray-400 mb-1">Socket (1–4)</label>
              <select
                value={newSocketId}
                onChange={(e) => setNewSocketId(e.target.value)}
                className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-gray-100 text-sm"
              >
                {[1, 2, 3, 4].map((n) => <option key={n} value={n}>Socket {n}</option>)}
              </select>
            </div>
          </div>
          <button type="submit" disabled={saving} className="btn-primary w-full">
            {saving ? 'Saving…' : 'Create Assignment'}
          </button>
        </form>
      )}

      <div className="space-y-2">
        {assignments.length === 0 && (
          <p className="text-sm text-gray-600 text-center py-2">No pilot assignments configured.</p>
        )}
        {assignments.map((a) => (
          <div key={a.id} className="flex items-center justify-between px-3 py-2 rounded-lg bg-gray-800/50 border border-gray-700/50">
            <div>
              <p className="text-sm text-gray-200 font-medium">{a.username}</p>
              <p className="text-xs text-gray-500 font-mono mt-0.5">
                Pedestal #{a.pedestal_id} · Socket {a.socket_id}
              </p>
            </div>
            <button
              onClick={() => handleDelete(a.id)}
              className="text-xs text-gray-600 hover:text-red-400 transition-colors px-1"
              title="Remove assignment"
            >
              ✕
            </button>
          </div>
        ))}
      </div>
    </div>
  )
}

// ── Active Pedestals Panel ─────────────────────────────────────────────────────

function ActivePedestalsPanel() {
  const [info, setInfo] = useState<ActivePedestalsInfo | null>(null)

  useEffect(() => {
    const load = () => getActivePedestals().then(setInfo).catch(() => {})
    load()
    const t = setInterval(load, 5000)
    return () => clearInterval(t)
  }, [])

  return (
    <div className="card">
      <div className="flex items-center justify-between mb-3">
        <h3 className="font-semibold text-gray-100">Active MQTT Clients</h3>
        {info && (
          <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${
            info.connected > 0
              ? 'bg-green-900/50 text-green-400'
              : 'bg-gray-700 text-gray-400'
          }`}>
            {info.connected} / {info.total} online
          </span>
        )}
      </div>
      <p className="text-xs text-gray-400 mb-3">
        Pedestals are registered automatically when the Arduino sends its first MQTT message.
        The list resets to zero on every application restart.
      </p>
      {!info && <p className="text-sm text-gray-500">Loading…</p>}
      {info && info.total === 0 && (
        <div className="flex items-center gap-2 px-3 py-2.5 rounded-lg bg-gray-800 text-gray-400 text-sm">
          <span className="w-2 h-2 rounded-full bg-gray-600 flex-shrink-0" />
          Waiting for Arduino MQTT connection…
        </div>
      )}
      {info && info.total > 0 && (
        <div className="space-y-1.5">
          {info.pedestals.map((p) => (
            <div key={p.id} className="flex items-center justify-between px-3 py-2 rounded-lg bg-gray-800">
              <div className="flex items-center gap-2">
                <span className={`w-2 h-2 rounded-full flex-shrink-0 ${p.connected ? 'bg-green-400' : 'bg-gray-500'}`} />
                <span className="text-sm text-gray-200">{p.name}</span>
                <span className="text-xs text-gray-500">#{p.id}</span>
              </div>
              <div className="text-right">
                <span className={`text-xs font-medium ${p.connected ? 'text-green-400' : 'text-gray-500'}`}>
                  {p.connected ? 'Online' : 'Offline'}
                </span>
                {p.last_heartbeat && (
                  <p className="text-xs text-gray-600 mt-0.5">
                    {new Date(p.last_heartbeat).toLocaleTimeString()}
                  </p>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ── Network Info Panel ─────────────────────────────────────────────────────────

function NetworkInfoPanel() {
  const [info, setInfo] = useState<NetworkInfo | null>(null)

  useEffect(() => {
    getNetworkInfo().then(setInfo).catch(() => {})
  }, [])

  return (
    <div className="card">
      <h3 className="font-semibold text-gray-100 mb-3">Application Network Address</h3>
      <p className="text-xs text-gray-400 mb-3">
        System IP is the address of this machine. MQTT Broker IP is the broker the application
        is connected to. On a NUC deployment these are the same; on a dev setup they may differ.
      </p>
      {info ? (
        <div className="space-y-2 text-sm">
          <div className="flex justify-between items-center bg-gray-800 rounded-lg px-3 py-2">
            <span className="text-gray-400">System IP</span>
            <span className="font-mono text-blue-400 font-bold text-base">{info.lan_ip}</span>
          </div>
          <div className="flex justify-between items-center bg-gray-800 rounded-lg px-3 py-2">
            <span className="text-gray-400">MQTT Broker IP</span>
            <span className="font-mono text-purple-400 font-bold text-base">{info.mqtt_broker_host}</span>
          </div>
          <div className="flex justify-between items-center bg-gray-800 rounded-lg px-3 py-2">
            <span className="text-gray-400">MQTT Broker port</span>
            <span className="font-mono text-green-400">{info.mqtt_port}</span>
          </div>
          <div className="flex justify-between items-center bg-gray-800 rounded-lg px-3 py-2">
            <span className="text-gray-400">SNMP Trap port</span>
            <span className="font-mono text-yellow-400">{info.snmp_trap_port}</span>
          </div>
        </div>
      ) : (
        <p className="text-sm text-gray-500">Detecting…</p>
      )}
    </div>
  )
}

// ── SNMP Trap Config Panel ─────────────────────────────────────────────────────

function SnmpConfigPanel() {
  const defaultCfg: SnmpConfig = {
    enabled: true, port: 1620, community: 'public',
    temp_oid: '1.3.6.1.4.1.18248.20.1.2.1.1.2.1', pedestal_id: 1,
  }
  const [cfg, setCfg] = useState<SnmpConfig>(defaultCfg)
  const [saving, setSaving] = useState(false)
  const [msg, setMsg]       = useState<{ type: 'success' | 'error'; text: string } | null>(null)

  useEffect(() => {
    getSnmpConfig().then(setCfg).catch(() => {})
  }, [])

  const handleSave = async () => {
    setSaving(true); setMsg(null)
    try {
      await updateSnmpConfig(cfg)
      setMsg({ type: 'success', text: 'SNMP config saved.' })
    } catch {
      setMsg({ type: 'error', text: 'Failed to save SNMP config.' })
    } finally {
      setSaving(false)
    }
  }

  const field = (label: string, value: string | number, key: keyof SnmpConfig, type = 'text') => (
    <div>
      <label className="block text-xs text-gray-400 mb-1">{label}</label>
      <input
        type={type}
        value={value as string}
        onChange={(e) => setCfg({ ...cfg, [key]: type === 'number' ? Number(e.target.value) : e.target.value })}
        className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-gray-100 text-sm font-mono"
      />
    </div>
  )

  return (
    <div className="card">
      <div className="flex items-center justify-between mb-3">
        <h3 className="font-semibold text-gray-100">SNMP Trap Receiver</h3>
        <label className="flex items-center gap-2 text-sm text-gray-400 cursor-pointer">
          <input
            type="checkbox" checked={cfg.enabled}
            onChange={(e) => setCfg({ ...cfg, enabled: e.target.checked })}
            className="accent-blue-500"
          />
          Enabled
        </label>
      </div>
      <p className="text-xs text-gray-400 mb-4">
        Listens for UDP SNMP traps from IP temperature sensors (e.g. Papouch TME).
        Default port 1620 (use 162 with root on NUC).
      </p>
      <div className="space-y-3">
        {field('UDP Listen Port', cfg.port, 'port', 'number')}
        {field('Community String', cfg.community, 'community')}
        {field('Temperature OID', cfg.temp_oid, 'temp_oid')}
        {field('Target Pedestal ID', cfg.pedestal_id, 'pedestal_id', 'number')}
      </div>
      {msg && (
        <div className={`mt-3 text-sm px-3 py-2 rounded-lg ${msg.type === 'success' ? 'bg-green-900/30 text-green-400' : 'bg-red-900/30 text-red-400'}`}>
          {msg.text}
        </div>
      )}
      <button className="btn-primary w-full mt-4" onClick={handleSave} disabled={saving}>
        {saving ? 'Saving…' : 'Save SNMP Config'}
      </button>
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
        <h3 className="font-semibold text-gray-100">Email / SMTP</h3>
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
  const [newRole, setNewRole] = useState<'admin' | 'monitor_control' | 'monitor'>('monitor')
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

  const handleSetRole = async (user: UserResponse, newRole: 'admin' | 'monitor_control' | 'monitor') => {
    if (newRole === user.role) return
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

  // v3.33 — recovery for a lost authenticator: clear the user's TOTP so they
  // re-enrol on their next login (the authenticator is the only second factor).
  const handleReset2fa = async (id: number, email: string) => {
    if (!confirm(`Reset two-factor for ${email}? They will set up a new authenticator on next login.`)) return
    try {
      const updated = await authResetUser2fa(id)
      setUsers((prev) => prev.map((u) => (u.id === updated.id ? updated : u)))
      setAddMsg({ type: 'success', text: `2FA reset for ${email}. They will re-enrol at next login.` })
    } catch {
      setAddMsg({ type: 'error', text: 'Failed to reset 2FA.' })
    }
  }

  return (
    <div className="card space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="font-semibold text-gray-100">Operator Accounts</h3>
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
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-gray-100 text-sm"
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
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-gray-100 text-sm"
              placeholder="Min 8 characters"
            />
            <FieldHelp example="min 8 chars" hint="User can change after first login" />
          </div>
          <div>
            <label className="block text-xs text-gray-400 mb-1">Role</label>
            <select
              value={newRole}
              onChange={(e) => setNewRole(e.target.value as 'admin' | 'monitor_control' | 'monitor')}
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-gray-100 text-sm"
            >
              <option value="monitor">Monitor — read only</option>
              <option value="monitor_control">Monitor &amp; Control — all but System Health / Settings / API Gateway</option>
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
              {/* Role selector (admin / monitor_control / monitor) */}
              <select
                value={u.role}
                onChange={(e) => handleSetRole(u, e.target.value as 'admin' | 'monitor_control' | 'monitor')}
                title="Change this operator's role"
                className={`text-xs px-2 py-0.5 rounded-full border bg-gray-800 transition-colors ${
                  u.role === 'admin'
                    ? 'text-blue-400 border-blue-700/40'
                    : u.role === 'monitor_control'
                      ? 'text-amber-400 border-amber-700/40'
                      : 'text-green-400 border-green-700/40'
                }`}
              >
                <option value="admin">admin</option>
                <option value="monitor_control">monitor &amp; control</option>
                <option value="monitor">monitor</option>
              </select>
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
              {/* Reset 2FA */}
              <button
                onClick={() => handleReset2fa(u.id, u.email)}
                className="text-xs px-2 py-0.5 rounded-full border bg-gray-700/50 text-gray-400 border-gray-600/40 hover:bg-amber-900/30 hover:text-amber-400 hover:border-amber-700/40 transition-colors"
                title="Reset two-factor — user re-enrols authenticator on next login"
              >
                Reset 2FA
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

// ── Two-Factor Authentication (TOTP) Panel ──────────────────────────────────

function TwoFactorPanel() {
  const [status, setStatus] = useState<TotpStatusResponse | null>(null)
  const [setup, setSetup] = useState<TotpSetupResponse | null>(null)
  const [code, setCode] = useState('')
  const [pw, setPw] = useState('')
  const [disableCode, setDisableCode] = useState('')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<{ type: 'success' | 'error'; text: string } | null>(null)

  const load = () => totpStatus().then(setStatus).catch(() => {})
  useEffect(() => { load() }, [])

  const detail = (err: unknown, fb: string) =>
    (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? fb

  const beginSetup = async () => {
    setBusy(true); setMsg(null)
    try { setSetup(await totpSetup()); setCode('') }
    catch (e) { setMsg({ type: 'error', text: detail(e, 'Setup failed.') }) }
    finally { setBusy(false) }
  }

  const verify = async () => {
    setBusy(true); setMsg(null)
    try {
      await totpVerifySetup(code)
      setSetup(null); setCode('')
      setMsg({ type: 'success', text: 'Two-factor authentication enabled.' })
      load()
    } catch (e) { setMsg({ type: 'error', text: detail(e, 'Invalid code — check your phone clock.') }) }
    finally { setBusy(false) }
  }

  const disable = async () => {
    if (!confirm('Disable two-factor authentication for your account?')) return
    setBusy(true); setMsg(null)
    try {
      await totpDisable(pw, disableCode)
      setPw(''); setDisableCode('')
      setMsg({ type: 'success', text: 'Two-factor authentication disabled.' })
      load()
    } catch (e) { setMsg({ type: 'error', text: detail(e, 'Could not disable — check password and code.') }) }
    finally { setBusy(false) }
  }

  const enabled = !!status?.totp_enabled

  return (
    <div className="card space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="font-semibold text-gray-100">Two-Factor Authentication</h3>
        <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${
          enabled ? 'bg-green-900/50 text-green-400' : 'bg-yellow-900/50 text-yellow-400'}`}>
          {enabled ? 'Enabled' : 'Disabled'}
        </span>
      </div>

      {msg && (
        <div className={`text-sm px-3 py-2 rounded-lg ${msg.type === 'success' ? 'bg-green-900/30 text-green-400' : 'bg-red-900/30 text-red-400'}`}>
          {msg.text}
        </div>
      )}

      {enabled ? (
        <>
          <p className="text-xs text-gray-400">
            Authenticator app enabled{status?.totp_verified_at ? ` on ${new Date(status.totp_verified_at).toLocaleDateString()}` : ''}.
          </p>
          <div className="space-y-2 p-3 bg-gray-800/50 rounded-lg border border-gray-700">
            <p className="text-sm text-gray-300">Disable two-factor authentication</p>
            <input type="password" value={pw} onChange={(e) => setPw(e.target.value)} placeholder="Current password"
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-gray-100 text-sm" autoComplete="current-password" />
            <input type="text" inputMode="numeric" maxLength={6} value={disableCode}
              onChange={(e) => setDisableCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
              placeholder="Current 6-digit code"
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-gray-100 text-sm font-mono" />
            <button onClick={disable} disabled={busy || !pw || disableCode.length !== 6}
              className="text-xs px-3 py-1.5 rounded-lg bg-red-700 hover:bg-red-600 text-white disabled:opacity-40">
              {busy ? '…' : 'Disable Two-Factor Authentication'}
            </button>
          </div>
        </>
      ) : setup ? (
        <div className="space-y-3">
          <p className="text-xs text-gray-400">
            Scan with Aegis, Google Authenticator, or Microsoft Authenticator. Then enter the 6-digit code to confirm.
          </p>
          <img src={`data:image/png;base64,${setup.qr_code}`} alt="TOTP QR code"
            className="w-44 h-44 bg-white p-2 rounded-lg mx-auto" />
          <p className="text-xs text-gray-500 text-center">Manual entry key:</p>
          <p className="text-xs font-mono text-gray-300 break-all text-center bg-gray-800 rounded px-2 py-1">{setup.secret}</p>
          <input type="text" inputMode="numeric" maxLength={6} value={code} autoFocus
            onChange={(e) => setCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
            placeholder="000000"
            className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-gray-100 text-center tracking-[0.4em] font-mono" />
          <button onClick={verify} disabled={busy || code.length !== 6} className="btn-primary w-full">
            {busy ? 'Verifying…' : 'Verify and Enable'}
          </button>
        </div>
      ) : (
        <>
          <p className="text-xs text-gray-400">
            Add an authenticator app as your second factor. A backup OTP code is always available via the
            backend log regardless of TOTP status.
          </p>
          <button onClick={beginSetup} disabled={busy} className="btn-primary w-full">
            {busy ? '…' : 'Setup Authenticator'}
          </button>
        </>
      )}

      <p className="text-[11px] text-gray-600">
        TOTP works completely offline — no internet on your phone or the NUC, and no data is sent to any
        external service.
      </p>
    </div>
  )
}


// ── Configuration Backup / Restore Panel ────────────────────────────────────

function downloadJson(obj: unknown, filename: string) {
  const blob = new Blob([JSON.stringify(obj, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

function BackupRestorePanel() {
  const [backups, setBackups] = useState<BackupMeta[]>([])
  const [full, setFull] = useState(false)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<{ type: 'success' | 'error'; text: string } | null>(null)
  const [report, setReport] = useState<RestoreReport | null>(null)

  const load = () => listBackups().then((r) => setBackups(r.backups)).catch(() => {})
  useEffect(() => { load() }, [])

  const stamp = (prefix: string) =>
    `${prefix}_${new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-')}.json`

  const handleExport = async () => {
    setBusy(true); setMsg(null); setReport(null)
    try {
      const bundle = await exportConfig(full)
      downloadJson(bundle, stamp(full ? 'cloud_iot_config_full' : 'cloud_iot_config'))
      setMsg({ type: 'success', text: `Config exported${full ? ' (full — includes secrets)' : ' (redacted)'}.` })
      load()
    } catch {
      setMsg({ type: 'error', text: 'Export failed.' })
    } finally { setBusy(false) }
  }

  const handleSupport = async () => {
    setBusy(true); setMsg(null); setReport(null)
    try {
      const bundle = await getSupportBundle()
      downloadJson(bundle, stamp('support_bundle'))
      setMsg({ type: 'success', text: 'Support bundle downloaded.' })
      load()
    } catch {
      setMsg({ type: 'error', text: 'Support bundle failed.' })
    } finally { setBusy(false) }
  }

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file) return
    if (!confirm(`Restore configuration from "${file.name}"? Config is upserted by natural key; redacted secrets are preserved.`)) return
    setBusy(true); setMsg(null); setReport(null)
    try {
      const bundle = JSON.parse(await file.text()) as ConfigBundle
      const res = await importConfig(bundle)
      setReport(res.report)
      setMsg({ type: 'success', text: 'Configuration restored.' })
      load()
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setMsg({ type: 'error', text: detail ?? 'Restore failed (invalid file?).' })
    } finally { setBusy(false) }
  }

  return (
    <div className="card space-y-4">
      <h3 className="font-semibold text-gray-100">Configuration Backup / Restore</h3>
      <p className="text-xs text-gray-400">
        Export all system configuration to a timestamped JSON file (redacted by default —
        safe to share for troubleshooting). Restore re-applies a saved file.
      </p>

      {msg && (
        <div className={`text-sm px-3 py-2 rounded-lg ${msg.type === 'success' ? 'bg-green-900/30 text-green-400' : 'bg-red-900/30 text-red-400'}`}>
          {msg.text}
        </div>
      )}

      <label className="flex items-center gap-2 text-xs text-gray-400 cursor-pointer">
        <input type="checkbox" checked={full} onChange={(e) => setFull(e.target.checked)} className="accent-blue-500" />
        Full backup — include secrets (passwords, API key). Handle with care.
      </label>

      <div className="grid grid-cols-2 gap-2">
        <button onClick={handleExport} disabled={busy} className="btn-primary">
          {busy ? '…' : 'Download Config'}
        </button>
        <button
          onClick={handleSupport}
          disabled={busy}
          className="px-4 py-2 bg-gray-700 text-gray-200 text-sm rounded-lg hover:bg-gray-600 transition-colors disabled:opacity-40"
        >
          Support Bundle
        </button>
      </div>

      <label className="block">
        <span className="text-xs text-gray-400">Restore from file</span>
        <input
          type="file"
          accept="application/json,.json"
          onChange={handleUpload}
          disabled={busy}
          className="mt-1 block w-full text-xs text-gray-400 file:mr-3 file:py-1.5 file:px-3 file:rounded-lg file:border-0 file:bg-blue-700 file:text-white hover:file:bg-blue-600 file:cursor-pointer"
        />
      </label>

      {report && (
        <div className="text-xs bg-gray-800/60 rounded-lg p-3 space-y-1">
          <p className="text-gray-300 font-medium">Restore report</p>
          {Object.entries(report).map(([k, v]) => (
            <p key={k} className="text-gray-400 font-mono">
              {k}: <span className="text-green-400">{v.updated}</span> updated, {v.inserted} new, {v.skipped} skipped
            </p>
          ))}
        </div>
      )}

      {backups.length > 0 && (
        <div className="space-y-1">
          <p className="text-xs text-gray-500">Saved on NUC ({backups.length}):</p>
          {backups.slice(0, 5).map((b) => (
            <div key={b.filename} className="flex items-center justify-between text-xs text-gray-500 font-mono">
              <span className="truncate">{b.filename}</span>
              <span className="ml-2 flex-shrink-0">{(b.size_bytes / 1024).toFixed(0)} KB</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
