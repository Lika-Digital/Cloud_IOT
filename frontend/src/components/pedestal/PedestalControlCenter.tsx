import { useState } from 'react'
import { useStore } from '../../store'
import { useAuthStore } from '../../store/authStore'
import {
  directSocketCmd,
  directWaterCmd,
  setLed,
  resetPedestal,
} from '../../api'
import type { OptaSocketState, OptaWaterState, OptaLogEntry } from '../../store'

// ─── Helpers ─────────────────────────────────────────────────────────────────

function fmtUptime(ms: number): string {
  if (!ms) return '—'
  const s = Math.floor(ms / 1000)
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = s % 60
  if (h > 0) return `${h}h ${m}m`
  if (m > 0) return `${m}m ${sec}s`
  return `${sec}s`
}

function fmtTs(ts: string): string {
  try {
    return new Date(ts).toLocaleTimeString()
  } catch {
    return ts
  }
}

function StateBadge({ state, title }: { state: string; title?: string }) {
  const cfg: Record<string, { color: string; dot: string }> = {
    active:      { color: 'bg-green-900/40 text-green-300 border-green-700/50', dot: 'bg-green-400 animate-pulse' },
    idle:        { color: 'bg-gray-800 text-gray-400 border-gray-700', dot: 'bg-gray-600' },
    fault:       { color: 'bg-red-900/40 text-red-300 border-red-700/50', dot: 'bg-red-400 animate-pulse' },
    // Plug inserted, session not yet activated. Mirrors the yellow socket
    // circle on the pedestal picture overlay.
    pending:     { color: 'bg-yellow-900/40 text-yellow-300 border-yellow-700/50', dot: 'bg-yellow-400 animate-pulse' },
    blocked:     { color: 'bg-amber-900/40 text-amber-300 border-amber-700/50', dot: 'bg-amber-400' },
  }
  const c = cfg[state] ?? cfg['idle']
  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium border ${c.color}`}
      title={title}
    >
      <span className={`w-1.5 h-1.5 rounded-full ${c.dot}`} />
      {state.toUpperCase()}
    </span>
  )
}

// ─── Feedback toast (inline) ──────────────────────────────────────────────────

interface CmdFeedback {
  key: string
  type: 'success' | 'error'
  text: string
}

function useCmdFeedback() {
  const [feedbacks, setFeedbacks] = useState<CmdFeedback[]>([])

  const show = (key: string, type: 'success' | 'error', text: string) => {
    setFeedbacks((prev) => [...prev.filter((f) => f.key !== key), { key, type, text }])
    setTimeout(() => setFeedbacks((prev) => prev.filter((f) => f.key !== key)), 3500)
  }

  return { feedbacks, show }
}

// ─── Socket card ─────────────────────────────────────────────────────────────

function SocketCard({
  socketName,
  socketState,
  pedestalId,
  computedState,
  isAdmin,
  onFeedback,
}: {
  socketName: string
  socketState: OptaSocketState | null
  pedestalId: number
  computedState: 'idle' | 'pending' | 'active' | 'fault' | undefined
  isAdmin: boolean
  onFeedback: (key: string, type: 'success' | 'error', text: string) => void
}) {
  const [loading, setLoading] = useState<string | null>(null)
  // Prefer the unified socket_state_changed broadcast when we have it —
  // otherwise fall back to the raw Opta firmware state string.
  const firmwareState = socketState?.state ?? 'idle'
  const state = computedState ?? firmwareState
  const label = `Socket ${socketName.replace('Q', '')}`
  const isPending = state === 'pending'
  const isActive = state === 'active'
  const isIdle = state === 'idle'
  const pendingTip = 'Plug inserted — awaiting activation'

  const sendCmd = async (action: string) => {
    setLoading(action)
    try {
      await directSocketCmd(pedestalId, socketName, action)
      onFeedback(`${socketName}-${action}`, 'success', `${action} sent to ${socketName}`)
    } catch {
      onFeedback(`${socketName}-${action}`, 'error', `Failed to send ${action} to ${socketName}`)
    } finally {
      setLoading(null)
    }
  }

  return (
    <div className="rounded-lg border border-gray-700 bg-gray-800/40 p-3 space-y-2">
      <div className="flex items-center justify-between">
        <div
          className="flex items-center gap-2"
          title={isPending ? pendingTip : undefined}
        >
          <span className="text-base">🔌</span>
          <span className="text-sm font-medium text-white">{label}</span>
          <span className="text-xs text-gray-500 font-mono">{socketName}</span>
        </div>
        <StateBadge state={state} title={isPending ? pendingTip : undefined} />
      </div>

      {socketState && (
        <div className="text-xs text-gray-500 space-y-0.5">
          {socketState.hw_status && (
            <p>hw: <span className="text-gray-400 font-mono">{socketState.hw_status}</span></p>
          )}
          {socketState.session != null && typeof socketState.session === 'object' && (
            <p>session: <span className="text-blue-400 font-mono">
              {String((socketState.session as Record<string, unknown>).customerId ?? JSON.stringify(socketState.session).slice(0, 40))}
            </span></p>
          )}
          <p className="text-gray-600">{fmtTs(socketState.timestamp)}</p>
        </div>
      )}

      {!socketState && (
        <p className="text-xs text-gray-600">No data received yet</p>
      )}

      {isAdmin && (
        <div className="flex gap-1.5 pt-1">
          {/* Only show Stop when the socket is actually active. Otherwise show
              Activate, which is only enabled for pending (plug inserted). */}
          {isActive ? (
            <CmdButton
              label="Stop"
              color="red"
              disabled={loading !== null}
              loading={loading === 'stop'}
              onClick={() => sendCmd('stop')}
            />
          ) : (
            <CmdButton
              label="Activate"
              color="green"
              disabled={!isPending || loading !== null}
              loading={loading === 'activate'}
              onClick={() => sendCmd('activate')}
              title={isIdle ? 'No plug inserted' : (isPending ? pendingTip : undefined)}
            />
          )}
        </div>
      )}
    </div>
  )
}

// ─── Water valve card ─────────────────────────────────────────────────────────

function WaterCard({
  valveName,
  valveState,
  pedestalId,
  isAdmin,
  onFeedback,
}: {
  valveName: string
  valveState: OptaWaterState | null
  pedestalId: number
  isAdmin: boolean
  onFeedback: (key: string, type: 'success' | 'error', text: string) => void
}) {
  const [loading, setLoading] = useState<string | null>(null)
  const state = valveState?.state ?? 'idle'
  const label = `Valve ${valveName}`

  const sendCmd = async (action: string) => {
    setLoading(action)
    try {
      await directWaterCmd(pedestalId, valveName, action)
      onFeedback(`${valveName}-${action}`, 'success', `${action} sent to ${valveName}`)
    } catch {
      onFeedback(`${valveName}-${action}`, 'error', `Failed to send ${action} to ${valveName}`)
    } finally {
      setLoading(null)
    }
  }

  return (
    <div className="rounded-lg border border-gray-700 bg-gray-800/40 p-3 space-y-2">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-base">💧</span>
          <span className="text-sm font-medium text-white">{label}</span>
          <span className="text-xs text-gray-500 font-mono">{valveName}</span>
        </div>
        <StateBadge state={state} />
      </div>

      {valveState && (
        <div className="text-xs text-gray-500 space-y-0.5">
          {valveState.hw_status && (
            <p>hw: <span className="text-gray-400 font-mono">{valveState.hw_status}</span></p>
          )}
          <div className="flex gap-4">
            <p>Total: <span className="text-gray-300 font-mono">{valveState.total_l.toFixed(1)} L</span></p>
            <p>Session: <span className="text-gray-300 font-mono">{valveState.session_l.toFixed(1)} L</span></p>
          </div>
          <p className="text-gray-600">{fmtTs(valveState.timestamp)}</p>
        </div>
      )}

      {!valveState && (
        <p className="text-xs text-gray-600">No data received yet</p>
      )}

      {isAdmin && (
        <div className="flex gap-1.5 pt-1">
          <CmdButton
            label="Activate"
            color="green"
            disabled={state === 'active' || loading !== null}
            loading={loading === 'activate'}
            onClick={() => sendCmd('activate')}
          />
          <CmdButton
            label="Stop"
            color="red"
            disabled={state === 'idle' || loading !== null}
            loading={loading === 'stop'}
            onClick={() => sendCmd('stop')}
          />
        </div>
      )}
    </div>
  )
}

// ─── LED control ─────────────────────────────────────────────────────────────

const LED_COLORS = ['green', 'red', 'blue', 'yellow', 'off'] as const
const LED_STATES = ['on', 'off', 'blink'] as const
const COLOR_SWATCH: Record<string, string> = {
  green: 'bg-green-500',
  red: 'bg-red-500',
  blue: 'bg-blue-500',
  yellow: 'bg-yellow-400',
  off: 'bg-gray-600',
}

function LedControl({
  pedestalId,
  isAdmin,
  onFeedback,
}: {
  pedestalId: number
  isAdmin: boolean
  onFeedback: (key: string, type: 'success' | 'error', text: string) => void
}) {
  const [color, setColor] = useState<string>('green')
  const [ledState, setLedState] = useState<string>('on')
  const [loading, setLoading] = useState(false)

  const send = async () => {
    setLoading(true)
    try {
      await setLed(pedestalId, color, ledState)
      onFeedback('led', 'success', `LED → ${color} / ${ledState}`)
    } catch {
      onFeedback('led', 'error', 'LED command failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="rounded-lg border border-gray-700 bg-gray-800/40 p-3 space-y-3">
      <div className="flex items-center gap-2">
        <span className="text-base">💡</span>
        <span className="text-sm font-medium text-white">LED Control</span>
      </div>

      <div>
        <p className="text-xs text-gray-500 mb-1.5">Color</p>
        <div className="flex flex-wrap gap-1.5">
          {LED_COLORS.map((c) => (
            <button
              key={c}
              onClick={() => setColor(c)}
              disabled={!isAdmin}
              className={`flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs border transition-all ${
                color === c
                  ? 'border-white bg-gray-700 text-white'
                  : 'border-gray-700 bg-gray-900 text-gray-400 hover:border-gray-500'
              } disabled:opacity-50`}
            >
              <span className={`w-2.5 h-2.5 rounded-full ${COLOR_SWATCH[c]}`} />
              {c}
            </button>
          ))}
        </div>
      </div>

      <div>
        <p className="text-xs text-gray-500 mb-1.5">State</p>
        <div className="flex gap-1.5">
          {LED_STATES.map((s) => (
            <button
              key={s}
              onClick={() => setLedState(s)}
              disabled={!isAdmin}
              className={`px-3 py-1 rounded-lg text-xs border transition-all ${
                ledState === s
                  ? 'border-blue-500 bg-blue-900/30 text-blue-300'
                  : 'border-gray-700 bg-gray-900 text-gray-400 hover:border-gray-500'
              } disabled:opacity-50`}
            >
              {s.toUpperCase()}
            </button>
          ))}
        </div>
      </div>

      {isAdmin && (
        <button
          onClick={send}
          disabled={loading}
          className="w-full py-1.5 rounded-lg bg-indigo-700 hover:bg-indigo-600 text-white text-xs font-medium transition-colors disabled:opacity-50 flex items-center justify-center gap-2"
        >
          {loading && <span className="w-3 h-3 rounded-full border-2 border-white border-t-transparent animate-spin" />}
          Send LED Command
        </button>
      )}
    </div>
  )
}

// ─── Log accordion ────────────────────────────────────────────────────────────

function LogAccordion({ title, icon, entries }: { title: string; icon: string; entries: OptaLogEntry[] }) {
  const [open, setOpen] = useState(false)

  return (
    <div className="rounded-lg border border-gray-700 bg-gray-800/30 overflow-hidden">
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center justify-between px-3 py-2.5 hover:bg-gray-800/60 transition-colors"
      >
        <div className="flex items-center gap-2">
          <span>{icon}</span>
          <span className="text-sm font-medium text-gray-300">{title}</span>
          <span className="text-xs text-gray-500 bg-gray-800 px-2 py-0.5 rounded-full">{entries.length}</span>
        </div>
        <span className="text-gray-500 text-xs">{open ? '▲' : '▼'}</span>
      </button>

      {open && (
        <div className="border-t border-gray-700/60 max-h-64 overflow-y-auto">
          {entries.length === 0 ? (
            <p className="text-xs text-gray-600 px-3 py-3">No entries yet. Waiting for MQTT messages…</p>
          ) : (
            <div className="divide-y divide-gray-800">
              {entries.map((e, i) => (
                <div key={i} className="px-3 py-2 text-xs">
                  <div className="flex items-center justify-between mb-0.5">
                    {e.cabinet_id && <span className="text-gray-500 font-mono">{e.cabinet_id}</span>}
                    <span className="text-gray-600 ml-auto">{fmtTs(e.timestamp)}</span>
                  </div>
                  <pre className="text-gray-400 whitespace-pre-wrap break-all font-mono leading-relaxed">
                    {typeof e.payload === 'string' ? e.payload : JSON.stringify(e.payload, null, 2).slice(0, 400)}
                  </pre>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ─── Inline command button ────────────────────────────────────────────────────

function CmdButton({
  label,
  color,
  disabled,
  loading,
  onClick,
  title,
}: {
  label: string
  color: 'green' | 'red' | 'blue'
  disabled: boolean
  loading: boolean
  onClick: () => void
  title?: string
}) {
  const cls = {
    green: 'bg-green-800/60 hover:bg-green-700/60 text-green-300 border-green-700/50',
    red:   'bg-red-900/40 hover:bg-red-800/50 text-red-300 border-red-700/50',
    blue:  'bg-blue-900/40 hover:bg-blue-800/50 text-blue-300 border-blue-700/50',
  }[color]

  return (
    <button
      onClick={onClick}
      disabled={disabled || loading}
      title={title}
      className={`flex-1 py-1 rounded text-xs font-medium border transition-colors disabled:opacity-40 ${cls} flex items-center justify-center gap-1`}
    >
      {loading && <span className="w-2.5 h-2.5 rounded-full border border-current border-t-transparent animate-spin" />}
      {label}
    </button>
  )
}

// ─── Main Control Center ──────────────────────────────────────────────────────

export default function PedestalControlCenter({ pedestalId }: { pedestalId: number }) {
  const { role } = useAuthStore()
  const isAdmin = role === 'admin'

  const {
    optaSocketStates,
    optaWaterStates,
    optaStatusInfo,
    optaEvents,
    optaAcks,
    pedestalHealth,
    marinaDoorState,
    pedestals,
    socketComputedStates,
  } = useStore()

  const { feedbacks, show } = useCmdFeedback()
  const [resetConfirm, setResetConfirm] = useState(false)
  const [resetLoading, setResetLoading] = useState(false)

  const pedestal = pedestals.find((p) => p.id === pedestalId)
  const health = pedestalHealth[pedestalId]
  const statusInfo = optaStatusInfo[pedestalId]
  const doorState = marinaDoorState[pedestalId]
  const events = optaEvents[pedestalId] ?? []
  const acks = optaAcks[pedestalId] ?? []

  const handleReset = async () => {
    if (!resetConfirm) { setResetConfirm(true); return }
    setResetLoading(true)
    setResetConfirm(false)
    try {
      await resetPedestal(pedestalId)
      show('reset', 'success', 'Reset command sent to device')
    } catch {
      show('reset', 'error', 'Reset command failed')
    } finally {
      setResetLoading(false)
    }
  }

  const SOCKETS = ['Q1', 'Q2', 'Q3', 'Q4']
  const VALVES = ['V1', 'V2']

  return (
    <div className="space-y-4">

      {/* Feedback toasts */}
      {feedbacks.length > 0 && (
        <div className="space-y-1.5">
          {feedbacks.map((f) => (
            <div
              key={f.key}
              className={`text-xs px-3 py-2 rounded-lg border ${
                f.type === 'success'
                  ? 'bg-green-900/30 text-green-400 border-green-700/40'
                  : 'bg-red-900/30 text-red-400 border-red-700/40'
              }`}
            >
              {f.text}
            </div>
          ))}
        </div>
      )}

      {/* ── Cabinet Status ──────────────────────────────────────────────── */}
      <div className="rounded-lg border border-gray-700 bg-gray-800/40 p-3">
        <div className="flex items-center gap-2 mb-2">
          <span className="text-base">📡</span>
          <span className="text-sm font-medium text-white">Cabinet Status</span>
          <span className={`ml-auto flex items-center gap-1.5 text-xs ${health?.opta_connected ? 'text-green-400' : 'text-gray-500'}`}>
            <span className={`w-2 h-2 rounded-full ${health?.opta_connected ? 'bg-green-400 animate-pulse' : 'bg-gray-600'}`} />
            {health?.opta_connected ? 'Connected' : 'Offline'}
          </span>
        </div>

        <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
          {statusInfo?.cabinet_id && (
            <>
              <span className="text-gray-500">Cabinet ID</span>
              <span className="text-gray-300 font-mono">{statusInfo.cabinet_id}</span>
            </>
          )}
          {!statusInfo?.cabinet_id && pedestal?.name && (
            <>
              <span className="text-gray-500">Name</span>
              <span className="text-gray-300">{pedestal.name}</span>
            </>
          )}
          {statusInfo && (
            <>
              <span className="text-gray-500">Seq</span>
              <span className="text-gray-300 font-mono">{statusInfo.seq}</span>
              <span className="text-gray-500">Uptime</span>
              <span className="text-gray-300 font-mono">{fmtUptime(statusInfo.uptime_ms)}</span>
            </>
          )}
          <span className="text-gray-500">Door</span>
          <span className={`font-medium ${doorState === 'open' ? 'text-red-400' : doorState === 'closed' ? 'text-gray-300' : 'text-gray-600'}`}>
            {doorState === 'open' ? '🔓 OPEN' : doorState === 'closed' ? '🔒 Closed' : '—'}
          </span>
          {health?.last_heartbeat && (
            <>
              <span className="text-gray-500">Last heartbeat</span>
              <span className="text-gray-500">{fmtTs(health.last_heartbeat)}</span>
            </>
          )}
        </div>
      </div>

      {/* ── Sockets Q1–Q4 ──────────────────────────────────────────────── */}
      <div>
        <p className="text-xs text-gray-500 uppercase tracking-wider mb-2">Electricity Sockets</p>
        <div className="grid grid-cols-2 gap-2">
          {SOCKETS.map((name) => {
            // Socket numeric id is the digit in Q1..Q4 (matches backend
            // broadcast key `${pedestal_id}-${socket_id}`).
            const socketId = Number(name.replace('Q', ''))
            return (
              <SocketCard
                key={name}
                socketName={name}
                socketState={optaSocketStates[`${pedestalId}-${name}`] ?? null}
                pedestalId={pedestalId}
                computedState={socketComputedStates[`${pedestalId}-${socketId}`]}
                isAdmin={isAdmin}
                onFeedback={show}
              />
            )
          })}
        </div>
      </div>

      {/* ── Water Valves V1–V2 ─────────────────────────────────────────── */}
      <div>
        <p className="text-xs text-gray-500 uppercase tracking-wider mb-2">Water Valves</p>
        <div className="grid grid-cols-2 gap-2">
          {VALVES.map((name) => (
            <WaterCard
              key={name}
              valveName={name}
              valveState={optaWaterStates[`${pedestalId}-${name}`] ?? null}
              pedestalId={pedestalId}
              isAdmin={isAdmin}
              onFeedback={show}
            />
          ))}
        </div>
      </div>

      {/* ── LED Control ────────────────────────────────────────────────── */}
      <LedControl pedestalId={pedestalId} isAdmin={isAdmin} onFeedback={show} />

      {/* ── Reset ──────────────────────────────────────────────────────── */}
      {isAdmin && (
        <div className="rounded-lg border border-red-900/50 bg-red-950/20 p-3 space-y-2">
          <div className="flex items-center gap-2">
            <span className="text-base">⚠️</span>
            <span className="text-sm font-medium text-red-300">Danger Zone</span>
          </div>
          <p className="text-xs text-gray-500">
            Sends a full reset command to the OPTA controller. All active sessions will be interrupted.
          </p>
          <button
            onClick={handleReset}
            disabled={resetLoading}
            className={`w-full py-2 rounded-lg text-sm font-medium transition-colors disabled:opacity-50 flex items-center justify-center gap-2 ${
              resetConfirm
                ? 'bg-red-600 hover:bg-red-500 text-white animate-pulse'
                : 'bg-red-900/40 hover:bg-red-800/50 text-red-300 border border-red-700/50'
            }`}
          >
            {resetLoading && <span className="w-3 h-3 rounded-full border-2 border-white border-t-transparent animate-spin" />}
            {resetConfirm ? 'Confirm Reset — Click Again!' : 'Reset Device'}
          </button>
          {resetConfirm && (
            <button
              onClick={() => setResetConfirm(false)}
              className="w-full text-xs text-gray-500 hover:text-gray-300 py-1"
            >
              Cancel
            </button>
          )}
        </div>
      )}

      {/* ── Event & ACK Logs ───────────────────────────────────────────── */}
      <LogAccordion
        title="Event Log"
        icon="📋"
        entries={events}
      />
      <LogAccordion
        title="Command ACK Log"
        icon="✅"
        entries={acks}
      />
    </div>
  )
}
