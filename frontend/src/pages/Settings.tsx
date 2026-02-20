import { useState, useEffect } from 'react'
import ConfigPanel from '../components/config/ConfigPanel'
import FieldHelp from '../components/config/FieldHelp'
import { getPedestals, configurePedestals } from '../api'
import { useStore } from '../store'

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
        </div>
      </div>
    </div>
  )
}
