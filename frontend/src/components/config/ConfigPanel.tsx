import { useState, useEffect } from 'react'
import { getPedestals, setMode, getSimulatorStatus, updatePedestal as apiUpdatePedestal } from '../../api'
import { useStore } from '../../store'
import type { Pedestal } from '../../store'
import RealPedestalModal from './RealPedestalModal'
import DiagnosticsModal from './DiagnosticsModal'
import FieldHelp from './FieldHelp'

export default function ConfigPanel() {
  const { setPedestals, updatePedestal } = useStore()
  const [pedestals, setPedestalsList] = useState<Pedestal[]>([])
  const [selectedId, setSelectedId]   = useState<number | null>(null)
  const [mode, setModeState]          = useState<'synthetic' | 'real'>('synthetic')
  const [simRunning, setSimRunning]   = useState(false)
  const [loading, setLoading]         = useState(false)
  const [message, setMessage]         = useState<{ type: 'success' | 'error'; text: string } | null>(null)

  // Modal state
  const [showRealModal, setShowRealModal]           = useState(false)
  const [showDiagnostics, setShowDiagnostics]       = useState(false)

  useEffect(() => {
    getPedestals().then((data) => {
      setPedestalsList(data)
      setPedestals(data)
      if (data.length > 0) {
        setSelectedId(data[0].id)
        setModeState(data[0].data_mode as 'synthetic' | 'real')
      }
    })
  }, [])

  useEffect(() => {
    if (!selectedId) return
    getSimulatorStatus(selectedId).then((s) => setSimRunning(s.running)).catch(() => {})
    const interval = setInterval(() => {
      getSimulatorStatus(selectedId).then((s) => setSimRunning(s.running)).catch(() => {})
    }, 5000)
    return () => clearInterval(interval)
  }, [selectedId])

  // ─── Mode button click ───────────────────────────────────────────────────

  const handleModeSelect = (newMode: 'synthetic' | 'real') => {
    setModeState(newMode)
    if (newMode === 'real') {
      // Open configuration modal immediately
      setShowRealModal(true)
    }
  }

  // ─── Apply synthetic ─────────────────────────────────────────────────────

  const handleApplySynthetic = async () => {
    if (!selectedId) return
    setLoading(true)
    setMessage(null)
    try {
      const updated = await setMode(selectedId, 'synthetic')
      updatePedestal(updated)
      setPedestalsList((prev) => prev.map((p) => (p.id === updated.id ? updated : p)))
      const s = await getSimulatorStatus(selectedId)
      setSimRunning(s.running)
      setMessage({ type: 'success', text: 'Synthetic mode activated — simulator started.' })
    } catch {
      setMessage({ type: 'error', text: 'Failed to apply settings.' })
    } finally {
      setLoading(false)
    }
  }

  // ─── Save real pedestal (from modal) ─────────────────────────────────────

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
      setMessage({ type: 'success', text: 'Real pedestal mode set. Run diagnostics to initialize.' })
      // Auto-open diagnostics
      setShowDiagnostics(true)
    } catch {
      setMessage({ type: 'error', text: 'Failed to connect to real pedestal.' })
      setModeState('synthetic')
    } finally {
      setLoading(false)
    }
  }

  // ─── Diagnostics closed ───────────────────────────────────────────────────

  const handleDiagnosticsClosed = (initialized: boolean) => {
    setShowDiagnostics(false)
    if (initialized && selectedId) {
      // Refresh pedestal data from store
      getPedestals().then((data) => {
        setPedestalsList(data)
        setPedestals(data)
      })
      setMessage({ type: 'success', text: 'Pedestal initialized and ready to use.' })
    }
  }

  const selected = pedestals.find((p) => p.id === selectedId)

  return (
    <>
      {/* Real Pedestal configuration modal */}
      {showRealModal && selected && (
        <RealPedestalModal
          pedestalName={selected.name}
          initialPedestalIp={selected.ip_address ?? ''}
          initialCameraIp={selected.camera_ip ?? ''}
          mqttBroker="localhost:1883"
          onSave={handleSaveReal}
          onCancel={() => { setShowRealModal(false); setModeState('synthetic') }}
        />
      )}

      {/* Diagnostics modal */}
      {showDiagnostics && selected && (
        <DiagnosticsModal
          pedestalId={selected.id}
          pedestalName={selected.name}
          onClose={handleDiagnosticsClosed}
        />
      )}

      <div className="card space-y-5 max-w-lg">
        <h3 className="text-lg font-semibold text-white">Pedestal Configuration</h3>

        {/* Pedestal selector */}
        {pedestals.length > 1 && (
          <div>
            <label className="block text-sm text-gray-400 mb-1">Select Pedestal</label>
            <select
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white"
              value={selectedId ?? ''}
              onChange={(e) => {
                const id = Number(e.target.value)
                setSelectedId(id)
                const p = pedestals.find((x) => x.id === id)
                if (p) setModeState(p.data_mode as 'synthetic' | 'real')
              }}
            >
              {pedestals.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name} — {p.location ?? 'No location'}
                </option>
              ))}
            </select>
          </div>
        )}

        {/* Current pedestal info */}
        {selected && (
          <div className="text-sm text-gray-400 space-y-1">
            <p>Name: <span className="text-gray-200">{selected.name}</span></p>
            <p>Location: <span className="text-gray-200">{selected.location ?? '—'}</span></p>
            <div className="flex items-center gap-3">
              <p>
                Mode:{' '}
                <span className={selected.data_mode === 'synthetic' ? 'text-blue-400' : 'text-green-400'}>
                  {selected.data_mode}
                </span>
              </p>
              {selected.data_mode === 'real' && (
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
        )}

        {/* Mode selector */}
        <div>
          <label className="block text-sm text-gray-400 mb-2">Data Source Mode</label>
          <div className="flex gap-3">
            <ModeOption
              label="Synthetic Data"
              description="Python simulator generates realistic data"
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

        {/* Simulator status (synthetic mode) */}
        {mode === 'synthetic' && (
          <div className="flex items-center gap-2 text-sm">
            <span className={`w-2 h-2 rounded-full ${simRunning ? 'bg-green-400 animate-pulse' : 'bg-gray-600'}`} />
            <span className="text-gray-400">Simulator: </span>
            <span className={simRunning ? 'text-green-400' : 'text-gray-500'}>
              {simRunning ? 'Running' : 'Stopped'}
            </span>
          </div>
        )}

        {/* Real mode — connection summary + diagnostics button */}
        {mode === 'real' && selected && (
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

        {message && (
          <div className={`text-sm px-3 py-2 rounded-lg ${
            message.type === 'success' ? 'bg-green-900/30 text-green-400' : 'bg-red-900/30 text-red-400'
          }`}>
            {message.text}
          </div>
        )}

        {/* Apply button (synthetic only — real applies via modal) */}
        {mode === 'synthetic' && (
          <button className="btn-primary w-full" onClick={handleApplySynthetic} disabled={loading}>
            {loading ? 'Applying…' : 'Apply — Start Simulator'}
          </button>
        )}
      </div>
    </>
  )
}

// ─── Mode option button ───────────────────────────────────────────────────────

function ModeOption({
  label,
  description,
  selected,
  onSelect,
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
