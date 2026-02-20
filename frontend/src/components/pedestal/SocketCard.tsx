import { useState, useEffect } from 'react'
import { useStore } from '../../store'
import { allowSession, denySession, stopSession } from '../../api'

interface SocketCardProps {
  socketId: number
  pedestalId: number
}

export default function SocketCard({ socketId, pedestalId }: SocketCardProps) {
  const { pendingSessions, activeSessions, socketLiveData, updateSession } = useStore()

  const pendingSession = pendingSessions.find(
    (s) => s.pedestal_id === pedestalId && s.socket_id === socketId && s.type === 'electricity'
  )
  const activeSession = activeSessions.find(
    (s) => s.pedestal_id === pedestalId && s.socket_id === socketId && s.type === 'electricity'
  )
  const liveData = socketLiveData[socketId]

  const handleAllow = async () => {
    if (!pendingSession) return
    const updated = await allowSession(pendingSession.id)
    updateSession({ id: updated.id, status: 'active' })
  }

  const handleDeny = async () => {
    if (!pendingSession) return
    const updated = await denySession(pendingSession.id)
    updateSession({ id: updated.id, status: 'denied' })
  }

  const handleStop = async () => {
    if (!activeSession) return
    const updated = await stopSession(activeSession.id)
    updateSession({ id: updated.id, status: 'completed' })
  }

  return (
    <div className={`card ${activeSession ? 'border-green-700/50' : pendingSession ? 'border-amber-700/50' : 'border-gray-800'}`}>
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <div className={`w-3 h-3 rounded-full ${activeSession ? 'bg-green-400' : pendingSession ? 'bg-amber-400 animate-pulse' : 'bg-gray-600'}`} />
          <span className="font-semibold text-white">Socket {socketId}</span>
        </div>
        <span
          className={
            activeSession ? 'badge-active' : pendingSession ? 'badge-pending' : 'badge bg-gray-800 text-gray-500'
          }
        >
          {activeSession ? 'Active' : pendingSession ? 'Pending' : 'Idle'}
        </span>
      </div>

      {/* Live power (active) */}
      {activeSession && liveData && (
        <div className="mb-3 space-y-1">
          <div className="flex justify-between text-sm">
            <span className="text-gray-400">Power</span>
            <span className="text-white font-mono font-bold">{liveData.watts.toFixed(0)} W</span>
          </div>
          <div className="flex justify-between text-sm">
            <span className="text-gray-400">Energy</span>
            <span className="text-gray-300 font-mono">{liveData.kwh_total.toFixed(4)} kWh</span>
          </div>
          <div className="mt-2">
            <SessionTimer startedAt={activeSession.started_at} />
          </div>
        </div>
      )}

      {/* Pending state */}
      {pendingSession && !activeSession && (
        <div className="mb-3">
          <p className="text-sm text-amber-400 mb-2">Plug detected — awaiting approval</p>
          <div className="flex gap-2">
            <button className="btn-success text-sm flex-1" onClick={handleAllow}>
              Allow
            </button>
            <button className="btn-danger text-sm flex-1" onClick={handleDeny}>
              Deny
            </button>
          </div>
        </div>
      )}

      {/* Idle state */}
      {!pendingSession && !activeSession && (
        <p className="text-sm text-gray-500 mb-3">No device connected</p>
      )}

      {/* Stop button when active */}
      {activeSession && (
        <button className="btn-warning text-sm w-full" onClick={handleStop}>
          Stop Session
        </button>
      )}
    </div>
  )
}

function SessionTimer({ startedAt }: { startedAt: string }) {
  const [elapsed, setElapsed] = useState(0)

  useEffect(() => {
    const start = new Date(startedAt).getTime()
    const interval = setInterval(() => {
      setElapsed(Math.floor((Date.now() - start) / 1000))
    }, 1000)
    return () => clearInterval(interval)
  }, [startedAt])

  const h = Math.floor(elapsed / 3600)
  const m = Math.floor((elapsed % 3600) / 60)
  const s = elapsed % 60
  const fmt = (n: number) => String(n).padStart(2, '0')

  return (
    <div className="text-xs text-gray-400">
      Duration: <span className="font-mono text-gray-200">{fmt(h)}:{fmt(m)}:{fmt(s)}</span>
    </div>
  )
}
