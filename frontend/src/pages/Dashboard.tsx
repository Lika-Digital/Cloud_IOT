import { useEffect } from 'react'
import { useStore } from '../store'
import { getPedestals, getPendingSessions, getActiveSessions } from '../api'
import SocketCard from '../components/pedestal/SocketCard'
import WaterCard from '../components/pedestal/WaterCard'
import PendingApprovals from '../components/sessions/PendingApprovals'
import ActiveSessions from '../components/sessions/ActiveSessions'

const SOCKET_IDS = [1, 2, 3, 4]

export default function Dashboard() {
  const { pedestals, setPedestals, setPendingSessions, setActiveSessions } = useStore()

  useEffect(() => {
    getPedestals().then(setPedestals)
    getPendingSessions().then(setPendingSessions)
    getActiveSessions().then(setActiveSessions)
  }, [])

  const pedestal = pedestals[0]

  return (
    <div>
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
      </div>

      {/* Pending approvals banner */}
      <PendingApprovals />

      {/* Active sessions */}
      <ActiveSessions />

      {/* Socket grid */}
      {pedestal ? (
        <>
          <h2 className="text-lg font-semibold text-gray-300 mb-3">Electricity Sockets</h2>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
            {SOCKET_IDS.map((id) => (
              <SocketCard key={id} socketId={id} pedestalId={pedestal.id} />
            ))}
          </div>

          <h2 className="text-lg font-semibold text-gray-300 mb-3">Water</h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <WaterCard pedestalId={pedestal.id} />
          </div>
        </>
      ) : (
        <div className="card text-center py-12 text-gray-500">
          <p>No pedestal configured. Go to Settings to get started.</p>
        </div>
      )}
    </div>
  )
}
