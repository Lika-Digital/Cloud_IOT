import { useState, useEffect, useCallback } from 'react'
import {
  getHealthSummary, getErrorLogs, clearLogs, getHardwareStats,
  type HealthSummary, type ErrorLogEntry, type HardwareStats, type HardwareAlarm,
} from '../api/systemHealth'
import {
  acknowledgeLoadAlarm, resolveLoadAlarm,
  type MeterLoadAlarm,
} from '../api/meterLoad'
import { useStore } from '../store'

type FilterCategory = 'all' | 'system' | 'hw'
type FilterLevel    = 'all' | 'error' | 'warning' | 'info'

export default function SystemHealth() {
  const [summary, setSummary]         = useState<HealthSummary | null>(null)
  const [logs, setLogs]               = useState<ErrorLogEntry[]>([])
  const [hw, setHw]                   = useState<HardwareStats | null>(null)
  const [category, setCategory]       = useState<FilterCategory>('all')
  const [level, setLevel]             = useState<FilterLevel>('all')
  const [hours, setHours]             = useState(24)
  const [expanded, setExpanded]       = useState<number | null>(null)
  const [clearing, setClearing]       = useState(false)
  const [loadError, setLoadError]     = useState<string | null>(null)
  const [hwError, setHwError]         = useState<string | null>(null)
  const {
    resetNewErrors, setHwAlarmLevel,
    activeCriticalLoadAlarms, activeWarningLoadAlarms,
  } = useStore()
  // v3.11 — open meter load alarms (resolved_at IS NULL) per pedestal.
  // Aggregated across all pedestals for the System Health view.
  const [loadAlarms, setLoadAlarms] = useState<MeterLoadAlarm[]>([])
  const [loadAlarmsBusyId, setLoadAlarmsBusyId] = useState<number | null>(null)

  // ── Error log polling (15s) ────────────────────────────────────────────────
  const loadLogs = useCallback(async () => {
    try {
      const [s, l] = await Promise.all([
        getHealthSummary(),
        getErrorLogs({
          category: category === 'all' ? undefined : category,
          level:    level    === 'all' ? undefined : level,
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

  // ── Hardware stats polling (10s) ───────────────────────────────────────────
  const loadHw = useCallback(async () => {
    try {
      const stats = await getHardwareStats()
      setHw(stats)
      setHwError(null)
      // Sync nav indicator based on highest alarm level — merge hardware
      // stats and meter load alarms into one severity bucket (v3.11 D8).
      const hwHighest = stats.alarms.find((a) => a.level === 'critical')
        ? 'critical'
        : stats.alarms.find((a) => a.level === 'warning')
          ? 'warning'
          : 'none'
      const loadCritical = useStore.getState().activeCriticalLoadAlarms.length > 0
      const loadWarning  = useStore.getState().activeWarningLoadAlarms.length > 0
      const merged: 'none' | 'warning' | 'critical' =
        hwHighest === 'critical' || loadCritical ? 'critical'
        : hwHighest === 'warning' || loadWarning ? 'warning'
        : 'none'
      setHwAlarmLevel(merged)
    } catch {
      setHwError('Hardware stats unavailable (psutil may not be installed on this host)')
    }
  }, [setHwAlarmLevel])

  // v3.11 — refresh open load alarms across all pedestals. Backend has no
  // marina-wide internal endpoint, so we iterate the visible pedestals from
  // the store. Light query — one row per open alarm — runs at 15 s cadence
  // alongside error log polling.
  const loadLoadAlarms = useCallback(async () => {
    try {
      const pedestals = useStore.getState().pedestals
      if (!pedestals || pedestals.length === 0) {
        setLoadAlarms([])
        return
      }
      const { getPedestalLoadAlarms } = await import('../api/meterLoad')
      const all: MeterLoadAlarm[] = []
      for (const p of pedestals) {
        try {
          const r = await getPedestalLoadAlarms(p.id)
          all.push(...r.alarms)
        } catch { /* per-pedestal failures shouldn't kill the page */ }
      }
      // Newest first.
      all.sort((a, b) => (b.triggered_at > a.triggered_at ? 1 : -1))
      setLoadAlarms(all)
    } catch { /* fine */ }
  }, [])

  useEffect(() => {
    resetNewErrors()
    loadLogs()
    loadHw()
    loadLoadAlarms()
    const logInterval  = setInterval(loadLogs, 15_000)
    const hwInterval   = setInterval(loadHw,   10_000)
    const loadInterval = setInterval(loadLoadAlarms, 15_000)
    return () => {
      clearInterval(logInterval)
      clearInterval(hwInterval)
      clearInterval(loadInterval)
    }
  }, [loadLogs, loadHw, loadLoadAlarms])

  // Re-run hw merge whenever the load-alarm counts change so the badge
  // promotes up immediately on a new WS critical/warning event.
  useEffect(() => {
    if (!hw) return
    loadHw()
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeCriticalLoadAlarms.length, activeWarningLoadAlarms.length])

  const handleAck = async (a: MeterLoadAlarm) => {
    setLoadAlarmsBusyId(a.id)
    try {
      const updated = await acknowledgeLoadAlarm(a.pedestal_id, a.id)
      setLoadAlarms((rows) => rows.map((r) => (r.id === a.id ? updated : r)))
    } catch { /* backend surfaces */ }
    finally { setLoadAlarmsBusyId(null) }
  }

  const handleResolve = async (a: MeterLoadAlarm) => {
    if (!confirm(`Manually resolve load alarm on pedestal ${a.pedestal_id} Q${a.socket_id}?`)) return
    setLoadAlarmsBusyId(a.id)
    try {
      await resolveLoadAlarm(a.pedestal_id, a.id)
      // Drop from the open list — server returned with resolved_at set.
      setLoadAlarms((rows) => rows.filter((r) => r.id !== a.id))
    } catch { /* backend surfaces */ }
    finally { setLoadAlarmsBusyId(null) }
  }

  const handleClear = async () => {
    if (!confirm('Delete all error logs? This cannot be undone.')) return
    setClearing(true)
    try {
      await clearLogs()
      setLogs([])
      loadLogs()
    } catch { /* backend will surface */ }
    finally { setClearing(false) }
  }

  const criticalAlarms = hw?.alarms.filter((a) => a.level === 'critical') ?? []
  const warningAlarms  = hw?.alarms.filter((a) => a.level === 'warning')  ?? []

  return (
    <div className="space-y-6">
      {loadError && (
        <div className="px-4 py-3 rounded-lg bg-red-900/30 border border-red-700/40 text-red-400 text-sm">
          {loadError}
        </div>
      )}

      {/* ── Header ─────────────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">System Health</h1>
          <p className="text-gray-400 text-sm mt-1">Hardware stats refresh every 10s · Error logs every 15s</p>
        </div>
        <button
          className="px-4 py-2 bg-red-900/40 border border-red-700/40 text-red-400 rounded-lg text-sm font-medium hover:bg-red-900/60 transition-colors disabled:opacity-40"
          onClick={handleClear}
          disabled={clearing}
        >
          {clearing ? 'Clearing…' : 'Clear All Logs'}
        </button>
      </div>

      {/* ── Hardware alarm banners ─────────────────────────────────────────── */}
      {criticalAlarms.length > 0 && (
        <div className="rounded-lg border border-red-600/50 bg-red-900/30 px-4 py-3 space-y-1">
          <p className="text-red-400 font-semibold text-sm flex items-center gap-2">
            <span className="w-2.5 h-2.5 rounded-full bg-red-500 animate-pulse inline-block" />
            CRITICAL ALARM — automatic downgrade actions applied
          </p>
          {criticalAlarms.map((a) => (
            <p key={a.param} className="text-red-300 text-sm ml-4">
              {a.label}: <span className="font-bold">{a.value.toFixed(1)}{a.unit}</span>
              {' '}(threshold {a.threshold}{a.unit})
            </p>
          ))}
        </div>
      )}
      {warningAlarms.length > 0 && (
        <div className="rounded-lg border border-yellow-600/50 bg-yellow-900/20 px-4 py-3 space-y-1">
          <p className="text-yellow-400 font-semibold text-sm flex items-center gap-2">
            <span className="w-2.5 h-2.5 rounded-full bg-yellow-400 animate-pulse inline-block" />
            WARNING — monitor closely, no automatic action taken
          </p>
          {warningAlarms.map((a) => (
            <p key={a.param} className="text-yellow-300 text-sm ml-4">
              {a.label}: <span className="font-bold">{a.value.toFixed(1)}{a.unit}</span>
              {' '}(threshold {a.threshold}{a.unit})
            </p>
          ))}
        </div>
      )}

      {/* ── v3.11 Meter Load Alarms (separate card per D7) ──────────────────── */}
      {loadAlarms.length > 0 && (
        <div className="rounded-lg border border-orange-600/50 bg-orange-900/20 px-4 py-3 space-y-2">
          <p className="text-orange-300 font-semibold text-sm flex items-center gap-2">
            <span className="text-base">⚡</span>
            METER LOAD ALARMS — {loadAlarms.filter((a) => !a.acknowledged).length} active, {loadAlarms.length} total
          </p>
          <div className="space-y-1">
            {loadAlarms.map((a) => {
              const isCritical = a.alarm_type === 'critical'
              const dim = a.acknowledged ? 'opacity-50' : ''
              return (
                <div
                  key={a.id}
                  className={`flex items-center gap-3 text-xs px-2 py-1.5 rounded border ${
                    isCritical
                      ? 'bg-red-900/30 border-red-700/40'
                      : 'bg-yellow-900/20 border-yellow-700/40'
                  } ${dim}`}
                >
                  <span className={`w-1.5 h-1.5 rounded-full ${
                    isCritical ? 'bg-red-500 animate-pulse' : 'bg-yellow-400'
                  }`} />
                  <span className={`font-mono ${isCritical ? 'text-red-200' : 'text-yellow-200'}`}>
                    {isCritical ? 'CRITICAL' : 'WARNING'}
                  </span>
                  <span className="text-gray-300">
                    Pedestal {a.pedestal_id} Q{a.socket_id}
                  </span>
                  <span className="text-gray-400 font-mono">
                    {a.meter_type ?? 'meter'}
                    {' · '}
                    {a.current_amps.toFixed(1)}A / {a.rated_amps.toFixed(0)}A
                    {' · '}
                    {a.load_pct.toFixed(0)}%
                  </span>
                  <span className="ml-auto text-gray-500 font-mono text-[11px]">
                    {a.triggered_at.replace('T', ' ').slice(0, 19)}
                  </span>
                  {!a.acknowledged && (
                    <button
                      type="button"
                      onClick={() => handleAck(a)}
                      disabled={loadAlarmsBusyId === a.id}
                      className="text-[11px] px-2 py-0.5 rounded border border-gray-600 text-gray-200 hover:bg-gray-700/60 disabled:opacity-40"
                    >
                      Acknowledge
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={() => handleResolve(a)}
                    disabled={loadAlarmsBusyId === a.id}
                    className="text-[11px] px-2 py-0.5 rounded border border-orange-700 text-orange-200 hover:bg-orange-800/50 disabled:opacity-40"
                  >
                    Resolve
                  </button>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* ── Hardware performance dashboard ─────────────────────────────────── */}
      {hwError ? (
        <div className="card">
          <p className="text-gray-500 text-sm">{hwError}</p>
        </div>
      ) : hw?.available ? (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-base font-semibold text-white">Hardware Performance</h2>
            <span className="text-xs text-gray-600">
              collected in {hw.elapsed_ms}ms
              {hw.rtsp_suspended && (
                <span className="ml-2 text-orange-400">[RTSP suspended — thermal protection]</span>
              )}
            </span>
          </div>

          {/* Main gauges row */}
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
            <GaugeCard title="CPU Usage" icon="⚙️"
              value={hw.cpu_percent} unit="%" warn={hw.thresholds.cpu_warning} crit={hw.thresholds.cpu_critical}
              sub={`${hw.cpu_freq_mhz ? hw.cpu_freq_mhz.toFixed(0) + ' MHz · ' : ''}${hw.cpu_per_core.length} cores`}
            />
            <GaugeCard title="Memory" icon="🧠"
              value={hw.mem_percent} unit="%" warn={hw.thresholds.mem_warning} crit={hw.thresholds.mem_critical}
              sub={`${hw.mem_used_hr} / ${hw.mem_total_hr}`}
            />
            <GaugeCard title="Disk Usage" icon="💾"
              value={hw.disk_percent} unit="%" warn={hw.thresholds.disk_warning} crit={hw.thresholds.disk_critical}
              sub={`${hw.disk_used_hr} / ${hw.disk_total_hr}`}
            />
            {hw.cpu_temp !== null && (
              <GaugeCard title="CPU Temperature" icon="🌡️"
                value={hw.cpu_temp} max={hw.cpu_temp_max} unit="°C"
                warn={hw.thresholds.temp_warning} crit={hw.thresholds.temp_critical}
                sub={`max ${hw.cpu_temp_max}°C safe`}
              />
            )}
          </div>

          {/* Per-core CPU */}
          {hw.cpu_per_core.length > 1 && (
            <div className="card space-y-2">
              <p className="text-xs text-gray-400 font-medium uppercase tracking-wider">CPU per core</p>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
                {hw.cpu_per_core.map((pct, i) => (
                  <Gauge key={i}
                    label={`Core ${i}`}
                    value={pct} max={100} unit="%"
                    warn={hw.thresholds.cpu_warning}
                    crit={hw.thresholds.cpu_critical}
                  />
                ))}
              </div>
            </div>
          )}

          {/* System info row */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <InfoCard label="Uptime" value={hw.uptime} icon="⏱️" />
            <InfoCard label="Load avg (1m)" value={hw.load_1.toFixed(2)} icon="📈" />
            <InfoCard label="Load avg (5m)" value={hw.load_5.toFixed(2)} icon="📊" />
            <InfoCard label="Load avg (15m)" value={hw.load_15.toFixed(2)} icon="📉" />
          </div>

          {/* Network interfaces */}
          {hw.interfaces.length > 0 && (
            <div className="card space-y-3">
              <p className="text-xs text-gray-400 font-medium uppercase tracking-wider">Network Interfaces</p>
              <div className="space-y-2">
                {hw.interfaces.map((iface) => (
                  <div key={iface.name}
                    className="flex flex-wrap items-center gap-x-4 gap-y-1 px-3 py-2 rounded-lg bg-gray-900/50 border border-gray-700/50">
                    <div className="flex items-center gap-2 min-w-[120px]">
                      <span className={`w-2 h-2 rounded-full flex-shrink-0 ${iface.up ? 'bg-green-400 animate-pulse' : 'bg-red-500'}`} />
                      <span className="font-mono text-sm text-white">{iface.name}</span>
                      <span className={`text-xs ${iface.up ? 'text-green-400' : 'text-red-400'}`}>
                        {iface.up ? 'UP' : 'DOWN'}
                      </span>
                    </div>
                    {iface.ip && <span className="font-mono text-xs text-gray-400">{iface.ip}</span>}
                    {iface.speed > 0 && <span className="text-xs text-gray-600">{iface.speed} Mb/s</span>}
                    <span className="text-xs text-gray-500 ml-auto">
                      ↑ {iface.bytes_sent_hr} · ↓ {iface.bytes_recv_hr}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Automatic actions log */}
          {hw.action_log.length > 0 && (
            <div className="card space-y-3">
              <p className="text-xs text-gray-400 font-medium uppercase tracking-wider">Automatic Actions Log</p>
              <div className="space-y-2 max-h-60 overflow-y-auto">
                {hw.action_log.map((entry, i) => (
                  <div key={i} className={`px-3 py-2 rounded-lg text-xs border ${
                    entry.alarm_level === 'critical'
                      ? 'bg-red-900/20 border-red-700/30'
                      : 'bg-yellow-900/20 border-yellow-700/30'
                  }`}>
                    <div className="flex items-center gap-2 mb-0.5">
                      <span className={`font-semibold ${entry.alarm_level === 'critical' ? 'text-red-400' : 'text-yellow-400'}`}>
                        {entry.alarm_level.toUpperCase()}
                      </span>
                      <span className="text-gray-500 font-mono">{formatTime(entry.timestamp)}</span>
                      <span className="text-gray-400 uppercase">{entry.param}</span>
                      <span className="text-gray-500">{entry.value.toFixed(1)}</span>
                    </div>
                    <p className="text-gray-300">{entry.action}</p>
                    <p className="text-gray-600 mt-0.5">Result: {entry.result}</p>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      ) : hw && !hw.available ? (
        <div className="card">
          <p className="text-gray-500 text-sm">Hardware stats not available: {hw.error}</p>
        </div>
      ) : (
        <div className="card">
          <p className="text-gray-600 text-sm">Loading hardware stats…</p>
        </div>
      )}

      {/* ── Infrastructure status ───────────────────────────────────────────── */}
      {summary && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <InfraCard label="MQTT Broker" ok={summary.mqtt_connected} okText="Connected" failText="Disconnected" />
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

      {/* ── Error log filters ───────────────────────────────────────────────── */}
      <div className="card">
        <div className="flex flex-wrap gap-4 items-center">
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

      {/* ── Error log table ────────────────────────────────────────────────── */}
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
                      <td className="px-4 py-3"><LevelBadge level={entry.level} /></td>
                      <td className="px-4 py-3"><CategoryBadge category={entry.category} /></td>
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

// ─── Gauge card (full card with title) ───────────────────────────────────────

function GaugeCard({
  title, icon, value, max = 100, unit, warn, crit, sub,
}: {
  title: string; icon: string; value: number | null; max?: number
  unit: string; warn: number; crit: number; sub?: string
}) {
  if (value === null) return null
  const pct     = Math.min((value / max) * 100, 100)
  const warnPct = (warn / max) * 100
  const critPct = (crit / max) * 100
  const color   = value >= crit ? 'bg-red-500' : value >= warn ? 'bg-yellow-500' : 'bg-green-500'
  const textCol = value >= crit ? 'text-red-400' : value >= warn ? 'text-yellow-400' : 'text-green-400'
  const border  = value >= crit ? 'border-red-700/40' : value >= warn ? 'border-yellow-700/30' : 'border-gray-700'

  return (
    <div className={`rounded-xl border bg-gray-800/60 p-4 space-y-3 ${border}`}>
      <div className="flex items-center justify-between">
        <span className="text-xs text-gray-400 font-medium flex items-center gap-1.5">
          <span>{icon}</span>{title}
        </span>
        <span className={`text-xl font-bold ${textCol}`}>
          {value.toFixed(1)}<span className="text-sm font-normal ml-0.5">{unit}</span>
        </span>
      </div>
      <div className="relative h-3 bg-gray-700 rounded-full overflow-hidden">
        {/* Threshold markers */}
        <div className="absolute top-0 bottom-0 w-0.5 bg-yellow-500/50 z-10" style={{ left: `${warnPct}%` }} />
        <div className="absolute top-0 bottom-0 w-0.5 bg-red-500/50 z-10"    style={{ left: `${critPct}%` }} />
        <div className={`h-full rounded-full transition-all duration-500 ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <div className="flex justify-between text-xs text-gray-600">
        <span>{sub}</span>
        <span>{warn}% · {crit}%</span>
      </div>
    </div>
  )
}

// ─── Inline gauge (no card) ───────────────────────────────────────────────────

function Gauge({
  label, value, max = 100, unit, warn, crit,
}: {
  label: string; value: number | null; max?: number
  unit: string; warn: number; crit: number
}) {
  if (value === null) return null
  const pct    = Math.min((value / max) * 100, 100)
  const color  = value >= crit ? 'bg-red-500' : value >= warn ? 'bg-yellow-500' : 'bg-green-500'
  const textCol= value >= crit ? 'text-red-400' : value >= warn ? 'text-yellow-400' : 'text-green-400'
  return (
    <div className="space-y-1">
      <div className="flex justify-between">
        <span className="text-xs text-gray-500">{label}</span>
        <span className={`text-xs font-semibold ${textCol}`}>{value.toFixed(0)}{unit}</span>
      </div>
      <div className="h-2 bg-gray-700 rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  )
}

// ─── Info card ────────────────────────────────────────────────────────────────

function InfoCard({ label, value, icon }: { label: string; value: string; icon: string }) {
  return (
    <div className="rounded-xl border border-gray-700 bg-gray-800/60 p-4">
      <p className="text-gray-400 text-xs font-medium flex items-center gap-1.5">
        <span>{icon}</span>{label}
      </p>
      <p className="text-white font-bold text-lg mt-1">{value}</p>
    </div>
  )
}

// ─── Infrastructure / stat cards (existing) ───────────────────────────────────

function InfraCard({
  label, ok, okText, failText, neutral,
}: {
  label: string; ok: boolean; okText: string; failText: string; neutral?: boolean
}) {
  const color = neutral
    ? 'border-gray-700 bg-gray-800/60'
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

// ─── Badges / filters ────────────────────────────────────────────────────────

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
