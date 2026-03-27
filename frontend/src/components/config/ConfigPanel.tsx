import { useState, useEffect } from 'react'
import {
  getPedestals,
  updatePedestal as apiUpdatePedestal,
} from '../../api'
import { useStore } from '../../store'
import type { Pedestal } from '../../store'
import RealPedestalModal from './RealPedestalModal'
import DiagnosticsModal from './DiagnosticsModal'
import HelpBubble from '../ui/HelpBubble'

export default function ConfigPanel() {
  const { setPedestals, updatePedestal } = useStore()
  const [pedestals, setPedestalsList] = useState<Pedestal[]>([])
  const [selectedId, setSelectedId]   = useState<number | null>(null)
  const [loading, setLoading]         = useState(false)
  const [message, setMessage]         = useState<{ type: 'success' | 'error'; text: string } | null>(null)

  const [showRealModal, setShowRealModal]     = useState(false)
  const [showDiagnostics, setShowDiagnostics] = useState(false)

  useEffect(() => {
    getPedestals().then((data) => {
      setPedestalsList(data)
      setPedestals(data)
      if (data.length > 0) setSelectedId(data[0].id)
    })
  }, [])

  const selected = pedestals.find((p) => p.id === selectedId)

  const handleSaveReal = async (pedestalIp: string, cameraIp: string) => {
    if (!selectedId) return
    setShowRealModal(false)
    setLoading(true)
    setMessage(null)
    try {
      let updated = await apiUpdatePedestal(selectedId, { ip_address: pedestalIp || undefined })
      if (cameraIp !== (updated.camera_ip ?? '')) {
        updated = await apiUpdatePedestal(selectedId, { camera_ip: cameraIp || undefined })
      }
      updatePedestal(updated)
      setPedestalsList((prev) => prev.map((p) => (p.id === updated.id ? updated : p)))
      setMessage({ type: 'success', text: 'Pedestal connection saved. Run diagnostics to initialize.' })
      setShowDiagnostics(true)
    } catch {
      setMessage({ type: 'error', text: 'Failed to save pedestal connection.' })
    } finally {
      setLoading(false)
    }
  }

  const handleDiagnosticsClosed = (initialized: boolean) => {
    setShowDiagnostics(false)
    if (initialized && selectedId) {
      getPedestals().then((data) => {
        setPedestalsList(data)
        setPedestals(data)
      })
      setMessage({ type: 'success', text: 'Pedestal initialized and ready to use.' })
    }
  }

  const handleToggle = async (field: 'mobile_enabled' | 'ai_enabled') => {
    if (!selectedId || !selected) return
    const newVal = !selected[field]
    try {
      const updated = await apiUpdatePedestal(selectedId, { [field]: newVal })
      updatePedestal(updated)
      setPedestalsList((prev) => prev.map((p) => (p.id === updated.id ? updated : p)))
    } catch {
      setMessage({ type: 'error', text: `Failed to update ${field === 'mobile_enabled' ? 'mobile access' : 'AI integration'}.` })
    }
  }

  return (
    <>
      {showRealModal && selected && (
        <RealPedestalModal
          pedestalName={selected.name}
          initialPedestalIp={selected.ip_address ?? ''}
          initialCameraIp={selected.camera_ip ?? ''}
          mqttBroker="localhost:1883"
          onSave={handleSaveReal}
          onCancel={() => setShowRealModal(false)}
        />
      )}

      {showDiagnostics && selected && (
        <DiagnosticsModal
          pedestalId={selected.id}
          pedestalName={selected.name}
          onClose={handleDiagnosticsClosed}
        />
      )}

      <div className="card space-y-5 max-w-lg">
        <h3 className="text-lg font-semibold text-white">Pedestal Settings</h3>

        {/* Pedestal selector */}
        {pedestals.length > 1 && (
          <div>
            <label className="block text-sm text-gray-400 mb-1">Select Pedestal</label>
            <select
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white"
              value={selectedId ?? ''}
              onChange={(e) => setSelectedId(Number(e.target.value))}
            >
              {pedestals.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name} — {p.location ?? 'No location'}
                </option>
              ))}
            </select>
          </div>
        )}

        {selected && (
          <>
            {/* Current pedestal info */}
            <div className="text-sm text-gray-400 space-y-1">
              <p>Name: <span className="text-gray-200">{selected.name}</span></p>
              <p>Location: <span className="text-gray-200">{selected.location ?? '—'}</span></p>
              <div className="flex items-center gap-2">
                <span className={`text-xs px-2 py-0.5 rounded-full border ${
                  selected.initialized
                    ? 'bg-green-900/30 text-green-400 border-green-700/40'
                    : 'bg-amber-900/30 text-amber-400 border-amber-700/40'
                }`}>
                  {selected.initialized ? '● Initialized' : '○ Not initialized'}
                </span>
                <HelpBubble text={
                  selected.initialized
                    ? 'Hardware has been verified. The system confirmed MQTT communication with the Arduino and all sensors responded to a diagnostics request.'
                    : 'Hardware not yet verified.\n\nThis means the Arduino has not yet responded to a diagnostics request over MQTT. Once the Arduino is connected and MQTT is working, click "Run Diagnostics" to verify the connection and mark this pedestal as initialized.'
                } />
              </div>
            </div>

            {/* ─── Connection info ──────────────────────────────────────────── */}
            <div className="space-y-3">
              {selected.ip_address && (
                <div className="text-sm space-y-1">
                  <p className="text-gray-500">
                    Arduino IP: <span className="font-mono text-gray-300">{selected.ip_address}</span>
                  </p>
                  {selected.camera_ip && (
                    <p className="text-gray-500">
                      Camera IP: <span className="font-mono text-gray-300">{selected.camera_ip}</span>
                    </p>
                  )}
                </div>
              )}
              <div className="flex gap-2">
                <button
                  onClick={() => setShowRealModal(true)}
                  disabled={loading}
                  className="flex-1 px-3 py-2 rounded-lg border border-gray-700 text-gray-300 text-sm hover:bg-gray-800 transition-colors disabled:opacity-40"
                >
                  Edit Connection
                </button>
                <div className="flex-1 flex items-center gap-1.5">
                  <button
                    onClick={() => setShowDiagnostics(true)}
                    disabled={loading}
                    className="flex-1 px-3 py-2 rounded-lg bg-blue-700 hover:bg-blue-600 text-white text-sm font-medium transition-colors disabled:opacity-40"
                  >
                    Run Diagnostics
                  </button>
                  <HelpBubble text={
                    'Tests MQTT communication with the Arduino OPTA.\n\n' +
                    'Sends a diagnostics request and waits for the Arduino to reply with readings from all 8 sensors: sockets 1–4, water meter, temperature, moisture, and camera.\n\n' +
                    'Use this after the Arduino is powered on and connected to confirm everything is working. A successful run marks the pedestal as Initialized.'
                  } />
                </div>
              </div>
            </div>

            {/* ─── Access Settings ──────────────────────────────────────────── */}
            <div>
              <p className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-3">Access Settings</p>
              <div className="space-y-2">
                <AccessToggle
                  label="Mobile App Access"
                  description="Expose this pedestal to customers in the mobile app"
                  enabled={selected.mobile_enabled}
                  onToggle={() => handleToggle('mobile_enabled')}
                />
                <AccessToggle
                  label="AI Integration"
                  description="Enable AI monitoring and automated decisions for this pedestal"
                  enabled={selected.ai_enabled}
                  onToggle={() => handleToggle('ai_enabled')}
                />
              </div>
            </div>

            {message && (
              <div className={`text-sm px-3 py-2 rounded-lg ${
                message.type === 'success' ? 'bg-green-900/30 text-green-400' : 'bg-red-900/30 text-red-400'
              }`}>
                {message.text}
              </div>
            )}
          </>
        )}
      </div>
    </>
  )
}

// ─── Access toggle ─────────────────────────────────────────────────────────────

function AccessToggle({
  label, description, enabled, onToggle,
}: {
  label: string
  description: string
  enabled: boolean
  onToggle: () => void
}) {
  return (
    <div className="flex items-center justify-between px-3 py-2.5 rounded-lg bg-gray-800/60 border border-gray-700/50">
      <div className="min-w-0 flex-1 mr-3">
        <p className="text-sm text-gray-200">{label}</p>
        <p className="text-xs text-gray-500 mt-0.5">{description}</p>
      </div>
      <button
        onClick={onToggle}
        className={`relative flex-shrink-0 w-11 h-6 rounded-full transition-colors duration-200 focus:outline-none ${
          enabled ? 'bg-blue-600' : 'bg-gray-600'
        }`}
        aria-pressed={enabled}
      >
        <span
          className={`absolute top-0.5 left-0.5 w-5 h-5 rounded-full bg-white shadow transition-transform duration-200 ${
            enabled ? 'translate-x-5' : 'translate-x-0'
          }`}
        />
      </button>
    </div>
  )
}
