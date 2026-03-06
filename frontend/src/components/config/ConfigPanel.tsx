import { useState, useEffect } from 'react'
import {
  getPedestals,
  setMode,
  getSimulatorStatus,
  startSimulator,
  stopSimulator,
  updatePedestal as apiUpdatePedestal,
} from '../../api'
import { useStore } from '../../store'
import type { Pedestal } from '../../store'
import RealPedestalModal from './RealPedestalModal'
import DiagnosticsModal from './DiagnosticsModal'

export default function ConfigPanel() {
  const { setPedestals, updatePedestal } = useStore()
  const [pedestals, setPedestalsList] = useState<Pedestal[]>([])
  const [selectedId, setSelectedId]   = useState<number | null>(null)
  const [simRunning, setSimRunning]   = useState(false)
  const [loading, setLoading]         = useState(false)
  const [message, setMessage]         = useState<{ type: 'success' | 'error'; text: string } | null>(null)

  // Modal state — track which pedestal opened which modal
  const [showRealModal, setShowRealModal]     = useState(false)
  const [showDiagnostics, setShowDiagnostics] = useState(false)

  useEffect(() => {
    getPedestals().then((data) => {
      setPedestalsList(data)
      setPedestals(data)
      if (data.length > 0) setSelectedId(data[0].id)
    })
  }, [])

  // Poll simulator status for selected pedestal
  useEffect(() => {
    if (!selectedId) return
    const refresh = () =>
      getSimulatorStatus(selectedId)
        .then((s) => setSimRunning(s.running))
        .catch(() => {})
    refresh()
    const iv = setInterval(refresh, 5000)
    return () => clearInterval(iv)
  }, [selectedId])

  const selected = pedestals.find((p) => p.id === selectedId)

  // ─── Handlers ────────────────────────────────────────────────────────────────

  const handleStartSimulator = async () => {
    if (!selectedId) return
    setLoading(true)
    setMessage(null)
    try {
      const res = await startSimulator(selectedId)
      setSimRunning(res.running)
      const fresh = await getPedestals()
      setPedestalsList(fresh)
      setPedestals(fresh)
      setMessage({ type: 'success', text: 'Simulator started — synthetic data flowing.' })
    } catch {
      setMessage({ type: 'error', text: 'Failed to start simulator.' })
    } finally {
      setLoading(false)
    }
  }

  const handleStopSimulator = async () => {
    if (!selectedId) return
    setLoading(true)
    setMessage(null)
    try {
      const res = await stopSimulator(selectedId)
      setSimRunning(res.running)
      const fresh = await getPedestals()
      setPedestalsList(fresh)
      setPedestals(fresh)
      setMessage({ type: 'success', text: 'Simulator stopped for this pedestal.' })
    } catch {
      setMessage({ type: 'error', text: 'Failed to stop simulator.' })
    } finally {
      setLoading(false)
    }
  }

  const handleModeSelect = (newMode: 'synthetic' | 'real') => {
    if (!selected) return
    if (newMode === 'real') {
      setShowRealModal(true)
    } else {
      handleStartSimulator()
    }
  }

  const handleSaveReal = async (pedestalIp: string, cameraIp: string) => {
    if (!selectedId) return
    setShowRealModal(false)
    setLoading(true)
    setMessage(null)
    try {
      let updated = await setMode(selectedId, 'real', pedestalIp || undefined)
      if (cameraIp !== (updated.camera_ip ?? '')) {
        updated = await apiUpdatePedestal(selectedId, { camera_ip: cameraIp || undefined })
      }
      updatePedestal(updated)
      setPedestalsList((prev) => prev.map((p) => (p.id === updated.id ? updated : p)))
      setSimRunning(false)
      setMessage({ type: 'success', text: 'Real pedestal mode set. Run diagnostics to initialize.' })
      setShowDiagnostics(true)
    } catch {
      setMessage({ type: 'error', text: 'Failed to set real pedestal mode.' })
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

  const mode = selected?.data_mode ?? 'real'

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
        <h3 className="text-lg font-semibold text-white">Pedestal Mode Settings</h3>

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
              <div className="flex items-center gap-3">
                <p>
                  Mode:{' '}
                  <span className={mode === 'synthetic' ? 'text-blue-400' : 'text-green-400'}>
                    {mode === 'synthetic' ? 'Simulator' : 'Real Pedestal'}
                  </span>
                </p>
                {mode === 'real' && (
                  <span className={`text-xs px-2 py-0.5 rounded-full border ${
                    selected.initialized
                      ? 'bg-green-900/30 text-green-400 border-green-700/40'
                      : 'bg-amber-900/30 text-amber-400 border-amber-700/40'
                  }`}>
                    {selected.initialized ? '● Initialized' : '○ Not initialized'}
                  </span>
                )}
              </div>
            </div>

            {/* ─── Data source mode ─────────────────────────────────────────── */}
            <div>
              <label className="block text-sm text-gray-400 mb-2">Data Source</label>
              <div className="flex gap-3">
                <ModeOption
                  label="Simulator"
                  description="Python simulator generates synthetic data"
                  selected={mode === 'synthetic'}
                  onSelect={() => handleModeSelect('synthetic')}
                />
                <ModeOption
                  label="Real Pedestal"
                  description="Connect to physical Arduino Opta via MQTT"
                  selected={mode === 'real'}
                  onSelect={() => handleModeSelect('real')}
                />
              </div>
            </div>

            {/* ─── Simulator controls ───────────────────────────────────────── */}
            {mode === 'synthetic' && (
              <div className="space-y-3">
                <div className="flex items-center gap-2 text-sm">
                  <span className={`w-2 h-2 rounded-full ${simRunning ? 'bg-green-400 animate-pulse' : 'bg-gray-600'}`} />
                  <span className="text-gray-400">Simulator:</span>
                  <span className={simRunning ? 'text-green-400' : 'text-gray-500'}>
                    {simRunning ? 'Running' : 'Stopped'}
                  </span>
                </div>
                <div className="flex gap-2">
                  <button
                    className="flex-1 btn-primary"
                    onClick={handleStartSimulator}
                    disabled={loading || simRunning}
                  >
                    {loading ? 'Starting…' : 'Start Simulator'}
                  </button>
                  <button
                    className="flex-1 px-3 py-2 rounded-lg bg-red-900/40 border border-red-700/40 text-red-400 text-sm font-medium hover:bg-red-900/60 transition-colors disabled:opacity-40"
                    onClick={handleStopSimulator}
                    disabled={loading || !simRunning}
                  >
                    {loading ? 'Stopping…' : 'Stop Simulator'}
                  </button>
                </div>
              </div>
            )}

            {/* ─── Real pedestal controls ───────────────────────────────────── */}
            {mode === 'real' && (
              <div className="space-y-3">
                {selected.ip_address && (
                  <div className="text-sm space-y-1">
                    <p className="text-gray-500">
                      Pedestal IP: <span className="font-mono text-gray-300">{selected.ip_address}</span>
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
                    className="flex-1 px-3 py-2 rounded-lg border border-gray-700 text-gray-300 text-sm hover:bg-gray-800 transition-colors"
                  >
                    Edit Connection
                  </button>
                  <button
                    onClick={() => setShowDiagnostics(true)}
                    className="flex-1 px-3 py-2 rounded-lg bg-blue-700 hover:bg-blue-600 text-white text-sm font-medium transition-colors"
                  >
                    Run Diagnostics
                  </button>
                </div>
              </div>
            )}

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

// ─── Mode option button ────────────────────────────────────────────────────────

function ModeOption({
  label, description, selected, onSelect,
}: {
  label: string
  description: string
  selected: boolean
  onSelect: () => void
}) {
  return (
    <button
      onClick={onSelect}
      className={`flex-1 text-left p-3 rounded-lg border transition-colors ${
        selected
          ? 'border-blue-600 bg-blue-900/20 text-white'
          : 'border-gray-700 bg-gray-800 text-gray-400 hover:border-gray-600'
      }`}
    >
      <div className="flex items-center gap-2 mb-1">
        <div className={`w-3 h-3 rounded-full border-2 ${selected ? 'border-blue-400 bg-blue-400' : 'border-gray-500'}`} />
        <span className="font-medium text-sm">{label}</span>
      </div>
      <p className="text-xs text-gray-500 ml-5">{description}</p>
    </button>
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
