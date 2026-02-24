import { useState, useEffect, useCallback } from 'react'
import {
  getHealthSummary, getErrorLogs, clearLogs,
  type HealthSummary, type ErrorLogEntry,
} from '../api/systemHealth'
import { useStore } from '../store'

type FilterCategory = 'all' | 'system' | 'hw'
type FilterLevel    = 'all' | 'error' | 'warning' | 'info'

export default function SystemHealth() {
  const [summary, setSummary] = useState<HealthSummary | null>(null)
  const [logs, setLogs] = useState<ErrorLogEntry[]>([])
  const [category, setCategory] = useState<FilterCategory>('all')
  const [level, setLevel] = useState<FilterLevel>('all')
  const [hours, setHours] = useState(24)
  const [expanded, setExpanded] = useState<number | null>(null)
  const [clearing, setClearing] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)
  const { resetNewErrors } = useStore()

  const load = useCallback(async () => {
    try {
      const [s, l] = await Promise.all([
        getHealthSummary(),
        getErrorLogs({
          category: category === 'all' ? undefined : category,
          level: level === 'all' ? undefined : level,
          hours,
        }),
      ])
      setSummary(s)
      setLogs(l)
      setLoadError(null)
    } catch {
      setLoadError('Failed to load system health data. Retrying…')
    }
  }, [category, level, hours])

  useEffect(() => {
    resetNewErrors()
    load()
    const interval = setInterval(load, 15_000)
    return () => clearInterval(interval)
  }, [load])

  const handleClear = async () => {
    if (!confirm('Delete all error logs? This cannot be undone.')) return
    setClearing(true)
    try {
      await clearLogs()
      setLogs([])
      load()
    } catch {
      // If clear fails the backend will surface it; just re-enable the button
    } finally {
      setClearing(false)
    }
  }

  return (
    <div className="space-y-6">
      {loadError && (
        <div className="px-4 py-3 rounded-lg bg-red-900/30 border border-red-700/40 text-red-400 text-sm">
          {loadError}
        </div>
      )}
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">System Health</h1>
          <p className="text-gray-400 text-sm mt-1">Error logs — last 7 days · auto-refresh every 15s</p>
        </div>
        <button
          className="px-4 py-2 bg-red-900/40 border border-red-700/40 text-red-400 rounded-lg text-sm font-medium hover:bg-red-900/60 transition-colors disabled:opacity-40"
          onClick={handleClear}
          disabled={clearing}
        >
          {clearing ? 'Clearing…' : 'Clear All Logs'}
        </button>
      </div>

      {/* Infrastructure status */}
      {summary && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <InfraCard
            label="MQTT Broker"
            ok={summary.mqtt_connected}
            okText="Connected"
            failText="Disconnected"
          />
          <InfraCard
            label="Simulator"
            ok={summary.simulator_running}
            okText="Running"
            failText="Stopped"
            neutral
          />
          <StatCard label="Errors (7d)"   value={summary.errors_7d}   color="red" />
          <StatCard label="Warnings (7d)" value={summary.warnings_7d} color="yellow" />
        </div>
      )}

      {/* Breakdown cards */}
      {summary && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <StatCard label="System Errors" value={summary.system_errors} color="red"    sub="software / API" />
          <StatCard label="HW Errors"     value={summary.hw_errors}     color="orange" sub="pedestal / MQTT" />
          <StatCard label="HW Warnings"   value={summary.hw_warnings}   color="yellow" sub="sensor alarms" />
          <StatCard label="Last 24h"      value={summary.last_24h_total} color="blue"  sub={`${summary.last_24h_errors} errors`} />
        </div>
      )}

      {/* Filters */}
      <div className="card">
        <div className="flex flex-wrap gap-4 items-center">
          {/* Category */}
          <FilterGroup
            label="Category"
            options={[
              { value: 'all',    label: 'All' },
              { value: 'system', label: 'System' },
              { value: 'hw',     label: 'HW' },
            ]}
            value={category}
            onChange={(v) => setCategory(v as FilterCategory)}
          />

          {/* Level */}
          <FilterGroup
            label="Level"
            options={[
              { value: 'all',     label: 'All' },
              { value: 'error',   label: 'Error' },
              { value: 'warning', label: 'Warning' },
              { value: 'info',    label: 'Info' },
            ]}
            value={level}
            onChange={(v) => setLevel(v as FilterLevel)}
          />

          {/* Time window */}
          <div className="flex items-center gap-2">
            <span className="text-gray-400 text-xs font-medium">Window</span>
            <select
              className="bg-gray-800 border border-gray-700 text-gray-200 text-sm rounded-lg px-3 py-1.5 focus:outline-none"
              value={hours}
              onChange={(e) => setHours(Number(e.target.value))}
            >
              <option value={1}>Last 1h</option>
              <option value={6}>Last 6h</option>
              <option value={24}>Last 24h</option>
              <option value={72}>Last 3d</option>
              <option value={168}>Last 7d</option>
            </select>
          </div>

          <span className="text-gray-600 text-xs ml-auto">{logs.length} entries</span>
        </div>
      </div>

      {/* Log table */}
      <div className="card p-0 overflow-hidden">
        {logs.length === 0 ? (
          <div className="text-center py-16 text-gray-500">
            <p className="text-4xl mb-3">✅</p>
            <p className="font-medium text-gray-400">No log entries found</p>
            <p className="text-sm mt-1">System is running cleanly for the selected filter.</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-700 text-gray-400 text-left">
                  <th className="px-4 py-3 w-40">Time</th>
                  <th className="px-4 py-3 w-20">Level</th>
                  <th className="px-4 py-3 w-24">Category</th>
                  <th className="px-4 py-3 w-36">Source</th>
                  <th className="px-4 py-3">Message</th>
                </tr>
              </thead>
              <tbody>
                {logs.map((entry) => (
                  <>
                    <tr
                      key={entry.id}
                      className={`border-b border-gray-800 cursor-pointer transition-colors ${
                        expanded === entry.id ? 'bg-gray-800/60' : 'hover:bg-gray-800/40'
                      }`}
                      onClick={() => setExpanded(expanded === entry.id ? null : entry.id)}
                    >
                      <td className="px-4 py-3 text-gray-500 font-mono text-xs whitespace-nowrap">
                        {formatTime(entry.created_at)}
                      </td>
                      <td className="px-4 py-3">
                        <LevelBadge level={entry.level} />
                      </td>
                      <td className="px-4 py-3">
                        <CategoryBadge category={entry.category} />
                      </td>
                      <td className="px-4 py-3 text-gray-400 font-mono text-xs truncate max-w-[140px]">
                        {entry.source}
                      </td>
                      <td className="px-4 py-3 text-gray-200">
                        {entry.message}
                        {entry.details && (
                          <span className="ml-2 text-gray-600 text-xs">
                            {expanded === entry.id ? '▲ hide' : '▼ details'}
                          </span>
                        )}
                      </td>
                    </tr>
                    {expanded === entry.id && entry.details && (
                      <tr key={`${entry.id}-details`} className="bg-gray-900/60 border-b border-gray-800">
                        <td colSpan={5} className="px-6 py-3">
                          <pre className="text-xs text-gray-400 font-mono whitespace-pre-wrap break-all max-h-64 overflow-y-auto">
                            {entry.details}
                          </pre>
                        </td>
                      </tr>
                    )}
                  </>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}

// ─── Sub-components ───────────────────────────────────────────────────────────

function InfraCard({
  label, ok, okText, failText, neutral,
}: {
  label: string; ok: boolean; okText: string; failText: string; neutral?: boolean
}) {
  const color = neutral
    ? (ok ? 'border-gray-700 bg-gray-800/60' : 'border-gray-700 bg-gray-800/60')
    : (ok ? 'border-green-700/40 bg-green-900/20' : 'border-red-700/40 bg-red-900/20')

  return (
    <div className={`rounded-xl border p-4 ${color}`}>
      <p className="text-gray-400 text-xs font-medium">{label}</p>
      <div className="flex items-center gap-2 mt-2">
        <span className={`w-2.5 h-2.5 rounded-full ${
          neutral ? 'bg-gray-500' : (ok ? 'bg-green-400 animate-pulse' : 'bg-red-500')
        }`} />
        <span className={`font-bold text-sm ${
          neutral ? 'text-gray-300' : (ok ? 'text-green-400' : 'text-red-400')
        }`}>
          {ok ? okText : failText}
        </span>
      </div>
    </div>
  )
}

function StatCard({
  label, value, color, sub,
}: {
  label: string; value: number; color: string; sub?: string
}) {
  const colors: Record<string, string> = {
    red:    'text-red-400',
    orange: 'text-orange-400',
    yellow: 'text-yellow-400',
    blue:   'text-blue-400',
    green:  'text-green-400',
  }
  return (
    <div className="rounded-xl border border-gray-700 bg-gray-800/60 p-4">
      <p className="text-gray-400 text-xs font-medium">{label}</p>
      <p className={`text-3xl font-bold mt-1 ${colors[color] ?? 'text-white'}`}>{value}</p>
      {sub && <p className="text-gray-600 text-xs mt-1">{sub}</p>}
    </div>
  )
}

function LevelBadge({ level }: { level: string }) {
  const styles: Record<string, string> = {
    error:   'bg-red-900/50 text-red-300 border-red-700/40',
    warning: 'bg-yellow-900/50 text-yellow-300 border-yellow-700/40',
    info:    'bg-blue-900/50 text-blue-300 border-blue-700/40',
  }
  return (
    <span className={`px-2 py-0.5 rounded-full text-xs font-semibold border ${styles[level] ?? styles.info}`}>
      {level.toUpperCase()}
    </span>
  )
}

function CategoryBadge({ category }: { category: string }) {
  return (
    <span className={`px-2 py-0.5 rounded-full text-xs font-semibold border ${
      category === 'hw'
        ? 'bg-orange-900/50 text-orange-300 border-orange-700/40'
        : 'bg-purple-900/50 text-purple-300 border-purple-700/40'
    }`}>
      {category === 'hw' ? 'HW' : 'SYSTEM'}
    </span>
  )
}

function FilterGroup({
  label, options, value, onChange,
}: {
  label: string
  options: { value: string; label: string }[]
  value: string
  onChange: (v: string) => void
}) {
  return (
    <div className="flex items-center gap-2">
      <span className="text-gray-400 text-xs font-medium">{label}</span>
      <div className="flex rounded-lg overflow-hidden border border-gray-700">
        {options.map((opt) => (
          <button
            key={opt.value}
            className={`px-3 py-1.5 text-xs font-medium transition-colors ${
              value === opt.value
                ? 'bg-blue-600 text-white'
                : 'bg-gray-800 text-gray-400 hover:bg-gray-700'
            }`}
            onClick={() => onChange(opt.value)}
          >
            {opt.label}
          </button>
        ))}
      </div>
    </div>
  )
}

function formatTime(iso: string): string {
  const d = new Date(iso)
  return d.toLocaleString('en-GB', {
    day: '2-digit', month: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit',
  })
}
