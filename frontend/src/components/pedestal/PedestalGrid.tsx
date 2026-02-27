import { useEffect } from 'react'
import { useStore } from '../../store'
import PedestalCard from './PedestalCard'
import { getPedestalHealth } from '../../api/pedestalConfig'

export default function PedestalGrid() {
  const {
    pedestals, pendingSessions, activeSessions, setSelectedPedestalId,
    pedestalHealth, setPedestalHealth,
  } = useStore()

  const totalPending = pendingSessions.length
  const totalActive  = activeSessions.length

  useEffect(() => {
    getPedestalHealth()
      .then(setPedestalHealth)
      .catch(() => {})
  }, [])

  return (
    <div>
      {/* Fleet summary bar */}
      <div className="flex items-center gap-4 mb-6 p-4 bg-gray-900 rounded-xl border border-gray-800">
        <div className="flex-1">
          <p className="text-sm text-gray-400">Fleet Overview</p>
          <p className="text-white font-semibold">{pedestals.length} Pedestal{pedestals.length !== 1 ? 's' : ''} monitored</p>
        </div>
        <div className="flex gap-4">
          <Stat label="Pending" value={totalPending} color="amber" pulse={totalPending > 0} />
          <Stat label="Active"  value={totalActive}  color="green" />
          <Stat label="Total"   value={totalPending + totalActive} color="blue" />
        </div>
      </div>

      {/* Pedestal cards grid */}
      {pedestals.length === 0 ? (
        <div className="card text-center py-12 text-gray-500">
          <p>No pedestals configured.</p>
          <p className="text-sm mt-1">Go to Settings → set number of pedestals → Apply.</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
          {pedestals.map((p) => (
            <PedestalCard
              key={p.id}
              pedestal={p}
              health={pedestalHealth[p.id] ?? null}
              onClick={() => setSelectedPedestalId(p.id)}
            />
          ))}
        </div>
      )}
    </div>
  )
}

function Stat({ label, value, color, pulse }: {
  label: string
  value: number
  color: 'amber' | 'green' | 'blue'
  pulse?: boolean
}) {
  const colors = {
    amber: 'text-amber-400',
    green: 'text-green-400',
    blue:  'text-blue-400',
  }
  return (
    <div className={`text-center ${pulse ? 'animate-pulse' : ''}`}>
      <p className={`text-2xl font-bold ${colors[color]}`}>{value}</p>
      <p className="text-xs text-gray-500">{label}</p>
    </div>
  )
}
