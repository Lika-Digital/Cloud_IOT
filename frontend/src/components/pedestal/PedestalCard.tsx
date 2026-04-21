import { useState } from 'react'
import { useStore, type Pedestal, type PedestalHealth } from '../../store'
import { SocketQrGrid } from './SocketQrGrid'
import { getPedestalQrAll } from '../../api'

interface PedestalCardProps {
  pedestal: Pedestal
  health: PedestalHealth | null
  onClick: () => void
}

export default function PedestalCard({ pedestal, health, onClick }: PedestalCardProps) {
  const { pendingSessions, activeSessions, temperatureData, moistureData, addToast } = useStore()
  const [qrOpen, setQrOpen] = useState(false)

  const pending = pendingSessions.filter((s) => s.pedestal_id === pedestal.id)
  const active  = activeSessions.filter((s) => s.pedestal_id === pedestal.id)

  const hasPending = pending.length > 0
  const hasActive  = active.length > 0

  const temp  = temperatureData[pedestal.id]
  const moist = moistureData[pedestal.id]
  const hasAlarm = (temp?.alarm || moist?.alarm) ?? false

  return (
    <>
    <button
      onClick={onClick}
      className={`card text-left w-full transition-all duration-200 hover:scale-[1.02] hover:border-blue-600/50 active:scale-[0.98]
        ${hasAlarm ? 'border-red-600/60' : hasPending ? 'border-amber-600/50' : hasActive ? 'border-green-600/50' : 'border-gray-800'}
      `}
    >
      {/* Header */}
      <div className="flex items-start justify-between mb-4">
        <div className="flex items-center gap-2 min-w-0">
          <div className="min-w-0">
            <h3 className="font-bold text-white text-lg truncate">{pedestal.name}</h3>
            <p className="text-gray-500 text-sm">{pedestal.location ?? '—'}</p>
          </div>
          {/* v3.7 — QR icon: opens the printable-QR grid without navigating
              away from the fleet overview. Only shown when we have a
              cabinet_id to resolve (real pedestals). stopPropagation so
              the surrounding card's onClick doesn't fire. */}
          {health?.opta_client_id && (
            <button
              type="button"
              onClick={(e) => { e.stopPropagation(); setQrOpen(true) }}
              className="text-sm px-1.5 py-0.5 rounded border border-gray-700 text-gray-400 hover:text-white hover:border-blue-500/50"
              title="Show printable QR codes"
              aria-label="Show QR codes"
            >
              🔖
            </button>
          )}
        </div>
        <div className="flex flex-col items-end gap-1">
          <span className={`text-xs px-2 py-1 rounded-full border
            ${pedestal.data_mode === 'synthetic'
              ? 'bg-blue-900/30 text-blue-400 border-blue-700/40'
              : 'bg-green-900/30 text-green-400 border-green-700/40'
            }`}
          >
            {pedestal.data_mode}
          </span>
          {pedestal.data_mode === 'real' && (
            <span className={`text-xs px-2 py-0.5 rounded-full border ${
              pedestal.initialized
                ? 'bg-green-900/30 text-green-400 border-green-700/40'
                : 'bg-amber-900/30 text-amber-400 border-amber-700/40'
            }`}>
              {pedestal.initialized ? '✓ Ready' : '○ Not initialized'}
            </span>
          )}
          {hasAlarm && (
            <span className="text-xs px-2 py-0.5 rounded-full bg-red-900/50 text-red-400 border border-red-700/50 animate-pulse">
              ALARM
            </span>
          )}
        </div>
      </div>

      {/* Symbolic pedestal icon */}
      <div className="flex justify-center mb-4">
        <PedestalIcon
          pending={hasPending}
          active={hasActive}
          alarm={hasAlarm}
          pendingSockets={new Set(pending.filter(s => s.socket_id != null).map(s => s.socket_id!))}
          activeSockets={new Set(active.filter(s => s.socket_id != null).map(s => s.socket_id!))}
        />
      </div>

      {/* Sensor readings */}
      {(temp || moist) && (
        <div className="flex gap-2 mb-3">
          {temp && (
            <div className={`flex-1 text-center text-xs py-1 rounded-lg ${temp.alarm ? 'bg-red-900/30 text-red-300' : 'bg-gray-800 text-gray-400'}`}>
              🌡️ {temp.value}°C{temp.alarm && ' ⚠'}
            </div>
          )}
          {moist && (
            <div className={`flex-1 text-center text-xs py-1 rounded-lg ${moist.alarm ? 'bg-red-900/30 text-red-300' : 'bg-gray-800 text-gray-400'}`}>
              💧 {moist.value}%{moist.alarm && ' ⚠'}
            </div>
          )}
        </div>
      )}

      {/* Health indicators */}
      {health && (
        <div className="flex items-center gap-2 mb-3">
          <StatusDot ok={health.opta_connected} label="OPTA" />
          <StatusDot ok={health.camera_reachable} label="Cam" />
          {health.last_heartbeat && (
            <span className="text-xs text-gray-500 ml-auto">
              HB {relativeTime(health.last_heartbeat)}
            </span>
          )}
        </div>
      )}

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

    {qrOpen && health?.opta_client_id && (
      <PedestalQrGridModal
        cabinetId={health.opta_client_id}
        pedestalId={pedestal.id}
        pedestalName={pedestal.name}
        onClose={() => setQrOpen(false)}
        onCopied={(sid) => addToast({ message: `Copied ${sid} URL`, variant: 'success' })}
        onCopyFailed={(sid) => addToast({ message: `Clipboard unavailable for ${sid}`, variant: 'warning' })}
      />
    )}
    </>
  )
}


// ─── QR grid modal (v3.7) ────────────────────────────────────────────────────
// Opened from the QR icon on a PedestalCard. Lightweight — no feedback
// toolbar, just the 4 QRs + Download All. Closes on backdrop click and on ×.

function PedestalQrGridModal({
  cabinetId,
  pedestalId,
  pedestalName,
  onClose,
  onCopied,
  onCopyFailed,
}: {
  cabinetId: string
  pedestalId: number
  pedestalName: string
  onClose: () => void
  onCopied: (sid: string) => void
  onCopyFailed: (sid: string) => void
}) {
  const [zipBusy, setZipBusy] = useState(false)

  const handleDownloadAll = async () => {
    setZipBusy(true)
    try {
      const blob = await getPedestalQrAll(cabinetId)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `${cabinetId}_qr_codes.zip`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)
    } catch {
      /* silent — button stops the spinner on fail */
    } finally {
      setZipBusy(false)
    }
  }

  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center bg-black/70 p-4"
      role="dialog"
      aria-modal="true"
      onClick={onClose}
    >
      <div
        className="bg-gray-900 border border-gray-700 rounded-lg p-4 max-w-lg w-full space-y-3"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-sm font-semibold text-white">QR Codes</h3>
            <p className="text-xs text-gray-500 font-mono">{pedestalName} — {cabinetId}</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="text-gray-400 hover:text-white text-lg leading-none"
            aria-label="Close"
          >
            ×
          </button>
        </div>

        <SocketQrGrid
          cabinetId={cabinetId}
          pedestalId={pedestalId}
          reloadNonce={0}
          onCopied={onCopied}
          onCopyFailed={onCopyFailed}
        />

        <div className="flex gap-2 pt-1">
          <button
            type="button"
            onClick={handleDownloadAll}
            disabled={zipBusy}
            className="flex-1 py-1.5 text-sm rounded bg-blue-700/60 hover:bg-blue-600/60 text-blue-100 border border-blue-700/50 disabled:opacity-40"
          >
            {zipBusy ? 'Downloading…' : 'Download All (ZIP)'}
          </button>
          <button
            type="button"
            onClick={onClose}
            className="flex-1 py-1.5 text-sm rounded border border-gray-600 text-gray-300 hover:bg-gray-700/60"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  )
}

function PedestalIcon({ pending, active, alarm, pendingSockets, activeSockets }: {
  pending: boolean; active: boolean; alarm: boolean
  pendingSockets: Set<number>; activeSockets: Set<number>
}) {
  const color = alarm ? '#ef4444' : pending ? '#f59e0b' : active ? '#22c55e' : '#4b5563'
  const glow  = alarm
    ? 'drop-shadow(0 0 8px rgba(239,68,68,0.7))'
    : pending
    ? 'drop-shadow(0 0 8px rgba(245,158,11,0.6))'
    : active
    ? 'drop-shadow(0 0 8px rgba(34,197,94,0.6))'
    : 'none'

  const socketFill = (id: number) =>
    activeSockets.has(id) ? '#22c55e' : pendingSockets.has(id) ? '#f59e0b' : '#374151'

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
      {/* 4 socket indicators — per-socket state */}
      <circle cx="12" cy="50" r="7" fill={socketFill(1)} stroke={color} strokeWidth="1.5" />
      <circle cx="12" cy="68" r="7" fill={socketFill(2)} stroke={color} strokeWidth="1.5" />
      <circle cx="60" cy="50" r="7" fill={socketFill(3)} stroke={color} strokeWidth="1.5" />
      <circle cx="60" cy="68" r="7" fill={socketFill(4)} stroke={color} strokeWidth="1.5" />
      {/* Water pipes */}
      <rect x="2" y="95" width="16" height="6" rx="3" fill="#374151" stroke="#6b7280" strokeWidth="1" />
      <rect x="54" y="95" width="16" height="6" rx="3" fill="#374151" stroke="#6b7280" strokeWidth="1" />
      {/* Base */}
      <rect x="14" y="104" width="44" height="8" rx="3" fill="#374151" stroke={color} strokeWidth="1" />
    </svg>
  )
}

function StatusDot({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span className="flex items-center gap-1 text-xs">
      <span
        className={`inline-block w-2 h-2 rounded-full ${ok ? 'bg-green-500' : 'bg-red-500'}`}
        title={ok ? `${label}: connected` : `${label}: offline`}
      />
      <span className={ok ? 'text-green-400' : 'text-red-400'}>{label}</span>
    </span>
  )
}

function relativeTime(iso: string): string {
  const diff = Math.floor((Date.now() - new Date(iso).getTime()) / 1000)
  if (diff < 60) return `${diff}s ago`
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
  return `${Math.floor(diff / 3600)}h ago`
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
