import { useStore, type Pedestal } from '../../store'

interface PedestalCardProps {
  pedestal: Pedestal
  onClick: () => void
}

export default function PedestalCard({ pedestal, onClick }: PedestalCardProps) {
  const { pendingSessions, activeSessions } = useStore()

  const pending = pendingSessions.filter((s) => s.pedestal_id === pedestal.id)
  const active  = activeSessions.filter((s) => s.pedestal_id === pedestal.id)

  const hasPending = pending.length > 0
  const hasActive  = active.length > 0

  return (
    <button
      onClick={onClick}
      className={`card text-left w-full transition-all duration-200 hover:scale-[1.02] hover:border-blue-600/50 active:scale-[0.98]
        ${hasPending ? 'border-amber-600/50' : hasActive ? 'border-green-600/50' : 'border-gray-800'}
      `}
    >
      {/* Header */}
      <div className="flex items-start justify-between mb-4">
        <div>
          <h3 className="font-bold text-white text-lg">{pedestal.name}</h3>
          <p className="text-gray-500 text-sm">{pedestal.location ?? '—'}</p>
        </div>
        <span className={`text-xs px-2 py-1 rounded-full border
          ${pedestal.data_mode === 'synthetic'
            ? 'bg-blue-900/30 text-blue-400 border-blue-700/40'
            : 'bg-green-900/30 text-green-400 border-green-700/40'
          }`}
        >
          {pedestal.data_mode}
        </span>
      </div>

      {/* Symbolic pedestal icon */}
      <div className="flex justify-center mb-4">
        <PedestalIcon pending={hasPending} active={hasActive} />
      </div>

      {/* Session counts */}
      <div className="grid grid-cols-2 gap-2">
        <SessionBadge
          count={pending.length}
          label="Pending"
          color={hasPending ? 'amber' : 'gray'}
          pulse={hasPending}
        />
        <SessionBadge
          count={active.length}
          label="Active"
          color={hasActive ? 'green' : 'gray'}
        />
      </div>

      {/* CTA */}
      {(hasPending || hasActive) && (
        <p className="text-xs text-blue-400 mt-3 text-center">
          Click to manage →
        </p>
      )}
    </button>
  )
}

function PedestalIcon({ pending, active }: { pending: boolean; active: boolean }) {
  const color = pending ? '#f59e0b' : active ? '#22c55e' : '#4b5563'
  const glow  = pending
    ? 'drop-shadow(0 0 8px rgba(245,158,11,0.6))'
    : active
    ? 'drop-shadow(0 0 8px rgba(34,197,94,0.6))'
    : 'none'

  return (
    <svg
      width="72" height="120"
      viewBox="0 0 72 120"
      fill="none"
      style={{ filter: glow }}
    >
      {/* Pedestal body */}
      <rect x="18" y="4" width="36" height="100" rx="4" fill="#1f2937" stroke={color} strokeWidth="2" />
      {/* Top panel */}
      <rect x="24" y="10" width="24" height="16" rx="2" fill="#374151" stroke={color} strokeWidth="1" />
      {/* 4 socket indicators */}
      <circle cx="12" cy="50" r="7" fill={active ? '#22c55e' : pending ? '#f59e0b' : '#374151'} stroke={color} strokeWidth="1.5" />
      <circle cx="12" cy="68" r="7" fill={active ? '#22c55e' : pending ? '#f59e0b' : '#374151'} stroke={color} strokeWidth="1.5" />
      <circle cx="60" cy="50" r="7" fill={active ? '#22c55e' : pending ? '#f59e0b' : '#374151'} stroke={color} strokeWidth="1.5" />
      <circle cx="60" cy="68" r="7" fill={active ? '#22c55e' : pending ? '#f59e0b' : '#374151'} stroke={color} strokeWidth="1.5" />
      {/* Water pipes */}
      <rect x="2" y="95" width="16" height="6" rx="3" fill="#374151" stroke="#6b7280" strokeWidth="1" />
      <rect x="54" y="95" width="16" height="6" rx="3" fill="#374151" stroke="#6b7280" strokeWidth="1" />
      {/* Base */}
      <rect x="14" y="104" width="44" height="8" rx="3" fill="#374151" stroke={color} strokeWidth="1" />
    </svg>
  )
}

function SessionBadge({
  count, label, color, pulse,
}: {
  count: number
  label: string
  color: 'amber' | 'green' | 'gray'
  pulse?: boolean
}) {
  const styles = {
    amber: 'bg-amber-900/30 text-amber-300 border-amber-700/40',
    green: 'bg-green-900/30 text-green-300 border-green-700/40',
    gray:  'bg-gray-800/50 text-gray-500 border-gray-700/40',
  }

  return (
    <div className={`rounded-lg border px-3 py-2 text-center ${styles[color]} ${pulse ? 'animate-pulse' : ''}`}>
      <p className={`text-xl font-bold ${color === 'gray' ? 'text-gray-600' : ''}`}>{count}</p>
      <p className="text-xs">{label}</p>
    </div>
  )
}
