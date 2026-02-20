import { useState, useEffect } from 'react'
import { useStore, type Session } from '../../store'
import { stopSession } from '../../api'

export default function ActiveSessions() {
  const { activeSessions, updateSession } = useStore()

  if (activeSessions.length === 0) return null

  return (
    <div className="mb-6">
      <h2 className="text-lg font-semibold text-green-400 mb-3">
        Active Sessions ({activeSessions.length})
      </h2>
      <div className="space-y-3">
        {activeSessions.map((s) => (
          <ActiveCard
            key={s.id}
            session={s}
            onStop={async () => {
              const updated = await stopSession(s.id)
              updateSession({ id: updated.id, status: 'completed' })
            }}
          />
        ))}
      </div>
    </div>
  )
}

function ActiveCard({ session, onStop }: { session: Session; onStop: () => void }) {
  const { socketLiveData, waterLiveData } = useStore()
  const liveData = session.socket_id !== null ? socketLiveData[session.socket_id] : null

  return (
    <div className="card border-green-700/50">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-3 h-3 rounded-full bg-green-400 animate-pulse" />
          <div>
            <p className="font-medium text-white">
              {session.type === 'electricity' ? `Socket ${session.socket_id}` : 'Water Meter'}
            </p>
            <p className="text-xs text-gray-400">
              Session #{session.id} • Started {new Date(session.started_at).toLocaleTimeString()}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-6">
          {session.type === 'electricity' && liveData && (
            <>
              <Metric label="Power" value={`${liveData.watts.toFixed(0)} W`} />
              <Metric label="Energy" value={`${liveData.kwh_total.toFixed(4)} kWh`} />
            </>
          )}
          {session.type === 'water' && waterLiveData && (
            <>
              <Metric label="Flow" value={`${waterLiveData.lpm.toFixed(1)} L/min`} />
              <Metric label="Total" value={`${waterLiveData.total_liters.toFixed(1)} L`} />
            </>
          )}
          <ElapsedTimer startedAt={session.started_at} />
          <button className="btn-warning text-sm" onClick={onStop}>
            Stop
          </button>
        </div>
      </div>
    </div>
  )
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="text-right">
      <p className="text-xs text-gray-400">{label}</p>
      <p className="font-mono font-bold text-white">{value}</p>
    </div>
  )
}

function ElapsedTimer({ startedAt }: { startedAt: string }) {
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
    <div className="text-right">
      <p className="text-xs text-gray-400">Duration</p>
      <p className="font-mono font-bold text-white">
        {fmt(h)}:{fmt(m)}:{fmt(s)}
      </p>
    </div>
  )
}
