import { useEffect } from 'react'
import { useStore } from '../store'
import { getPedestals, getPendingSessions, getActiveSessions } from '../api'
import PedestalView from '../components/pedestal/PedestalView'

export default function Dashboard() {
  const { pedestals, setPedestals, setPendingSessions, setActiveSessions, pendingSessions, activeSessions } = useStore()

  useEffect(() => {
    getPedestals().then(setPedestals)
    getPendingSessions().then(setPendingSessions)
    getActiveSessions().then(setActiveSessions)
  }, [])

  const pedestal = pedestals[0]

  return (
    <div>
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-white">Dashboard</h1>
          {pedestal && (
            <p className="text-gray-400 text-sm mt-0.5">
              {pedestal.name} · {pedestal.location} · Mode:{' '}
              <span className={pedestal.data_mode === 'synthetic' ? 'text-blue-400' : 'text-green-400'}>
                {pedestal.data_mode}
              </span>
            </p>
          )}
        </div>

        {/* Live session counts */}
        <div className="flex gap-3">
          {pendingSessions.length > 0 && (
            <span className="badge-pending text-sm px-3 py-1">
              {pendingSessions.length} Pending
            </span>
          )}
          {activeSessions.length > 0 && (
            <span className="badge-active text-sm px-3 py-1">
              {activeSessions.length} Active
            </span>
          )}
        </div>
      </div>

      {/* Pedestal interactive view */}
      {pedestal ? (
        <PedestalView />
      ) : (
        <div className="card text-center py-12 text-gray-500">
          <p>No pedestal configured.</p>
          <p className="text-sm mt-1">Go to Settings to get started.</p>
        </div>
      )}
    </div>
  )
}
