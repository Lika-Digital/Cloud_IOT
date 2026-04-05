import { useState, useEffect } from 'react'
import type { Pedestal } from '../../store'
import {
  getPedestalConfig,
  updatePedestalConfig,
  addSensor,
  deleteSensor,
  runMdnsScan,
  runSnmpScan,
  type PedestalConfigData,
  type PedestalSensorData,
  type SensorCreate,
  type DiscoveredDevice,
  type SnmpDevice,
} from '../../api/pedestalConfig'

interface Props {
  pedestal: Pedestal
}

export default function PedestalConfigForm({ pedestal }: Props) {
  const [open, setOpen] = useState(false)
  const [cfg, setCfg] = useState<PedestalConfigData | null>(null)
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [msg, setMsg] = useState<{ type: 'success' | 'error'; text: string } | null>(null)

  // Editable fields
  const [siteId, setSiteId] = useState('')
  const [dockId, setDockId] = useState('')
  const [berthRef, setBerthRef] = useState('')
  const [pedestalUid, setPedestalUid] = useState('')
  const [pedestalModel, setPedestalModel] = useState('')
  const [mqttUser, setMqttUser] = useState('')
  const [mqttPass, setMqttPass] = useState('')
  const [optaClientId, setOptaClientId] = useState('')
  const [camUrl, setCamUrl] = useState('')
  const [camFqdn, setCamFqdn] = useState('')
  const [camUser, setCamUser] = useState('')
  const [camPass, setCamPass] = useState('')
  const [sensorMode, setSensorMode] = useState<'auto' | 'manual'>('auto')

  // Sensor management
  const [sensors, setSensors] = useState<PedestalSensorData[]>([])
  const [showAddSensor, setShowAddSensor] = useState(false)
  const [newSensor, setNewSensor] = useState<SensorCreate>({
    sensor_name: '', sensor_type: '', mqtt_topic: '', unit: '',
  })
  const [sensorMsg, setSensorMsg] = useState<string | null>(null)

  // Discovery
  const [mdnsResults, setMdnsResults] = useState<DiscoveredDevice[]>([])
  const [snmpResults, setSnmpResults] = useState<SnmpDevice[]>([])
  const [scanning, setScanning] = useState<'mdns' | 'snmp' | null>(null)
  const [snmpSubnet, setSnmpSubnet] = useState('192.168.1')

  useEffect(() => {
    if (!open) return
    setLoading(true)
    getPedestalConfig(pedestal.id)
      .then((data) => {
        setCfg(data)
        setSiteId(data.site_id ?? '')
        setDockId(data.dock_id ?? '')
        setBerthRef(data.berth_ref ?? '')
        setPedestalUid(data.pedestal_uid ?? '')
        setPedestalModel(data.pedestal_model ?? '')
        setMqttUser(data.mqtt_username ?? '')
        setMqttPass(data.mqtt_password ?? '')
        setOptaClientId(data.opta_client_id ?? '')
        setCamUrl(data.camera_stream_url ?? '')
        setCamFqdn(data.camera_fqdn ?? '')
        setCamUser(data.camera_username ?? '')
        setCamPass(data.camera_password ?? '')
        setSensorMode(data.sensor_config_mode ?? 'auto')
        setSensors(data.sensors)
        setMdnsResults(data.mdns_discovered ?? [])
        setSnmpResults(data.snmp_discovered ?? [])
      })
      .catch(() => setMsg({ type: 'error', text: 'Failed to load config.' }))
      .finally(() => setLoading(false))
  }, [open, pedestal.id])

  const handleSave = async () => {
    setSaving(true)
    setMsg(null)
    try {
      const updated = await updatePedestalConfig(pedestal.id, {
        site_id: siteId || undefined,
        dock_id: dockId || undefined,
        berth_ref: berthRef || undefined,
        pedestal_uid: pedestalUid || undefined,
        pedestal_model: pedestalModel || undefined,
        mqtt_username: mqttUser || undefined,
        mqtt_password: mqttPass || undefined,
        opta_client_id: optaClientId || undefined,
        camera_stream_url: camUrl || undefined,
        camera_fqdn: camFqdn || undefined,
        camera_username: camUser || undefined,
        camera_password: camPass || undefined,
        sensor_config_mode: sensorMode,
      })
      setCfg(updated)
      // Sync camera_stream_url back — backend may have injected credentials
      if (updated.camera_stream_url) setCamUrl(updated.camera_stream_url)
      setMsg({ type: 'success', text: 'Configuration saved.' })
    } catch {
      setMsg({ type: 'error', text: 'Failed to save configuration.' })
    } finally {
      setSaving(false)
    }
  }

  const handleAddSensor = async (e: React.FormEvent) => {
    e.preventDefault()
    setSensorMsg(null)
    try {
      const created = await addSensor(pedestal.id, newSensor)
      setSensors((prev) => [...prev, created])
      setNewSensor({ sensor_name: '', sensor_type: '', mqtt_topic: '', unit: '' })
      setShowAddSensor(false)
    } catch {
      setSensorMsg('Failed to add sensor.')
    }
  }

  const handleDeleteSensor = async (id: number) => {
    if (!confirm('Delete this sensor?')) return
    try {
      await deleteSensor(id)
      setSensors((prev) => prev.filter((s) => s.id !== id))
    } catch {
      setSensorMsg('Failed to delete sensor.')
    }
  }

  const handleMdnsScan = async () => {
    setScanning('mdns')
    try {
      const result = await runMdnsScan(pedestal.id)
      setMdnsResults(result.discovered)
    } catch {
      setMdnsResults([])
    } finally {
      setScanning(null)
    }
  }

  const handleSnmpScan = async () => {
    setScanning('snmp')
    try {
      const result = await runSnmpScan(pedestal.id, snmpSubnet)
      setSnmpResults(result.discovered)
    } catch {
      setSnmpResults([])
    } finally {
      setScanning(null)
    }
  }

  return (
    <div className="border border-gray-700 rounded-xl overflow-hidden">
      {/* Accordion header */}
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center justify-between px-4 py-3 bg-gray-800/60 hover:bg-gray-800 transition-colors text-left"
      >
        <span className="font-medium text-white">
          {pedestal.name}
          <span className="text-gray-500 text-sm ml-2">{pedestal.location}</span>
        </span>
        <span className="text-gray-400 text-lg">{open ? '▲' : '▼'}</span>
      </button>

      {open && (
        <div className="p-4 space-y-6 bg-gray-900/40">
          {loading && <p className="text-sm text-gray-400">Loading…</p>}

          {msg && (
            <div className={`text-sm px-3 py-2 rounded-lg ${
              msg.type === 'success' ? 'bg-green-900/30 text-green-400' : 'bg-red-900/30 text-red-400'
            }`}>
              {msg.text}
            </div>
          )}

          {cfg && !loading && (
            <>
              {/* ── Identifiers ── */}
              <Section title="Identifiers">
                <div className="grid grid-cols-2 gap-3">
                  <Field label="Site ID" value={siteId} onChange={setSiteId} />
                  <Field label="Dock ID" value={dockId} onChange={setDockId} />
                  <Field label="Berth Ref" value={berthRef} onChange={setBerthRef} />
                  <Field label="Pedestal UID" value={pedestalUid} onChange={setPedestalUid} />
                  <div>
                    <label className="block text-xs text-gray-400 mb-1">Model</label>
                    <select
                      value={pedestalModel}
                      onChange={(e) => setPedestalModel(e.target.value)}
                      className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-white text-sm"
                    >
                      <option value="">— Select —</option>
                      <option value="16A">16A</option>
                      <option value="24A">24A</option>
                      <option value="64A">64A</option>
                    </select>
                  </div>
                </div>
              </Section>

              {/* ── MQTT / OPTA ── */}
              <Section title="MQTT / OPTA">
                <div className="grid grid-cols-2 gap-3">
                  <Field label="MQTT Username" value={mqttUser} onChange={setMqttUser} />
                  <Field label="MQTT Password" value={mqttPass} onChange={setMqttPass} type="password" />
                  <Field label="OPTA Client ID" value={optaClientId} onChange={setOptaClientId} />
                </div>
              </Section>

              {/* ── Camera ── */}
              <Section title="Camera">
                <div className="grid grid-cols-2 gap-3">
                  <div className="col-span-2">
                    <Field label="Stream URL" value={camUrl} onChange={setCamUrl} placeholder="rtsp://…" />
                  </div>
                  <Field label="FQDN / Hostname" value={camFqdn} onChange={setCamFqdn} />
                  <Field label="Username" value={camUser} onChange={setCamUser} />
                  <Field label="Password" value={camPass} onChange={setCamPass} type="password" />
                  <div className="col-span-2">
                    <button
                      type="button"
                      onClick={() => {
                        if (!camFqdn) return
                        const host = camFqdn.trim()
                        const creds = camUser ? `${encodeURIComponent(camUser)}${camPass ? ':' + encodeURIComponent(camPass) : ''}@` : ''
                        // Preserve existing path, or default to empty
                        let path = ''
                        try {
                          const existing = new URL(camUrl)
                          path = existing.pathname + existing.search
                        } catch { /* no existing URL */ }
                        setCamUrl(`rtsp://${creds}${host}${path}`)
                      }}
                      className="text-xs text-blue-400 hover:text-blue-300 underline"
                    >
                      Build URL from FQDN + credentials
                    </button>
                  </div>
                </div>
              </Section>

              {/* ── Sensors ── */}
              <Section title="Sensors">
                <div className="flex items-center gap-3 mb-3">
                  <label className="text-sm text-gray-300">Mode:</label>
                  <select
                    value={sensorMode}
                    onChange={(e) => setSensorMode(e.target.value as 'auto' | 'manual')}
                    className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-1 text-white text-sm"
                  >
                    <option value="auto">Auto (MQTT register)</option>
                    <option value="manual">Manual</option>
                  </select>
                </div>

                {sensorMsg && <p className="text-xs text-red-400 mb-2">{sensorMsg}</p>}

                {sensors.length > 0 && (
                  <div className="space-y-1 mb-3">
                    {sensors.map((s) => (
                      <div
                        key={s.id}
                        className="flex items-center justify-between text-xs px-3 py-1.5 bg-gray-800/60 rounded-lg border border-gray-700/50"
                      >
                        <div>
                          <span className="text-gray-200 font-medium">{s.sensor_name}</span>
                          <span className="text-gray-500 ml-2">{s.mqtt_topic}</span>
                          {s.unit && <span className="text-gray-600 ml-1">({s.unit})</span>}
                          <span className={`ml-2 px-1.5 py-0.5 rounded text-xs ${
                            s.source === 'auto_mqtt'
                              ? 'bg-blue-900/30 text-blue-400'
                              : 'bg-gray-700 text-gray-400'
                          }`}>
                            {s.source === 'auto_mqtt' ? 'auto' : 'manual'}
                          </span>
                        </div>
                        <button
                          onClick={() => handleDeleteSensor(s.id)}
                          className="text-gray-600 hover:text-red-400 transition-colors px-1"
                        >
                          ✕
                        </button>
                      </div>
                    ))}
                  </div>
                )}

                {sensorMode === 'manual' && (
                  <>
                    <button
                      onClick={() => setShowAddSensor((v) => !v)}
                      className="text-xs px-3 py-1.5 rounded-lg bg-gray-700 hover:bg-gray-600 text-gray-300 transition-colors"
                    >
                      {showAddSensor ? 'Cancel' : '+ Add Sensor'}
                    </button>

                    {showAddSensor && (
                      <form onSubmit={handleAddSensor} className="mt-3 space-y-2 p-3 bg-gray-800/50 rounded-lg border border-gray-700">
                        <div className="grid grid-cols-2 gap-2">
                          <Field label="Name" value={newSensor.sensor_name}
                            onChange={(v) => setNewSensor((s) => ({ ...s, sensor_name: v }))} />
                          <Field label="Type" value={newSensor.sensor_type}
                            onChange={(v) => setNewSensor((s) => ({ ...s, sensor_type: v }))}
                            placeholder="temperature, moisture…" />
                          <div className="col-span-2">
                            <Field label="MQTT Topic" value={newSensor.mqtt_topic}
                              onChange={(v) => setNewSensor((s) => ({ ...s, mqtt_topic: v }))}
                              placeholder="pedestal/1/sensors/…" />
                          </div>
                          <Field label="Unit" value={newSensor.unit ?? ''}
                            onChange={(v) => setNewSensor((s) => ({ ...s, unit: v }))}
                            placeholder="°C, %, V…" />
                        </div>
                        <button type="submit" className="btn-primary text-xs py-1 px-3">Add Sensor</button>
                      </form>
                    )}
                  </>
                )}
              </Section>

              {/* ── Auto-Discovery ── */}
              <Section title="Auto-Discovery">
                <div className="space-y-3">
                  <div className="flex items-center gap-2">
                    <button
                      onClick={handleMdnsScan}
                      disabled={scanning !== null}
                      className="text-xs px-3 py-1.5 rounded-lg bg-gray-700 hover:bg-gray-600 text-gray-300 disabled:opacity-50 transition-colors"
                    >
                      {scanning === 'mdns' ? 'Scanning…' : 'Scan mDNS (5 s)'}
                    </button>
                    <span className="text-xs text-gray-500">Finds cameras on local network (RTSP/HTTP/ONVIF)</span>
                  </div>

                  {mdnsResults.length > 0 && (
                    <div className="space-y-1">
                      {mdnsResults.map((d, i) => (
                        <div key={i} className="text-xs px-3 py-1.5 bg-gray-800/60 rounded-lg border border-gray-700/50">
                          <span className="text-gray-200 font-medium">{d.name}</span>
                          <span className="text-gray-500 ml-2">{d.address}:{d.port}</span>
                          <span className="text-gray-600 ml-1">({d.type})</span>
                        </div>
                      ))}
                    </div>
                  )}
                  {mdnsResults.length === 0 && scanning !== 'mdns' && cfg.mdns_discovered?.length === 0 && (
                    <p className="text-xs text-gray-600">No mDNS devices found yet. Click Scan to search.</p>
                  )}

                  <div className="flex items-center gap-2">
                    <button
                      onClick={handleSnmpScan}
                      disabled={scanning !== null}
                      className="text-xs px-3 py-1.5 rounded-lg bg-gray-700 hover:bg-gray-600 text-gray-300 disabled:opacity-50 transition-colors"
                    >
                      {scanning === 'snmp' ? 'Scanning…' : 'Scan SNMP'}
                    </button>
                    <input
                      value={snmpSubnet}
                      onChange={(e) => setSnmpSubnet(e.target.value)}
                      placeholder="192.168.1"
                      className="bg-gray-800 border border-gray-700 rounded px-2 py-1 text-white text-xs w-32"
                    />
                    <span className="text-xs text-gray-500">/24 subnet prefix</span>
                  </div>

                  {snmpResults.length > 0 && (
                    <div className="space-y-1">
                      {snmpResults.map((d, i) => (
                        <div key={i} className="text-xs px-3 py-1.5 bg-gray-800/60 rounded-lg border border-gray-700/50">
                          <span className="text-gray-200 font-medium">{d.ip}</span>
                          <span className="text-gray-500 ml-2 truncate">{d.sysDescr}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </Section>

              {/* Save button */}
              <button
                onClick={handleSave}
                disabled={saving}
                className="btn-primary w-full"
              >
                {saving ? 'Saving…' : 'Save Configuration'}
              </button>
            </>
          )}
        </div>
      )}
    </div>
  )
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">{title}</h4>
      {children}
    </div>
  )
}

function Field({
  label, value, onChange, type = 'text', placeholder,
}: {
  label: string
  value: string
  onChange: (v: string) => void
  type?: string
  placeholder?: string
}) {
  return (
    <div>
      <label className="block text-xs text-gray-400 mb-1">{label}</label>
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-white text-sm focus:outline-none focus:border-blue-600"
      />
    </div>
  )
}
