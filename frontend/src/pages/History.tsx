import { useEffect, useState } from 'react'
import { getSessions } from '../api'
import type { Session } from '../store'

const STATUS_OPTIONS = ['', 'pending', 'active', 'completed', 'denied']

export default function History() {
  const [sessions, setSessions] = useState<Session[]>([])
  const [statusFilter, setStatusFilter] = useState('')
  const [loading, setLoading] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)

  useEffect(() => {
    setLoading(true)
    setLoadError(null)
    getSessions({ status: statusFilter || undefined, limit: 200 })
      .then((data) => { setSessions(data); setLoadError(null) })
      .catch(() => setLoadError('Failed to load session history. Check your connection and refresh.'))
      .finally(() => setLoading(false))
  }, [statusFilter])

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-white">Session History</h1>
        <select
          className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-sm text-white"
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
        >
          {STATUS_OPTIONS.map((s) => (
            <option key={s} value={s}>
              {s ? s.charAt(0).toUpperCase() + s.slice(1) : 'All statuses'}
            </option>
          ))}
        </select>
      </div>

      {loadError && (
        <div className="mb-4 px-4 py-3 rounded-lg bg-red-900/30 border border-red-700/40 text-red-400 text-sm">
          {loadError}
        </div>
      )}
      {loading ? (
        <div className="text-gray-400 text-center py-8">Loading…</div>
      ) : !loadError && sessions.length === 0 ? (
        <div className="card text-center py-12 text-gray-500">
          <p>No sessions found.</p>
          <p className="text-sm mt-1">Connect a pedestal and approve some sessions first.</p>
        </div>
      ) : !loadError ? (
        <div className="card overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-800 text-left text-gray-400">
                <th className="py-3 px-2">ID</th>
                <th className="py-3 px-2">Type</th>
                <th className="py-3 px-2">Socket</th>
                <th className="py-3 px-2">Status</th>
                <th className="py-3 px-2">Started</th>
                <th className="py-3 px-2">Ended</th>
                <th className="py-3 px-2">Duration</th>
                <th className="py-3 px-2">Consumption</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800">
              {sessions.map((s) => {
                const duration =
                  s.started_at && s.ended_at
                    ? Math.floor(
                        (new Date(s.ended_at).getTime() - new Date(s.started_at).getTime()) / 1000
                      )
                    : null
                return (
                  <tr key={s.id} className="hover:bg-gray-800/50 transition-colors">
                    <td className="py-3 px-2 text-gray-400">#{s.id}</td>
                    <td className="py-3 px-2 text-white capitalize">{s.type}</td>
                    <td className="py-3 px-2 text-gray-300">
                      {s.socket_id != null ? `Socket ${s.socket_id}` : 'Water'}
                    </td>
                    <td className="py-3 px-2">
                      <span className={`badge-${s.status}`}>{s.status}</span>
                    </td>
                    <td className="py-3 px-2 text-gray-400">
                      {new Date(s.started_at).toLocaleString()}
                    </td>
                    <td className="py-3 px-2 text-gray-400">
                      {s.ended_at ? new Date(s.ended_at).toLocaleString() : '—'}
                    </td>
                    <td className="py-3 px-2 font-mono text-gray-300">
                      {duration != null ? formatDuration(duration) : '—'}
                    </td>
                    <td className="py-3 px-2 font-mono text-gray-200">
                      {s.energy_kwh != null
                        ? `${s.energy_kwh.toFixed(4)} kWh`
                        : s.water_liters != null
                        ? `${s.water_liters.toFixed(1)} L`
                        : '—'}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  )
}

function formatDuration(seconds: number) {
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const s = seconds % 60
  return [h, m, s].map((n) => String(n).padStart(2, '0')).join(':')
}
