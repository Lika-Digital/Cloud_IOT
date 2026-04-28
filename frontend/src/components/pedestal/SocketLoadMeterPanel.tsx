import { useEffect, useState } from 'react'
import { useStore } from '../../store'
import {
  getSocketLoad,
  patchLoadThresholds,
  type LoadStatus,
} from '../../api/meterLoad'

// v3.11 — per-socket meter Hardware Info + load bar(s) + threshold editor.
// Sibling component to SocketBreakerPanel; no breaker fields are touched here.
//
// Layout:
//   1. Read-only Hardware Info (meter type, phases, rated amps, modbus addr).
//      "Awaiting hardware configuration from device" if hw_config_received_at is null.
//   2. Load bars: single bar for 1Φ, three stacked bars for 3Φ.
//      Bar fill driven by load_pct; color by load_status.
//   3. Secondary meter readings (voltage, power kW, PF, frequency).
//   4. Admin-only threshold editor (warning + critical %).

interface Props {
  pedestalId: number
  socketId: number
  socketName: string
  isAdmin: boolean
  onFeedback: (key: string, type: 'success' | 'error', text: string) => void
}

const STATUS_BAR_COLOR: Record<LoadStatus, string> = {
  normal:   'bg-green-500',
  warning:  'bg-yellow-500',
  critical: 'bg-red-500 animate-pulse',
  unknown:  'bg-gray-500',
}

const STATUS_TEXT: Record<LoadStatus, string> = {
  normal:   'Normal',
  warning:  'High load',
  critical: 'CRITICAL load — act now',
  unknown:  'Unknown',
}

const STATUS_BADGE_CLASS: Record<LoadStatus, string> = {
  normal:   'bg-green-900/40 border-green-700/60 text-green-300',
  warning:  'bg-yellow-900/40 border-yellow-700/60 text-yellow-200',
  critical: 'bg-red-900/40 border-red-700/60 text-red-200 animate-pulse',
  unknown:  'bg-gray-800 border-gray-700 text-gray-400',
}

function fmtNum(v: number | null | undefined, digits = 1, suffix = ''): string {
  if (v === null || v === undefined) return '—'
  return `${v.toFixed(digits)}${suffix}`
}

function PhaseBar({ amps, rated, label }: { amps: number | null | undefined; rated: number | null; label: string }) {
  const pct = (amps != null && rated && rated > 0) ? Math.min(100, (amps / rated) * 100) : 0
  // Phase bars use neutral blue. The aggregate status banner above the
  // bars conveys the alarm state via color + animation.
  return (
    <div className="flex items-center gap-2 text-[10px]">
      <span className="w-6 text-gray-400 font-mono">{label}</span>
      <div className="flex-1 h-2 bg-gray-900/60 rounded overflow-hidden">
        <div
          className="h-full bg-blue-500/80 transition-[width]"
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="w-16 text-right text-gray-300 font-mono">
        {fmtNum(amps, 1, 'A')}
      </span>
    </div>
  )
}

export default function SocketLoadMeterPanel({
  pedestalId, socketId, socketName, isAdmin, onFeedback,
}: Props) {
  const key = `${pedestalId}-${socketId}`
  const hwCfg = useStore((s) => s.socketHardwareConfig[key])
  const live = useStore((s) => s.socketLoadStates[key])
  const setLoadState = useStore((s) => s.setLoadState)

  const [warnInput, setWarnInput] = useState<number>(60)
  const [critInput, setCritInput] = useState<number>(80)
  const [busy, setBusy] = useState(false)

  // Initial fetch — populates store via setLoadState even if no WS event has arrived yet.
  useEffect(() => {
    let cancelled = false
    getSocketLoad(pedestalId, socketId)
      .then((r) => {
        if (cancelled) return
        setLoadState(pedestalId, socketId, {
          current_amps: r.current_amps,
          voltage_v: r.voltage_v,
          power_kw: r.power_kw,
          power_factor: r.power_factor,
          energy_kwh: r.energy_kwh,
          frequency_hz: r.frequency_hz,
          current_l1: r.current_l1 ?? null,
          current_l2: r.current_l2 ?? null,
          current_l3: r.current_l3 ?? null,
          voltage_l1: r.voltage_l1 ?? null,
          voltage_l2: r.voltage_l2 ?? null,
          voltage_l3: r.voltage_l3 ?? null,
          load_pct: r.load_pct,
          load_status: r.load_status,
          warning_threshold_pct: r.warning_threshold_pct,
          critical_threshold_pct: r.critical_threshold_pct,
        })
        setWarnInput(r.warning_threshold_pct)
        setCritInput(r.critical_threshold_pct)
      })
      .catch(() => { /* fine — defaults stay; WS will populate later */ })
    return () => { cancelled = true }
  }, [pedestalId, socketId, setLoadState])

  const phases = hwCfg?.phases ?? null
  const isThreePhase = phases === 3
  const status: LoadStatus = live?.load_status ?? 'unknown'
  const ratedAmps = hwCfg?.rated_amps ?? null
  const totalAmps = live?.current_amps ?? null
  const loadPct = live?.load_pct ?? null

  const handleSaveThresholds = async () => {
    if (warnInput < 1 || warnInput > 99 || critInput < 1 || critInput > 99) {
      onFeedback(`load-${socketName}-thresh`, 'error', 'Thresholds must be between 1 and 99')
      return
    }
    if (warnInput >= critInput) {
      onFeedback(`load-${socketName}-thresh`, 'error', 'Warning must be strictly less than critical')
      return
    }
    setBusy(true)
    try {
      const updated = await patchLoadThresholds(pedestalId, socketId, warnInput, critInput)
      setLoadState(pedestalId, socketId, {
        warning_threshold_pct: updated.warning_threshold_pct,
        critical_threshold_pct: updated.critical_threshold_pct,
      })
      onFeedback(`load-${socketName}-thresh`, 'success', 'Thresholds saved')
    } catch (err) {
      const e = err as { response?: { data?: { detail?: string } } }
      onFeedback(`load-${socketName}-thresh`, 'error', e?.response?.data?.detail ?? 'Save failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="rounded-lg border border-gray-700 bg-gray-800/40 p-3 space-y-2">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-base">⚡</span>
          <span className="text-sm font-medium text-white">Load — {socketName}</span>
        </div>
        <span
          className={`text-[10px] font-medium px-2 py-0.5 rounded border ${STATUS_BADGE_CLASS[status]}`}
          aria-live="polite"
        >
          {status === 'critical' ? '🔴 ' : status === 'warning' ? '⚠️ ' : ''}
          {STATUS_TEXT[status]}
        </span>
      </div>

      {/* Hardware Info — read only. v3.11 D1. */}
      <div className="text-[11px] space-y-0.5">
        {!hwCfg?.hw_config_received_at ? (
          <p className="text-amber-300">Awaiting hardware configuration from device</p>
        ) : (
          <>
            <p className="text-gray-400">
              meter: <span className="text-gray-200 font-mono">{hwCfg.meter_type ?? '—'}</span>
              {' · '}
              phases: <span className="text-gray-200 font-mono">{phases ?? '—'}</span>
              {' · '}
              rated: <span className="text-gray-200 font-mono">{fmtNum(ratedAmps, 0, 'A')}</span>
            </p>
            <p className="text-gray-500">
              modbus: <span className="text-gray-300 font-mono">{hwCfg.modbus_address ?? '—'}</span>
              {' · '}
              hw report: <span className="text-gray-300 font-mono">{hwCfg.hw_config_received_at?.replace('T', ' ').slice(0, 19) ?? '—'}</span>
            </p>
          </>
        )}
      </div>

      {/* Load bars — phase-aware. v3.11 D10. */}
      {hwCfg?.hw_config_received_at && ratedAmps && (
        <div className="space-y-1.5 pt-1 border-t border-gray-700/50">
          {isThreePhase ? (
            <>
              <PhaseBar amps={live?.current_l1} rated={ratedAmps} label="L1" />
              <PhaseBar amps={live?.current_l2} rated={ratedAmps} label="L2" />
              <PhaseBar amps={live?.current_l3} rated={ratedAmps} label="L3" />
              <p className="text-[11px] text-gray-400 pt-0.5">
                total: <span className="text-gray-200 font-mono">{fmtNum(totalAmps, 1, 'A')}</span>
                {' / '}
                <span className="text-gray-300 font-mono">{fmtNum(ratedAmps, 0, 'A')}</span>
                {' — '}
                <span className={`font-mono ${
                  status === 'critical' ? 'text-red-300' :
                  status === 'warning'  ? 'text-yellow-300' :
                  'text-gray-300'
                }`}>
                  {fmtNum(loadPct, 0, '%')}
                </span>
              </p>
            </>
          ) : (
            <>
              <div className="flex items-center gap-2 text-xs">
                <div className="flex-1 h-3 bg-gray-900/60 rounded overflow-hidden">
                  <div
                    className={`h-full ${STATUS_BAR_COLOR[status]} transition-[width]`}
                    style={{ width: `${Math.min(100, loadPct ?? 0)}%` }}
                  />
                </div>
                <span className="w-24 text-right text-gray-300 font-mono">
                  {fmtNum(totalAmps, 1, 'A')} / {fmtNum(ratedAmps, 0, 'A')}
                </span>
              </div>
              <p className="text-[11px] text-gray-400">
                load: <span className={`font-mono ${
                  status === 'critical' ? 'text-red-300' :
                  status === 'warning'  ? 'text-yellow-300' :
                  'text-gray-300'
                }`}>
                  {fmtNum(loadPct, 0, '%')}
                </span>
              </p>
            </>
          )}
        </div>
      )}

      {/* Secondary meter readings */}
      {hwCfg?.hw_config_received_at && live && (
        <div className="text-[11px] text-gray-500 grid grid-cols-2 gap-x-3 pt-1 border-t border-gray-700/50">
          {isThreePhase ? (
            <>
              <p>V L1: <span className="text-gray-300 font-mono">{fmtNum(live.voltage_l1, 1, 'V')}</span></p>
              <p>V L2: <span className="text-gray-300 font-mono">{fmtNum(live.voltage_l2, 1, 'V')}</span></p>
              <p>V L3: <span className="text-gray-300 font-mono">{fmtNum(live.voltage_l3, 1, 'V')}</span></p>
              <p>P: <span className="text-gray-300 font-mono">{fmtNum(live.power_kw, 2, ' kW')}</span></p>
              <p>PF: <span className="text-gray-300 font-mono">{fmtNum(live.power_factor, 2)}</span></p>
              <p>f: <span className="text-gray-300 font-mono">{fmtNum(live.frequency_hz, 1, ' Hz')}</span></p>
            </>
          ) : (
            <>
              <p>V: <span className="text-gray-300 font-mono">{fmtNum(live.voltage_v, 1, 'V')}</span></p>
              <p>P: <span className="text-gray-300 font-mono">{fmtNum(live.power_kw, 2, ' kW')}</span></p>
              <p>PF: <span className="text-gray-300 font-mono">{fmtNum(live.power_factor, 2)}</span></p>
              <p>f: <span className="text-gray-300 font-mono">{fmtNum(live.frequency_hz, 1, ' Hz')}</span></p>
            </>
          )}
        </div>
      )}

      {/* Admin-only threshold editor */}
      {isAdmin && (
        <div className="pt-1 border-t border-gray-700/50 space-y-1.5">
          <p className="text-[11px] text-gray-400">Thresholds (% of rated current)</p>
          <div className="flex gap-2 items-center">
            <label className="flex-1 text-[11px] text-gray-400">
              warn
              <input
                type="number"
                min={1}
                max={99}
                value={warnInput}
                onChange={(e) => setWarnInput(Number(e.target.value))}
                className="ml-1 w-14 bg-gray-900/60 border border-gray-700 rounded px-1.5 py-0.5 text-xs text-white font-mono"
                aria-label={`Warning threshold for ${socketName}`}
              />
              <span className="ml-1 text-gray-500">%</span>
            </label>
            <label className="flex-1 text-[11px] text-gray-400">
              crit
              <input
                type="number"
                min={1}
                max={99}
                value={critInput}
                onChange={(e) => setCritInput(Number(e.target.value))}
                className="ml-1 w-14 bg-gray-900/60 border border-gray-700 rounded px-1.5 py-0.5 text-xs text-white font-mono"
                aria-label={`Critical threshold for ${socketName}`}
              />
              <span className="ml-1 text-gray-500">%</span>
            </label>
            <button
              type="button"
              onClick={handleSaveThresholds}
              disabled={busy}
              className="text-xs px-2 py-0.5 rounded border border-gray-600 text-gray-200 hover:bg-gray-700/60 disabled:opacity-40"
            >
              {busy ? 'Saving…' : 'Save'}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
