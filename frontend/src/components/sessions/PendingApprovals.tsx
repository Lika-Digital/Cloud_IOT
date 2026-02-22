import { useState } from 'react'
import { useStore } from '../../store'
import { allowSession, denySession } from '../../api'
import DenyDialog from './DenyDialog'

export default function PendingApprovals() {
  const { pendingSessions, updateSession } = useStore()
  const [denyingId, setDenyingId] = useState<number | null>(null)

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
            onDenyClick={() => setDenyingId(s.id)}
          />
        ))}
      </div>

      {denyingId !== null && (
        <DenyDialog
          sessionId={denyingId}
          onConfirm={async (reason) => {
            const updated = await denySession(denyingId, reason)
            updateSession({ id: updated.id, status: 'denied', deny_reason: reason ?? null })
            setDenyingId(null)
          }}
          onCancel={() => setDenyingId(null)}
        />
      )}
    </div>
  )
}

function PendingCard({
  session,
  onAllow,
  onDenyClick,
}: {
  session: { id: number; type: string; socket_id: number | null; started_at: string; customer_id: number | null; customer_name?: string | null }
  onAllow: () => void
  onDenyClick: () => void
}) {
  return (
    <div className="card border-amber-700/50 flex items-center gap-4">
      <div className="flex-1">
        <p className="font-medium text-white">
          {session.type === 'electricity' ? `Socket ${session.socket_id}` : 'Water Meter'}
          {session.customer_name && (
            <span className="ml-2 text-sm text-amber-300 font-normal">· {session.customer_name}</span>
          )}
        </p>
        <p className="text-xs text-gray-400">
          {session.type === 'electricity' ? 'Plug connected' : 'Water flow requested'} •{' '}
          {new Date(session.started_at).toLocaleTimeString()}
        </p>
      </div>
      <div className="flex gap-2">
        <button className="btn-success text-sm" onClick={onAllow}>
          Allow
        </button>
        <button className="btn-danger text-sm" onClick={onDenyClick}>
          Deny
        </button>
      </div>
    </div>
  )
}
