import { useEffect, useRef, useState } from 'react'
import { useStore } from '../../store'
import { postBreakerReset } from '../../api/breakers'
import BreakerHistoryModal from './BreakerHistoryModal'

// v3.8 — per-socket breaker UI. Mounted once inside each SocketCard.
// - Status indicator (coloured dot + label)
// - Hardware Info block (metadata from Arduino — "Not reported" if null)
// - Admin-only Reset button with confirm-before-send flow + 15 s timeout watchdog
// - History button opens BreakerHistoryModal (last 10 events)

interface Props {
  pedestalId: number
  socketId: number
  isAdmin: boolean
  onFeedback: (key: string, type: 'success' | 'error', text: string) => void
}

const STATE_LABELS: Record<string, { label: string; dot: string; text: string }> = {
  closed:    { label: 'Breaker OK',        dot: 'bg-green-400',                 text: 'text-green-300' },
  tripped:   { label: 'BREAKER TRIPPED',   dot: 'bg-red-500 animate-pulse',     text: 'text-red-300'   },
  resetting: { label: 'Resetting…',        dot: 'bg-yellow-400 animate-spin rounded-none', text: 'text-yellow-300' },
  open:      { label: 'Breaker Open',      dot: 'bg-orange-400',                text: 'text-orange-300'},
  unknown:   { label: 'Unknown',           dot: 'bg-gray-500',                  text: 'text-gray-400'  },
}

function fmt(v: string | number | boolean | null | undefined): string {
  if (v === null || v === undefined) return 'Not reported'
  if (typeof v === 'boolean') return v ? 'Yes' : 'No'
  return String(v)
}

export default function SocketBreakerPanel({ pedestalId, socketId, isAdmin, onFeedback }: Props) {
  const key = `${pedestalId}-${socketId}`
  const breaker = useStore((s) => s.socketBreakerStates[key])
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [historyOpen, setHistoryOpen] = useState(false)
  const [resetBusy, setResetBusy] = useState(false)
  const watchdogRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const state: keyof typeof STATE_LABELS = (breaker?.breaker_state ?? 'unknown') as keyof typeof STATE_LABELS
  const cfg = STATE_LABELS[state] ?? STATE_LABELS.unknown
  const isTripped = state === 'tripped'
  const isResetting = state === 'resetting'

  // Clear the 15 s watchdog the moment we observe a return to closed.
  useEffect(() => {
    if (state === 'closed' && watchdogRef.current) {
      clearTimeout(watchdogRef.current)
      watchdogRef.current = null
    }
  }, [state])

  // Clean up watchdog on unmount.
  useEffect(() => () => {
    if (watchdogRef.current) clearTimeout(watchdogRef.current)
  }, [])

  const handleReset = async () => {
    setConfirmOpen(false)
    setResetBusy(true)
    try {
      await postBreakerReset(pedestalId, socketId)
      onFeedback(`breaker-${socketId}-reset`, 'success', `Reset sent to Q${socketId}`)
      // 15 s watchdog — if state is still 'tripped' when it fires, notify operator.
      // The store's setBreakerState driven by the ACK or the state-change broadcast
      // will flip to 'resetting' → 'closed' long before this fires on success.
      watchdogRef.current = setTimeout(() => {
        const current = useStore.getState().socketBreakerStates[key]?.breaker_state
        if (current !== 'closed') {
          onFeedback(
            `breaker-${socketId}-reset-timeout`,
            'error',
            `Breaker reset failed — overload condition may still be present`,
          )
        }
        watchdogRef.current = null
      }, 15_000)
    } catch (err) {
      const axiosErr = err as { response?: { status?: number; data?: { detail?: string } } }
      if (axiosErr?.response?.status === 409) {
        onFeedback(`breaker-${socketId}-reset`, 'error', 'Breaker is not in tripped state')
      } else {
        onFeedback(`breaker-${socketId}-reset`, 'error', axiosErr?.response?.data?.detail ?? `Reset failed for Q${socketId}`)
      }
    } finally {
      setResetBusy(false)
    }
  }

  return (
    <>
      <div className="pt-2 border-t border-gray-700/50 space-y-2">
        {/* ── Status indicator ───────────────────────────────── */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1.5">
            <span className={`inline-block w-2 h-2 rounded-full ${cfg.dot}`} />
            <span className={`text-xs font-medium ${cfg.text}`}>{cfg.label}</span>
          </div>
          <button
            type="button"
            onClick={() => setHistoryOpen(true)}
            className="text-[10px] px-1.5 py-0.5 rounded border border-gray-600 text-gray-300 hover:bg-gray-700/60"
            aria-label={`Show breaker history for Q${socketId}`}
          >
            History
          </button>
        </div>

        {/* ── Hardware Info ──────────────────────────────────── */}
        <div className="text-[11px] text-gray-500 space-y-0.5">
          <p>
            type: <span className="text-gray-300 font-mono">{fmt(breaker?.breaker_type ?? null)}</span>
            {' · '}
            rating: <span className="text-gray-300 font-mono">{fmt(breaker?.breaker_rating ?? null)}</span>
          </p>
          <p>
            poles: <span className="text-gray-300 font-mono">{fmt(breaker?.breaker_poles ?? null)}</span>
            {' · '}
            RCD: <span className="text-gray-300 font-mono">{fmt(breaker?.breaker_rcd ?? null)}</span>
            {breaker?.breaker_rcd === true && (
              <>
                {' · '}
                sensitivity: <span className="text-gray-300 font-mono">{fmt(breaker?.breaker_rcd_sensitivity ?? null)}</span>
              </>
            )}
          </p>
          {breaker?.trip_count != null && breaker.trip_count > 0 && (
            <p>trips: <span className="text-gray-300 font-mono">{breaker.trip_count}</span></p>
          )}
          {breaker?.trip_cause && (
            <p>
              cause: <span className="text-red-300 font-mono">{breaker.trip_cause}</span>
            </p>
          )}
        </div>

        {/* ── Admin-only Reset button ────────────────────────── */}
        {isAdmin && isTripped && (
          <button
            type="button"
            onClick={() => setConfirmOpen(true)}
            disabled={resetBusy}
            className="w-full text-xs font-medium px-2 py-1.5 rounded border border-red-600 bg-red-900/40 text-red-200 hover:bg-red-800/60 disabled:opacity-50 disabled:cursor-not-allowed"
            aria-label={`Reset breaker on Q${socketId}`}
          >
            {resetBusy ? 'Sending…' : '⚡ Reset Breaker'}
          </button>
        )}
        {isAdmin && isResetting && (
          <div className="w-full text-xs font-medium px-2 py-1.5 rounded border border-yellow-700 bg-yellow-900/40 text-yellow-200 text-center">
            <span className="inline-block animate-spin">⟳</span> Resetting breaker…
          </div>
        )}
      </div>

      {/* ── Confirm dialog ─────────────────────────────────── */}
      {confirmOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" role="dialog" aria-modal="true">
          <div className="bg-gray-900 border border-gray-700 rounded-lg p-4 max-w-md mx-4 space-y-3">
            <h3 className="text-sm font-semibold text-white">Confirm breaker reset</h3>
            <p className="text-xs text-gray-300">
              Are you sure you want to remotely reset the circuit breaker on socket Q{socketId}?
            </p>
            <p className="text-xs text-amber-300 bg-amber-900/20 border border-amber-700/40 rounded px-2 py-1.5">
              Ensure the overload condition has been resolved before resetting.
            </p>
            <div className="flex gap-2 pt-1">
              <button
                type="button"
                onClick={() => setConfirmOpen(false)}
                className="flex-1 text-xs px-3 py-1.5 rounded border border-gray-600 text-gray-300 hover:bg-gray-700/60"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleReset}
                className="flex-1 text-xs px-3 py-1.5 rounded border border-red-600 bg-red-900/60 text-red-100 hover:bg-red-800"
              >
                Reset Breaker
              </button>
            </div>
          </div>
        </div>
      )}

      {historyOpen && (
        <BreakerHistoryModal
          pedestalId={pedestalId}
          socketId={socketId}
          onClose={() => setHistoryOpen(false)}
        />
      )}
    </>
  )
}
