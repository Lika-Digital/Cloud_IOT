import { useState } from 'react'
import { useStore } from '../../store'
import { useAuthStore } from '../../store/authStore'
import SocketBreakerPanel from './SocketBreakerPanel'
import SocketLoadMeterPanel from './SocketLoadMeterPanel'
import SocketUsageHistoryModal from './SocketUsageHistoryModal'
import OperationalAlarmsModal from './OperationalAlarmsModal'

// v3.32 — Dashboard Overview: the read-only MONITORING home for a pedestal.
// Shows cabinet status + per-socket/valve live readings (state, load, breaker,
// power/energy/water) and quick drill-in to Usage / Alarms history. All
// configuration and control lives in the Control Center. Works in both modes.

const SOCKETS = ['Q1', 'Q2', 'Q3', 'Q4']
const VALVES = ['V1', 'V2']

const noop = () => { /* monitor mode has no actions */ }

function fmtUptime(ms?: number): string {
  if (!ms || ms < 0) return '—'
  const s = Math.floor(ms / 1000)
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  return h > 0 ? `${h}h ${m}m` : `${m}m`
}

const BADGE: Record<string, string> = {
  idle: 'badge bg-gray-800 text-gray-500',
  pending: 'badge-pending',
  active: 'badge-active',
  fault: 'badge bg-red-900/40 text-red-300 border border-red-700/50',
}

function StateBadge({ state }: { state?: string }) {
  const s = state ?? 'idle'
  return <span className={`text-[10px] ${BADGE[s] ?? BADGE.idle}`}>{s.toUpperCase()}</span>
}

export default function PedestalOverview({ pedestalId }: { pedestalId: number }) {
  const isAdmin = useAuthStore((s) => s.role) === 'admin'
  const {
    pedestals, optaStatusInfo, pedestalHealth, marinaDoorState,
    socketComputedStates, optaWaterStates,
  } = useStore()

  const pedestal = pedestals.find((p) => p.id === pedestalId)
  const statusInfo = optaStatusInfo[pedestalId]
  const health = pedestalHealth[pedestalId]
  const doorState = marinaDoorState[pedestalId]
  const smartMode = statusInfo?.smart_mode ?? health?.smart_mode ?? false

  const [usage, setUsage] = useState<{ sid: number; label: string; resource: 'electricity' | 'water' } | null>(null)
  const [alarms, setAlarms] = useState<{ sid: number; label: string } | null>(null)

  return (
    <div className="space-y-3">
      {/* ── Cabinet status ─────────────────────────────────────────────── */}
      <div className="card space-y-2">
        <div className="flex items-center justify-between">
          <span className="text-sm font-medium text-gray-100">📡 Cabinet Status</span>
          <div className="flex items-center gap-2">
            <span className={`badge text-[10px] ${smartMode
              ? 'bg-green-900/40 text-green-300 border border-green-700/50'
              : 'bg-gray-800 text-gray-400 border border-gray-700'}`}>
              {smartMode ? 'Smart Mode: ON' : 'Smart Mode: OFF'}
            </span>
            <span className="flex items-center gap-1 text-xs text-gray-400">
              <span className={`w-2 h-2 rounded-full ${health?.opta_connected ? 'bg-green-400 animate-pulse' : 'bg-gray-600'}`} />
              {health?.opta_connected ? 'Connected' : 'Offline'}
            </span>
          </div>
        </div>
        <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
          <span className="text-gray-500">{statusInfo?.cabinet_id ? 'Cabinet ID' : 'Name'}</span>
          <span className="text-gray-300 font-mono">{statusInfo?.cabinet_id ?? pedestal?.name ?? '—'}</span>
          {statusInfo && (
            <>
              <span className="text-gray-500">Uptime</span>
              {/* v3.40 — a RETAINED status is the cabinet's last-known state
                  replayed by the broker, not a live reading. Label it, or a
                  weeks-old uptime reads as if the cabinet were up right now. */}
              <span className="text-gray-300 font-mono">
                {fmtUptime(statusInfo.uptime_ms)}
                {statusInfo.retained && (
                  <span
                    className="ml-1.5 font-sans text-[10px] text-amber-400"
                    title="Last known value replayed by the MQTT broker — the cabinet has not reported since."
                  >
                    last known
                  </span>
                )}
              </span>
            </>
          )}
          <span className="text-gray-500">Door</span>
          <span className={`font-medium ${doorState === 'open' ? 'text-red-400' : doorState === 'closed' ? 'text-gray-300' : 'text-gray-600'}`}>
            {doorState === 'open' ? '🔓 OPEN' : doorState === 'closed' ? '🔒 Closed' : '—'}
          </span>
        </div>
      </div>

      {/* ── Electricity sockets ────────────────────────────────────────── */}
      <div>
        <p className="text-xs text-gray-500 uppercase tracking-wider mb-2">Electricity Sockets</p>
        <div className="grid grid-cols-2 gap-2">
          {SOCKETS.map((name) => {
            const sid = Number(name.replace('Q', ''))
            const state = socketComputedStates[`${pedestalId}-${sid}`]
            return (
              <div key={name} className="rounded-lg border border-gray-700 bg-gray-800/40 p-3 space-y-2">
                <div className="flex items-center justify-between">
                  <span className="text-sm font-medium text-gray-100">🔌 Socket {sid}</span>
                  <div className="flex items-center gap-1.5">
                    <button type="button" onClick={() => setUsage({ sid, label: name, resource: 'electricity' })}
                      className="text-[10px] px-1.5 py-0.5 rounded border border-gray-600 text-gray-300 hover:bg-gray-700/60"
                      title="Usage history + monthly report">Usage</button>
                    <button type="button" onClick={() => setAlarms({ sid, label: name })}
                      className="text-[10px] px-1.5 py-0.5 rounded border border-gray-600 text-gray-300 hover:bg-gray-700/60"
                      title="Operational alarms history">Alarms</button>
                    <StateBadge state={state} />
                  </div>
                </div>
                <SocketBreakerPanel pedestalId={pedestalId} socketId={sid} isAdmin={isAdmin} onFeedback={noop} mode="monitor" />
                <SocketLoadMeterPanel pedestalId={pedestalId} socketId={sid} socketName={name} isAdmin={isAdmin} onFeedback={noop} mode="monitor" />
              </div>
            )
          })}
        </div>
      </div>

      {/* ── Water valves ───────────────────────────────────────────────── */}
      <div>
        <p className="text-xs text-gray-500 uppercase tracking-wider mb-2">Water Valves</p>
        <div className="grid grid-cols-2 gap-2">
          {VALVES.map((name) => {
            const vid = Number(name.replace('V', ''))
            const vs = optaWaterStates[`${pedestalId}-${name}`]
            const state = vs?.state ?? 'idle'
            return (
              <div key={name} className="rounded-lg border border-gray-700 bg-gray-800/40 p-3 space-y-1">
                <div className="flex items-center justify-between">
                  <span className="text-sm font-medium text-gray-100">💧 Valve {name}</span>
                  <div className="flex items-center gap-1.5">
                    <button type="button" onClick={() => setUsage({ sid: vid, label: name, resource: 'water' })}
                      className="text-[10px] px-1.5 py-0.5 rounded border border-gray-600 text-gray-300 hover:bg-gray-700/60"
                      title="Water usage history + monthly report">Usage</button>
                    <StateBadge state={state} />
                  </div>
                </div>
                {vs ? (
                  <div className="text-xs text-gray-500 space-y-0.5">
                    {vs.hw_status && <p>hw: <span className="text-gray-400 font-mono">{vs.hw_status}</span></p>}
                    <div className="flex gap-4">
                      <p>Total: <span className="text-gray-300 font-mono">{vs.total_l.toFixed(1)} L</span></p>
                      <p>Session: <span className="text-gray-300 font-mono">{vs.session_l.toFixed(1)} L</span></p>
                    </div>
                  </div>
                ) : (
                  <p className="text-xs text-gray-600">No data received yet</p>
                )}
              </div>
            )
          })}
        </div>
      </div>

      {usage && (
        <SocketUsageHistoryModal
          pedestalId={pedestalId} socketId={usage.sid} resource={usage.resource}
          label={usage.label} isAdmin={isAdmin} onClose={() => setUsage(null)}
        />
      )}
      {alarms && (
        <OperationalAlarmsModal
          pedestalId={pedestalId} socketId={alarms.sid} label={alarms.label}
          onClose={() => setAlarms(null)}
        />
      )}
    </div>
  )
}
