import { useStore } from '../../store'
import { stopSession } from '../../api'

interface WaterCardProps {
  pedestalId: number
}

export default function WaterCard({ pedestalId }: WaterCardProps) {
  const { pendingSessions, activeSessions, waterLiveData, updateSession } = useStore()

  const pendingSession = pendingSessions.find(
    (s) => s.pedestal_id === pedestalId && s.type === 'water'
  )
  const activeSession = activeSessions.find(
    (s) => s.pedestal_id === pedestalId && s.type === 'water'
  )

  const handleStop = async () => {
    if (!activeSession) return
    const updated = await stopSession(activeSession.id)
    updateSession({ id: updated.id, status: 'completed' })
  }

  return (
    <div className={`card ${activeSession ? 'border-cyan-700/50' : pendingSession ? 'border-amber-700/50' : 'border-gray-800'}`}>
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <div className={`w-3 h-3 rounded-full ${activeSession ? 'bg-cyan-400' : pendingSession ? 'bg-amber-400 animate-pulse' : 'bg-gray-600'}`} />
          <span className="font-semibold text-white">Water Meter</span>
        </div>
        <span
          className={
            activeSession ? 'badge bg-cyan-900/50 text-cyan-300 border border-cyan-700' : pendingSession ? 'badge-pending' : 'badge bg-gray-800 text-gray-500'
          }
        >
          {activeSession ? 'Flowing' : pendingSession ? 'Pending' : 'Idle'}
        </span>
      </div>

      {activeSession && waterLiveData && (
        <div className="mb-3 space-y-1">
          <div className="flex justify-between text-sm">
            <span className="text-gray-400">Flow rate</span>
            <span className="text-white font-mono font-bold">{waterLiveData.lpm.toFixed(1)} L/min</span>
          </div>
          <div className="flex justify-between text-sm">
            <span className="text-gray-400">Total</span>
            <span className="text-gray-300 font-mono">{waterLiveData.total_liters.toFixed(2)} L</span>
          </div>
        </div>
      )}

      {pendingSession && !activeSession && (
        <div className="mb-3">
          <p className="text-sm text-amber-400">Session starting…</p>
        </div>
      )}

      {!pendingSession && !activeSession && (
        <p className="text-sm text-gray-500 mb-3">No water flow detected</p>
      )}

      {activeSession && (
        <button className="btn-warning text-sm w-full" onClick={handleStop}>
          Stop Session
        </button>
      )}
    </div>
  )
}
