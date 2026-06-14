/**
 * ActiveAlarmsPanel (v3.24) — generic ActiveAlarm list (fire, temperature,
 * comm_loss, …). Admin-only. Hydrated from REST on mount + a 30 s safety poll,
 * and kept live via the WS alarm_triggered / alarm_acknowledged / alarm_resolved
 * events (handled in useWebSocket → store.activeAlarms).
 */
import { useEffect, useState } from 'react'
import { useStore } from '../../store'
import { useAuthStore } from '../../store/authStore'
import { getActiveAlarms, acknowledgeAlarm } from '../../api/alarms'

const TYPE_ICON: Record<string, string> = {
  fire: '🔥',
  temperature: '🌡️',
  temp_sensor_offline: '🌡️',
  moisture: '💦',
  comm_loss: '📡',
  operational_failure: '🛠️',
  security: '🛡️',
  unauthorized_entry: '🚪',
}

function timeAgo(iso: string): string {
  const s = Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 1000))
  if (s < 60) return `${s}s ago`
  if (s < 3600) return `${Math.floor(s / 60)}m ago`
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`
  return new Date(iso).toLocaleString()
}

// critical OR unclassified severity → red; warning → yellow (D2).
function colorOf(severity: string | null): string {
  return severity === 'warning'
    ? 'bg-yellow-900/20 border-yellow-700/40 text-yellow-300'
    : 'bg-red-900/20 border-red-700/40 text-red-300'
}

export default function ActiveAlarmsPanel() {
  const role = useAuthStore((s) => s.role)
  const isAdmin = role === 'admin'
  const alarms = useStore((s) => s.activeAlarms)
  const setActiveAlarms = useStore((s) => s.setActiveAlarms)
  const removeActiveAlarm = useStore((s) => s.removeActiveAlarm)
  const [busyId, setBusyId] = useState<number | null>(null)

  useEffect(() => {
    if (!isAdmin) return
    let cancelled = false
    const load = () =>
      getActiveAlarms()
        .then((rows) => { if (!cancelled) setActiveAlarms(rows) })
        .catch(() => { /* transient — next poll reconciles */ })
    load()
    const t = setInterval(load, 30_000)
    return () => { cancelled = true; clearInterval(t) }
  }, [isAdmin, setActiveAlarms])

  if (!isAdmin) return null

  const handleAck = async (id: number) => {
    setBusyId(id)
    try {
      await acknowledgeAlarm(id)
      removeActiveAlarm(id)
    } catch {
      /* ignore — poll will reconcile */
    } finally {
      setBusyId(null)
    }
  }

  return (
    <div className="card">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-lg font-semibold text-white">Active Alarms</h3>
        <span className="text-xs text-gray-500">{alarms.length} active</span>
      </div>

      {alarms.length === 0 ? (
        <p className="text-sm text-gray-500">✓ No active alarms.</p>
      ) : (
        <div className="space-y-2">
          {alarms.map((a) => (
            <div
              key={a.id}
              className={`flex items-center gap-3 px-3 py-2 rounded-lg border ${colorOf(a.severity)}`}
            >
              <span className="text-lg flex-shrink-0">{TYPE_ICON[a.alarm_type] ?? '⚠️'}</span>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium truncate">{a.message}</p>
                <p className="text-xs opacity-70">
                  {a.alarm_type}
                  {a.pedestal_id != null ? ` · pedestal ${a.pedestal_id}` : ''}
                  {a.severity ? ` · ${a.severity.toUpperCase()}` : ''}
                  {' · '}{timeAgo(a.triggered_at)}
                </p>
              </div>
              <button
                onClick={() => handleAck(a.id)}
                disabled={busyId === a.id}
                className="flex-shrink-0 text-xs px-3 py-1.5 rounded-lg bg-gray-700 hover:bg-gray-600 text-white transition-colors disabled:opacity-50"
              >
                {busyId === a.id ? '…' : 'Acknowledge'}
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
