import { useState, useEffect } from 'react'
import { getPedestals, setMode, getSimulatorStatus, updatePedestal as apiUpdatePedestal } from '../../api'
import { useStore } from '../../store'
import type { Pedestal } from '../../store'

export default function ConfigPanel() {
  const { setPedestals, updatePedestal } = useStore()
  const [pedestals, setPedestalsList] = useState<Pedestal[]>([])
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [mode, setModeState] = useState<'synthetic' | 'real'>('synthetic')
  const [ipAddress, setIpAddress] = useState('')
  const [cameraIp, setCameraIp] = useState('')
  const [simRunning, setSimRunning] = useState(false)
  const [loading, setLoading] = useState(false)
  const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null)

  useEffect(() => {
    getPedestals().then((data) => {
      setPedestalsList(data)
      setPedestals(data)
      if (data.length > 0) {
        setSelectedId(data[0].id)
        setModeState(data[0].data_mode as 'synthetic' | 'real')
        setIpAddress(data[0].ip_address ?? '')
        setCameraIp(data[0].camera_ip ?? '')
      }
    })
  }, [])

  useEffect(() => {
    if (!selectedId) return
    getSimulatorStatus(selectedId).then((s) => setSimRunning(s.running)).catch(() => {})

    const interval = setInterval(() => {
      getSimulatorStatus(selectedId)
        .then((s) => setSimRunning(s.running))
        .catch(() => {})
    }, 5000)
    return () => clearInterval(interval)
  }, [selectedId])

  const handleApply = async () => {
    if (!selectedId) return
    setLoading(true)
    setMessage(null)
    try {
      // Set mode (and pedestal IP for real mode)
      let updated = await setMode(selectedId, mode, mode === 'real' ? ipAddress : undefined)

      // Save camera IP separately if changed
      if (cameraIp !== (updated.camera_ip ?? '')) {
        updated = await apiUpdatePedestal(selectedId, { camera_ip: cameraIp || undefined })
      }

      updatePedestal(updated)
      setPedestalsList((prev) => prev.map((p) => (p.id === updated.id ? updated : p)))

      // Refresh sim status
      const s = await getSimulatorStatus(selectedId)
      setSimRunning(s.running)

      setMessage({ type: 'success', text: `Mode set to "${mode}" successfully.` })
    } catch {
      setMessage({ type: 'error', text: 'Failed to apply settings.' })
    } finally {
      setLoading(false)
    }
  }

  const selected = pedestals.find((p) => p.id === selectedId)

  return (
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
              if (p) {
                setModeState(p.data_mode as 'synthetic' | 'real')
                setIpAddress(p.ip_address ?? '')
                setCameraIp(p.camera_ip ?? '')
              }
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

      {selected && (
        <div className="text-sm text-gray-400 space-y-1">
          <p>Name: <span className="text-gray-200">{selected.name}</span></p>
          <p>Location: <span className="text-gray-200">{selected.location ?? '—'}</span></p>
          <p>
            Current mode:{' '}
            <span className={selected.data_mode === 'synthetic' ? 'text-blue-400' : 'text-green-400'}>
              {selected.data_mode}
            </span>
          </p>
        </div>
      )}

      {/* Mode selector */}
      <div>
        <label className="block text-sm text-gray-400 mb-2">Data Source Mode</label>
        <div className="flex gap-3">
          <ModeOption
            value="synthetic"
            label="Synthetic Data"
            description="Python simulator generates realistic data"
            selected={mode === 'synthetic'}
            onSelect={() => setModeState('synthetic')}
          />
          <ModeOption
            value="real"
            label="Real Pedestal"
            description="Connect to physical Arduino Opta"
            selected={mode === 'real'}
            onSelect={() => setModeState('real')}
          />
        </div>
      </div>

      {/* IP address for real mode */}
      {mode === 'real' && (
        <div>
          <label className="block text-sm text-gray-400 mb-1">Pedestal IP Address</label>
          <input
            type="text"
            placeholder="e.g. 192.168.1.10"
            value={ipAddress}
            onChange={(e) => setIpAddress(e.target.value)}
            className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white placeholder-gray-600"
          />
          <p className="text-xs text-gray-500 mt-1">
            Informational only — pedestal connects to the same MQTT broker.
          </p>
        </div>
      )}

      {/* Camera IP — available in both modes */}
      <div>
        <label className="block text-sm text-gray-400 mb-1">Camera IP Address</label>
        <input
          type="text"
          placeholder="e.g. 192.168.1.20"
          value={cameraIp}
          onChange={(e) => setCameraIp(e.target.value)}
          className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white placeholder-gray-600"
        />
        <p className="text-xs text-gray-500 mt-1">
          IP camera for live stream (real mode). In synthetic mode the demo video is used.
        </p>
      </div>

      {/* Simulator status */}
      {mode === 'synthetic' && (
        <div className="flex items-center gap-2 text-sm">
          <span className={`w-2 h-2 rounded-full ${simRunning ? 'bg-green-400 animate-pulse' : 'bg-gray-600'}`} />
          <span className="text-gray-400">Simulator: </span>
          <span className={simRunning ? 'text-green-400' : 'text-gray-500'}>
            {simRunning ? 'Running' : 'Stopped'}
          </span>
        </div>
      )}

      {message && (
        <div className={`text-sm px-3 py-2 rounded-lg ${message.type === 'success' ? 'bg-green-900/30 text-green-400' : 'bg-red-900/30 text-red-400'}`}>
          {message.text}
        </div>
      )}

      <button className="btn-primary" onClick={handleApply} disabled={loading}>
        {loading ? 'Applying…' : 'Apply Settings'}
      </button>
    </div>
  )
}

function ModeOption({
  value,
  label,
  description,
  selected,
  onSelect,
}: {
  value: string
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
