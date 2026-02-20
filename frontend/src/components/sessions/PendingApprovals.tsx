import { useStore } from '../../store'
import { allowSession, denySession } from '../../api'

export default function PendingApprovals() {
  const { pendingSessions, updateSession } = useStore()

  if (pendingSessions.length === 0) return null

  return (
    <div className="mb-6">
      <h2 className="text-lg font-semibold text-amber-400 mb-3 flex items-center gap-2">
        <span className="animate-pulse">●</span>
        Pending Approvals ({pendingSessions.length})
      </h2>
      <div className="space-y-3">
        {pendingSessions.map((s) => (
          <PendingCard
            key={s.id}
            session={s}
            onAllow={async () => {
              const updated = await allowSession(s.id)
              updateSession({ id: updated.id, status: 'active' })
            }}
            onDeny={async () => {
              const updated = await denySession(s.id)
              updateSession({ id: updated.id, status: 'denied' })
            }}
          />
        ))}
      </div>
    </div>
  )
}

function PendingCard({
  session,
  onAllow,
  onDeny,
}: {
  session: { id: number; type: string; socket_id: number | null; started_at: string }
  onAllow: () => void
  onDeny: () => void
}) {
  return (
    <div className="card border-amber-700/50 flex items-center gap-4">
      <div className="flex-1">
        <p className="font-medium text-white">
          {session.type === 'electricity' ? `Socket ${session.socket_id}` : 'Water Meter'}
        </p>
        <p className="text-xs text-gray-400">
          {session.type === 'electricity' ? 'Plug detected' : 'Water flow detected'} •{' '}
          {new Date(session.started_at).toLocaleTimeString()}
        </p>
      </div>
      <div className="flex gap-2">
        <button className="btn-success text-sm" onClick={onAllow}>
          Allow
        </button>
        <button className="btn-danger text-sm" onClick={onDeny}>
          Deny
        </button>
      </div>
    </div>
  )
}
