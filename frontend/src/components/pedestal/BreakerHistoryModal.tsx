import { useEffect, useState } from 'react'
import { getSocketBreakerHistory, type BreakerEvent } from '../../api/breakers'

// v3.8 — Last-10 breaker events modal per D6.

interface Props {
  pedestalId: number
  socketId: number
  onClose: () => void
}

const EVENT_LABEL: Record<BreakerEvent['event_type'], string> = {
  tripped:         'Tripped',
  reset_attempted: 'Reset attempted',
  reset_success:   'Reset success',
  reset_failed:    'Reset failed',
  manually_opened: 'Manually opened',
}

const EVENT_CLASS: Record<BreakerEvent['event_type'], string> = {
  tripped:         'text-red-300',
  reset_attempted: 'text-yellow-300',
  reset_success:   'text-green-300',
  reset_failed:    'text-orange-300',
  manually_opened: 'text-gray-300',
}

export default function BreakerHistoryModal({ pedestalId, socketId, onClose }: Props) {
  const [events, setEvents] = useState<BreakerEvent[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    getSocketBreakerHistory(pedestalId, socketId, 10)
      .then((res) => { if (!cancelled) setEvents(res.events) })
      .catch((e) => { if (!cancelled) setError(e?.response?.data?.detail ?? 'Failed to load history') })
    return () => { cancelled = true }
  }, [pedestalId, socketId])

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" role="dialog" aria-modal="true">
      <div className="bg-gray-900 border border-gray-700 rounded-lg p-4 w-full max-w-lg mx-4 max-h-[80vh] flex flex-col">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-semibold text-white">Breaker history — Q{socketId}</h3>
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
          {!error && events == null && <p className="text-xs text-gray-400">Loading…</p>}
          {!error && events != null && events.length === 0 && (
            <p className="text-xs text-gray-500">No breaker events recorded for this socket.</p>
          )}
          {!error && events != null && events.length > 0 && (
            <ul className="space-y-1.5">
              {events.map((e) => (
                <li
                  key={e.id}
                  className="text-xs bg-gray-800/50 border border-gray-700/50 rounded p-2 space-y-0.5"
                >
                  <div className="flex items-center justify-between">
                    <span className={`font-semibold ${EVENT_CLASS[e.event_type] ?? 'text-gray-300'}`}>
                      {EVENT_LABEL[e.event_type] ?? e.event_type}
                    </span>
                    <span className="text-gray-500 font-mono">
                      {new Date(e.timestamp).toLocaleString()}
                    </span>
                  </div>
                  {(e.trip_cause || e.current_at_trip != null) && (
                    <div className="text-gray-400 font-mono">
                      {e.trip_cause && <>cause: <span className="text-gray-200">{e.trip_cause}</span>{' '}</>}
                      {e.current_at_trip != null && (
                        <>current: <span className="text-gray-200">{e.current_at_trip} A</span></>
                      )}
                    </div>
                  )}
                  {e.reset_initiated_by && (
                    <div className="text-gray-400">
                      initiated by:{' '}
                      <span className={e.reset_initiated_by === 'erp-service' ? 'text-purple-300' : 'text-blue-300'}>
                        {e.reset_initiated_by}
                      </span>
                    </div>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  )
}
