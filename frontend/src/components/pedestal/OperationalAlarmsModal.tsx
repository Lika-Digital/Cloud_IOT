import { useEffect, useState } from 'react'
import { getSocketBreakerHistory, type BreakerEvent } from '../../api/breakers'
import { getSocketLoadHistory, type MeterLoadAlarm } from '../../api/meterLoad'

// v3.32 — Operational Alarms History: a unified, newest-first timeline of
// breaker events (trips/resets) + load alarms (warning/critical/overload) for
// one socket. Read-only; available in both Smart Mode ON and OFF.

interface Props {
  pedestalId: number
  socketId: number
  /** Display label, e.g. "Q1". */
  label: string
  onClose: () => void
}

interface Row {
  ts: string
  kind: 'breaker' | 'load'
  title: string
  detail: string
  cls: string
}

const BREAKER_LABEL: Record<BreakerEvent['event_type'], string> = {
  tripped: 'Breaker tripped',
  reset_attempted: 'Breaker reset attempted',
  reset_success: 'Breaker reset OK',
  reset_failed: 'Breaker reset failed',
  manually_opened: 'Breaker manually opened',
}

const LOAD_LABEL: Record<MeterLoadAlarm['alarm_type'], string> = {
  warning: 'High load (warning)',
  critical: 'Critical load',
  auto_stop: 'Overload (≥90%)',
}

function breakerRow(e: BreakerEvent): Row {
  const parts: string[] = []
  if (e.trip_cause) parts.push(`cause: ${e.trip_cause}`)
  if (e.current_at_trip != null) parts.push(`${e.current_at_trip} A at trip`)
  if (e.reset_initiated_by) parts.push(`by ${e.reset_initiated_by}`)
  return {
    ts: e.timestamp,
    kind: 'breaker',
    title: BREAKER_LABEL[e.event_type] ?? e.event_type,
    detail: parts.join(' · '),
    cls: e.event_type === 'tripped' || e.event_type === 'reset_failed' ? 'text-red-300' : 'text-gray-300',
  }
}

function loadRow(a: MeterLoadAlarm): Row {
  const resolved = a.resolved_at ? ` · resolved` : ' · active'
  return {
    ts: a.triggered_at,
    kind: 'load',
    title: LOAD_LABEL[a.alarm_type] ?? a.alarm_type,
    detail: `${a.load_pct?.toFixed(0)}% (${a.current_amps?.toFixed(1)}/${a.rated_amps?.toFixed(0)} A)${resolved}`,
    cls: a.alarm_type === 'warning' ? 'text-yellow-300' : 'text-red-300',
  }
}

export default function OperationalAlarmsModal({ pedestalId, socketId, label, onClose }: Props) {
  const [rows, setRows] = useState<Row[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    Promise.allSettled([
      getSocketBreakerHistory(pedestalId, socketId, 50),
      getSocketLoadHistory(pedestalId, socketId),
    ]).then(([b, l]) => {
      if (cancelled) return
      const out: Row[] = []
      if (b.status === 'fulfilled') out.push(...b.value.events.map(breakerRow))
      if (l.status === 'fulfilled') out.push(...l.value.events.map(loadRow))
      out.sort((x, y) => (x.ts < y.ts ? 1 : -1)) // newest first
      setRows(out)
      if (b.status === 'rejected' && l.status === 'rejected') setError('Failed to load alarm history')
    })
    return () => { cancelled = true }
  }, [pedestalId, socketId])

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" role="dialog" aria-modal="true">
      <div className="bg-gray-900 border border-gray-700 rounded-lg p-4 w-full max-w-xl mx-4 max-h-[85vh] flex flex-col">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-semibold text-white">Operational alarms history — {label}</h3>
          <button
            type="button"
            onClick={onClose}
            className="text-xs text-gray-400 hover:text-white px-2 py-1 rounded hover:bg-gray-800"
            aria-label="Close"
          >
            ✕
          </button>
        </div>

        <div className="overflow-y-auto flex-1">
          {error && <p className="text-xs text-red-300">{error}</p>}
          {!error && rows == null && <p className="text-xs text-gray-400">Loading…</p>}
          {!error && rows != null && rows.length === 0 && (
            <p className="text-xs text-gray-500">No breaker or load alarms recorded for {label}.</p>
          )}
          {!error && rows != null && rows.length > 0 && (
            <ul className="space-y-1.5">
              {rows.map((r, i) => (
                <li key={`${r.kind}-${r.ts}-${i}`} className="text-xs bg-gray-800/50 border border-gray-700/50 rounded p-2">
                  <div className="flex items-center justify-between">
                    <span className={`font-semibold ${r.cls}`}>
                      {r.kind === 'breaker' ? '⚡ ' : '📈 '}{r.title}
                    </span>
                    <span className="text-gray-500 font-mono">{new Date(r.ts).toLocaleString()}</span>
                  </div>
                  {r.detail && <div className="text-gray-400 font-mono mt-0.5">{r.detail}</div>}
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  )
}
