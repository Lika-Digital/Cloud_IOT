import { useEffect } from 'react'
import { useStore } from '../store'
import { getPedestals, getPendingSessions, getActiveSessions } from '../api'
import PedestalGrid from '../components/pedestal/PedestalGrid'
import PedestalView from '../components/pedestal/PedestalView'

export default function Dashboard() {
  const {
    pedestals,
    setPedestals,
    setPendingSessions,
    setActiveSessions,
    selectedPedestalId,
    setSelectedPedestalId,
  } = useStore()

  useEffect(() => {
    getPedestals().then(setPedestals)
    getPendingSessions().then(setPendingSessions)
    getActiveSessions().then(setActiveSessions)
  }, [])

  const selectedPedestal = pedestals.find((p) => p.id === selectedPedestalId)

  return (
    <div>
      {/* Header */}
      <div className="flex items-center gap-3 mb-6">
        {selectedPedestalId !== null && (
          <button
            onClick={() => setSelectedPedestalId(null)}
            className="btn-ghost text-sm flex items-center gap-2"
          >
            ← Back
          </button>
        )}
        <div>
          <h1 className="text-2xl font-bold text-white">
            {selectedPedestal ? selectedPedestal.name : 'Dashboard'}
          </h1>
          <p className="text-gray-400 text-sm mt-0.5">
            {selectedPedestal
              ? `${selectedPedestal.location ?? ''} · Mode: `
              : 'Select a pedestal to manage sessions'}
            {selectedPedestal && (
              <span className={selectedPedestal.data_mode === 'synthetic' ? 'text-blue-400' : 'text-green-400'}>
                {selectedPedestal.data_mode}
              </span>
            )}
          </p>
        </div>
      </div>

      {/* View: grid overview or single pedestal detail */}
      {selectedPedestalId === null ? (
        <PedestalGrid />
      ) : (
        <PedestalView pedestalId={selectedPedestalId} />
      )}
    </div>
  )
}
