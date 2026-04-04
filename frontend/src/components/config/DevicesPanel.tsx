import { useState, useEffect } from 'react'
import { getPedestals } from '../../api'
import HelpBubble from '../ui/HelpBubble'
import type { Pedestal } from '../../store'
import {
  getPedestalConfig,
  updatePedestalConfig,
  scanAllDevices,
  type PedestalConfigData,
  type DiscoveredCamera,
} from '../../api/pedestalConfig'

// ─── Status dot ───────────────────────────────────────────────────────────────

function StatusDot({ ok, label }: { ok: boolean; label?: string }) {
  return (
    <span className="flex items-center gap-1.5">
      <span className={`w-2 h-2 rounded-full flex-shrink-0 ${ok ? 'bg-green-400 animate-pulse' : 'bg-gray-600'}`} />
      <span className={`text-xs ${ok ? 'text-green-400' : 'text-gray-500'}`}>
        {label ?? (ok ? 'Connected' : 'Not connected')}
      </span>
    </span>
  )
}

// ─── Device card wrapper ───────────────────────────────────────────────────────

function DeviceCard({ icon, title, status, children }: {
  icon: string
  title: string
  status: React.ReactNode
  children: React.ReactNode
}) {
  return (
    <div className="rounded-lg border border-gray-700 bg-gray-800/40 overflow-hidden">
      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-700/60 bg-gray-800/60">
        <div className="flex items-center gap-2">
          <span className="text-lg">{icon}</span>
          <span className="font-medium text-white text-sm">{title}</span>
        </div>
        {status}
      </div>
      <div className="p-4 space-y-3">{children}</div>
    </div>
  )
}

// ─── Field ─────────────────────────────────────────────────────────────────────

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="block text-xs text-gray-400 mb-1">{label}</label>
      {children}
    </div>
  )
}

function TextInput({ value, onChange, placeholder, type = 'text' }: {
  value: string
  onChange: (v: string) => void
  placeholder?: string
  type?: string
}) {
  return (
    <input
      type={type}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      className="w-full bg-gray-900 border border-gray-700 rounded-lg px-3 py-1.5 text-gray-200 text-sm focus:outline-none focus:border-blue-500"
    />
  )
}

// ─── Discovered badge ──────────────────────────────────────────────────────────

function DiscoveredBadge({ item, onAssign }: {
  item: DiscoveredCamera
  onAssign: () => void
}) {
  return (
    <div className="flex items-center justify-between px-3 py-2 rounded-lg bg-blue-900/20 border border-blue-700/40">
      <div>
        <p className="text-sm text-blue-300 font-medium">{item.name}</p>
        <p className="text-xs text-blue-400/70">{item.onvif_url}</p>
      </div>
      <button
        onClick={onAssign}
        className="ml-3 flex-shrink-0 text-xs px-3 py-1.5 rounded-lg bg-blue-600 hover:bg-blue-500 text-white transition-colors"
      >
        Assign
      </button>
    </div>
  )
}

// ─── Main component ────────────────────────────────────────────────────────────

export default function DevicesPanel() {
  const [pedestals, setPedestalsList] = useState<Pedestal[]>([])
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [cfg, setCfg] = useState<PedestalConfigData | null>(null)

  // Editable fields
  const [optaClientId, setOptaClientId]   = useState('')
  const [mqttUser, setMqttUser]           = useState('')
  const [mqttPass, setMqttPass]           = useState('')
  const [cameraIp, setCameraIp]           = useState('')
  const [cameraUser, setCameraUser]       = useState('')
  const [cameraPass, setCameraPass]       = useState('')
  const [showCameraPass, setShowCameraPass] = useState(false)

  // Auto-computed RTSP URL — derived from ip + user + pass
  const computedRtspUrl = cameraIp && cameraUser && cameraPass
    ? `rtsp://${cameraUser}:${cameraPass}@${cameraIp}:554/profile1`
    : null
  const maskedRtspUrl = cameraIp && cameraUser
    ? `rtsp://${cameraUser}:${'●'.repeat(10)}@${cameraIp}:554/profile1`
    : ''

  // Scan state
  const [scanning, setScanning]           = useState(false)
  const [scanResult, setScanResult]       = useState<{ cameras: DiscoveredCamera[] } | null>(null)
  const [scanMsg, setScanMsg]             = useState('')

  const [saving, setSaving]               = useState(false)
  const [saveMsg, setSaveMsg]             = useState<{ type: 'success' | 'error'; text: string } | null>(null)

  // Load pedestals on mount
  useEffect(() => {
    getPedestals().then((data) => {
      setPedestalsList(data)
      if (data.length > 0) setSelectedId(data[0].id)
    })
  }, [])

  // Load config when pedestal selected
  useEffect(() => {
    if (!selectedId) return
    getPedestalConfig(selectedId).then((c) => {
      setCfg(c)
      setOptaClientId(c.opta_client_id ?? '')
      setMqttUser(c.mqtt_username ?? '')
      setMqttPass(c.mqtt_password ?? '')
      setCameraIp(c.camera_fqdn ?? '')
      setCameraUser(c.camera_username ?? '')
      // Backend masks password as "***" — load as empty so user knows to re-enter
      setCameraPass(c.camera_password && c.camera_password !== '***' ? c.camera_password : '')
      setScanResult(null)
      setScanMsg('')
      setSaveMsg(null)
    }).catch(() => {})
  }, [selectedId])

  const handleScan = async () => {
    setScanning(true)
    setScanResult(null)
    setScanMsg('Scanning network… (ONVIF multicast + subnet HTTP probe, ~5s)')
    try {
      const result = await scanAllDevices()
      setScanResult(result)
      setScanMsg(
        result.cameras.length === 0
          ? `No cameras found on ${result.subnet}.0/24. Use manual entry below.`
          : `Found ${result.cameras.length} camera(s) on ${result.subnet}.0/24`
      )
    } catch {
      setScanMsg('Scan failed. Check network connection.')
    } finally {
      setScanning(false)
    }
  }

  const assignCamera = (cam: DiscoveredCamera) => {
    setCameraIp(cam.ip)
    setScanMsg('Camera assigned. Enter username and password then click Save.')
  }

  const handleSave = async () => {
    if (!selectedId) return
    setSaving(true)
    setSaveMsg(null)
    try {
      await updatePedestalConfig(selectedId, {
        opta_client_id:       optaClientId    || undefined,
        mqtt_username:        mqttUser         || undefined,
        mqtt_password:        mqttPass         || undefined,
        camera_fqdn:          cameraIp         || undefined,
        // Only send the computed URL when we have all three credentials
        camera_stream_url:    computedRtspUrl  || undefined,
        camera_username:      cameraUser        || undefined,
        // Empty password = keep existing (user didn't re-enter it)
        camera_password:      cameraPass        || undefined,
      })
      // Refresh cfg to get updated health/status
      const fresh = await getPedestalConfig(selectedId)
      setCfg(fresh)
      setSaveMsg({ type: 'success', text: 'Device configuration saved.' })
    } catch {
      setSaveMsg({ type: 'error', text: 'Failed to save configuration.' })
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="card space-y-5">
      <h3 className="text-lg font-semibold text-white">Device Configuration</h3>

      {/* Pedestal selector */}
      {pedestals.length > 1 && (
        <div>
          <label className="block text-sm text-gray-400 mb-1">Pedestal</label>
          <select
            className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white"
            value={selectedId ?? ''}
            onChange={(e) => setSelectedId(Number(e.target.value))}
          >
            {pedestals.map((p) => (
              <option key={p.id} value={p.id}>{p.name} — {p.location ?? 'No location'}</option>
            ))}
          </select>
        </div>
      )}

      {/* ── Network Scan ─────────────────────────────────────────────────────── */}
      <div className="rounded-lg border border-gray-700 bg-gray-800/30 p-4 space-y-3">
        <div className="flex items-center justify-between">
          <div className="flex items-start gap-2">
            <div>
              <p className="text-sm font-medium text-white">Auto-Discovery</p>
              <p className="text-xs text-gray-500 mt-0.5">
                Scans LAN for ONVIF cameras
              </p>
            </div>
            <HelpBubble text={
              'Scans your local network (LAN) to automatically find IP cameras.\n\n' +
              '📷 Cameras — sends an ONVIF WS-Discovery UDP multicast to detect any ONVIF-compatible IP camera (e.g. D-Link DCS-TF2283AI-DL).\n\n' +
              'Scan takes up to 5 seconds. Found cameras appear below with an Assign button to fill in the RTSP URL automatically.\n\n' +
              'Use manual entry below if auto-discovery does not find your camera.'
            } />
          </div>
          <button
            onClick={handleScan}
            disabled={scanning}
            className="px-4 py-2 rounded-lg bg-blue-700 hover:bg-blue-600 text-white text-sm font-medium transition-colors disabled:opacity-50 flex items-center gap-2"
          >
            {scanning && <span className="w-3 h-3 rounded-full border-2 border-white border-t-transparent animate-spin" />}
            {scanning ? 'Scanning…' : 'Scan Network'}
          </button>
        </div>

        {scanMsg && (
          <p className={`text-xs px-3 py-2 rounded-lg ${
            scanMsg.includes('No devices') || scanMsg.includes('failed')
              ? 'bg-yellow-900/20 text-yellow-400 border border-yellow-700/30'
              : 'bg-blue-900/20 text-blue-400 border border-blue-700/30'
          }`}>
            {scanMsg}
          </p>
        )}

        {/* Discovered cameras */}
        {scanResult && scanResult.cameras.length > 0 && (
          <div className="space-y-2">
            <p className="text-xs text-gray-500 uppercase tracking-wider">Cameras found</p>
            {scanResult.cameras.map((cam, i) => (
              <DiscoveredBadge key={i} item={cam} onAssign={() => assignCamera(cam)} />
            ))}
          </div>
        )}

      </div>

      {/* ── Arduino OPTA ─────────────────────────────────────────────────────── */}
      <DeviceCard
        icon="⚡"
        title="Arduino OPTA (MQTT)"
        status={<StatusDot ok={cfg?.opta_connected ?? false} label={cfg?.opta_connected ? 'Connected' : 'Not connected'} />}
      >
        <p className="text-xs text-gray-500">
          Arduino connects automatically via MQTT when powered on.
          Client ID is set by the Arduino firmware.
        </p>
        <Field label="MQTT Client ID (optional override)">
          <TextInput value={optaClientId} onChange={setOptaClientId} placeholder="auto-detected from MQTT" />
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="MQTT Username">
            <TextInput value={mqttUser} onChange={setMqttUser} placeholder="leave blank if not set" />
          </Field>
          <Field label="MQTT Password">
            <TextInput value={mqttPass} onChange={setMqttPass} placeholder="leave blank if not set" type="password" />
          </Field>
        </div>
        {cfg?.last_heartbeat && (
          <p className="text-xs text-gray-600">
            Last heartbeat: {new Date(cfg.last_heartbeat).toLocaleString()}
          </p>
        )}
      </DeviceCard>

      {/* ── Camera ───────────────────────────────────────────────────────────── */}
      <DeviceCard
        icon="📷"
        title="IP Camera — D-Link DCS-TF2283AI-DL"
        status={<StatusDot ok={cfg?.camera_reachable ?? false} label={cfg?.camera_reachable ? 'Reachable' : 'Unreachable'} />}
      >
        <Field label="Camera IP / Hostname">
          <TextInput value={cameraIp} onChange={setCameraIp} placeholder="e.g. 192.168.1.192" />
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Username">
            <TextInput value={cameraUser} onChange={setCameraUser} placeholder="admin" />
          </Field>
          <Field label="Password">
            <div className="relative">
              <TextInput value={cameraPass} onChange={setCameraPass} placeholder="enter to set / update" type={showCameraPass ? 'text' : 'password'} />
              <button
                type="button"
                onClick={() => setShowCameraPass((v) => !v)}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-500 hover:text-gray-300 text-sm px-1"
                tabIndex={-1}
              >
                {showCameraPass ? '🙈' : '👁'}
              </button>
            </div>
          </Field>
        </div>
        <Field label="RTSP Stream URL (auto-generated)">
          <div className="relative">
            <input
              type="text"
              readOnly
              value={showCameraPass ? (computedRtspUrl ?? '') : maskedRtspUrl}
              placeholder={
                !cameraIp ? 'Enter IP above' :
                !cameraUser ? 'Enter username above' :
                !cameraPass ? 'Enter password above to generate URL' : ''
              }
              className="w-full bg-gray-900/50 border border-gray-700 rounded-lg px-3 py-1.5 text-gray-400 text-xs font-mono pr-10 cursor-default"
            />
            {maskedRtspUrl && (
              <button
                type="button"
                onClick={() => setShowCameraPass((v) => !v)}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-500 hover:text-gray-300 text-sm px-1"
                tabIndex={-1}
              >
                {showCameraPass ? '🙈' : '👁'}
              </button>
            )}
          </div>
          {!computedRtspUrl && cfg?.camera_stream_url && (
            <p className="text-xs text-gray-600 mt-1">Current saved URL will be kept. Re-enter password to update it.</p>
          )}
        </Field>
        {cfg?.last_camera_check && (
          <p className="text-xs text-gray-600">
            Last check: {new Date(cfg.last_camera_check).toLocaleString()}
          </p>
        )}
      </DeviceCard>

      {/* ── Save ─────────────────────────────────────────────────────────────── */}
      {saveMsg && (
        <div className={`text-sm px-3 py-2 rounded-lg ${
          saveMsg.type === 'success' ? 'bg-green-900/30 text-green-400' : 'bg-red-900/30 text-red-400'
        }`}>
          {saveMsg.text}
        </div>
      )}
      <button
        onClick={handleSave}
        disabled={saving || !selectedId}
        className="btn-primary w-full"
      >
        {saving ? 'Saving…' : 'Save Device Configuration'}
      </button>
    </div>
  )
}
