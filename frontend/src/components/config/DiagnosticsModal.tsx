/**
 * DiagnosticsModal — runs sensor health check against a real (or synthetic) pedestal.
 *
 * Flow:
 *   1. Opens and immediately calls POST /api/pedestals/{id}/diagnostics/run
 *   2. Shows spinner while waiting (up to 12 s)
 *   3. Displays per-sensor OK / FAIL / MISSING result
 *   4. If all OK → pedestal is initialized and ready
 *   5. User can re-run or close
 */
import { useEffect, useState } from 'react'
import { runDiagnostics } from '../../api'
import type { DiagnosticsResult } from '../../api'

const SENSOR_LABELS: Record<string, string> = {
  socket_1:    'Socket 1 (Electricity)',
  socket_2:    'Socket 2 (Electricity)',
  socket_3:    'Socket 3 (Electricity)',
  socket_4:    'Socket 4 (Electricity)',
  water:       'Water Meter',
  temperature: 'Temperature Sensor',
  moisture:    'Moisture Sensor',
}

const SENSOR_ICONS: Record<string, string> = {
  socket_1: '🔌', socket_2: '🔌', socket_3: '🔌', socket_4: '🔌',
  water: '💧', temperature: '🌡️', moisture: '💦',
}

interface DiagnosticsModalProps {
  pedestalId: number
  pedestalName: string
  onClose: (initialized: boolean) => void
}

export default function DiagnosticsModal({ pedestalId, pedestalName, onClose }: DiagnosticsModalProps) {
  const [running, setRunning] = useState(true)
  const [result, setResult] = useState<DiagnosticsResult | null>(null)

  const run = async () => {
    setRunning(true)
    setResult(null)
    try {
      const res = await runDiagnostics(pedestalId)
      setResult(res)
    } catch {
      setResult({
        pedestal_id: pedestalId,
        sensors: Object.fromEntries(
          Object.keys(SENSOR_LABELS).map((k) => [k, 'missing' as const])
        ),
        all_ok: false,
        initialized: false,
        error: 'Failed to reach backend. Is the server running?',
      })
    } finally {
      setRunning(false)
    }
  }

  useEffect(() => { run() }, [])

  const passCount = result
    ? Object.values(result.sensors).filter((v) => v !== 'missing').length
    : 0
  const totalCount = Object.keys(SENSOR_LABELS).length

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm"
      onClick={() => !running && onClose(result?.initialized ?? false)}
    >
      <div
        className="bg-gray-900 border border-gray-700 rounded-2xl shadow-2xl w-full max-w-md mx-4"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-800">
          <div>
            <h2 className="text-lg font-bold text-white">Sensor Diagnostics</h2>
            <p className="text-sm text-gray-400 mt-0.5">{pedestalName}</p>
          </div>
          {!running && (
            <button
              onClick={() => onClose(result?.initialized ?? false)}
              className="text-gray-500 hover:text-gray-300 text-xl leading-none"
            >✕</button>
          )}
        </div>

        {/* Body */}
        <div className="px-6 py-5">

          {/* Running state */}
          {running && (
            <div className="text-center py-6">
              <div className="inline-block w-10 h-10 border-4 border-blue-600 border-t-transparent rounded-full animate-spin mb-4" />
              <p className="text-gray-300 text-sm">Sending diagnostics request…</p>
              <p className="text-gray-500 text-xs mt-1">Waiting up to 12 seconds for pedestal response</p>
            </div>
          )}

          {/* Results */}
          {!running && result && (
            <div className="space-y-4">
              {/* Summary banner */}
              {result.error ? (
                <div className="bg-red-900/20 border border-red-700/40 rounded-lg px-4 py-3">
                  <p className="text-red-300 font-medium text-sm">Connection failed</p>
                  <p className="text-red-400 text-xs mt-1">{result.error}</p>
                </div>
              ) : result.all_ok ? (
                <div className="bg-green-900/20 border border-green-700/40 rounded-lg px-4 py-3 flex items-center gap-3">
                  <span className="text-3xl">✅</span>
                  <div>
                    <p className="text-green-300 font-medium text-sm">All sensors responding</p>
                    <p className="text-green-400 text-xs mt-0.5">Pedestal is initialized and ready to use</p>
                  </div>
                </div>
              ) : (
                <div className="bg-amber-900/20 border border-amber-700/40 rounded-lg px-4 py-3">
                  <p className="text-amber-300 font-medium text-sm">
                    {passCount}/{totalCount} sensors passed
                  </p>
                  <p className="text-amber-400 text-xs mt-0.5">
                    {result.error ?? 'Some sensors did not respond — check connections.'}
                  </p>
                </div>
              )}

              {/* Per-sensor checklist */}
              <div className="space-y-1.5">
                {Object.entries(SENSOR_LABELS).map(([key, label]) => {
                  const status = result.sensors[key] ?? 'missing'
                  return (
                    <div
                      key={key}
                      className="flex items-center gap-3 py-2 px-3 rounded-lg bg-gray-800/50"
                    >
                      <span className="text-lg">{SENSOR_ICONS[key]}</span>
                      <span className="flex-1 text-sm text-gray-300">{label}</span>
                      <StatusChip status={status} />
                    </div>
                  )
                })}
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        {!running && (
          <div className="flex gap-3 px-6 py-4 border-t border-gray-800">
            <button
              onClick={run}
              className="flex-1 px-4 py-2 rounded-lg border border-gray-700 text-gray-300 text-sm hover:bg-gray-800 transition-colors"
            >
              Re-run Checks
            </button>
            <button
              onClick={() => onClose(result?.initialized ?? false)}
              className={`flex-1 px-4 py-2 rounded-lg text-white text-sm font-medium transition-colors ${
                result?.all_ok
                  ? 'bg-green-700 hover:bg-green-600'
                  : 'bg-gray-700 hover:bg-gray-600'
              }`}
            >
              {result?.all_ok ? 'Done — Pedestal Ready' : 'Close'}
            </button>
          </div>
        )}
      </div>
    </div>
  )
}

// ─── Status chip ──────────────────────────────────────────────────────────────

function StatusChip({ status }: { status: string }) {
  if (status === 'ok') {
    return (
      <span className="flex items-center gap-1 text-xs font-medium text-green-400 bg-green-900/30 border border-green-700/40 px-2 py-0.5 rounded-full">
        <span>✓</span> OK
      </span>
    )
  }
  if (status === 'fail') {
    return (
      <span className="flex items-center gap-1 text-xs font-medium text-red-400 bg-red-900/30 border border-red-700/40 px-2 py-0.5 rounded-full">
        <span>✗</span> FAIL
      </span>
    )
  }
  return (
    <span className="flex items-center gap-1 text-xs font-medium text-gray-500 bg-gray-800 border border-gray-700 px-2 py-0.5 rounded-full">
      — NO RESPONSE
    </span>
  )
}
