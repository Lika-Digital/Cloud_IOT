import { useCallback, useEffect, useState } from 'react'
import { downloadUsageReport, getUsageHistory, type UsageResource, type UsageRow } from '../../api/usage'
import { useAuthStore } from '../../store/authStore'
import { TONE } from './Status'

/**
 * L3 — the completed sessions of ONE outlet, a month at a time (block 4, 2026-10-15).
 *
 * Session rows, not ledger rows: the §4.4 exception, for the reason the monthly report has it
 * — the ledger is not yet proven on the cabinet — and so this screen and the staff report say
 * the same thing about the same session. Every figure carries its provenance and the two
 * register readings it is the difference of. Unknown is "—", never 0.
 *
 * The month total follows the report's rule: if any session in it was not measured there is
 * NO total figure, only how many were not measured. A sum of the measured part looks exactly
 * like a total, and is not one.
 */

const UNIT: Record<UsageResource, string> = { electricity: 'kWh', water: 'L' }
const DIGITS: Record<UsageResource, number> = { electricity: 3, water: 1 }

export function currentMonth(now = new Date()): string {
  return now.toISOString().slice(0, 7)          // UTC, as the server's month filter
}

function shiftMonth(month: string, by: number): string {
  const [y, m] = month.split('-').map(Number)
  const d = new Date(Date.UTC(y, m - 1 + by, 1))
  return d.toISOString().slice(0, 7)
}

function monthName(month: string): string {
  const [y, m] = month.split('-').map(Number)
  return new Date(Date.UTC(y, m - 1, 1)).toLocaleString(undefined, { month: 'long', year: 'numeric', timeZone: 'UTC' })
}

/** The figure, or null when it is not a measurement we can stand behind. */
function figure(r: UsageRow): number | null {
  const v = r.type === 'water' ? r.water_liters : r.energy_kwh
  if (v == null) return null
  return r.consumption_source === 'register' || r.consumption_source === 'integrated_legacy' ? v : null
}

function provenance(r: UsageRow): string {
  if (figure(r) === null) {
    return r.consumption_source ? 'not measured' : 'not measured (no provenance recorded)'
  }
  return r.consumption_source === 'register' ? 'meter reading' : 'estimated, meter unavailable'
}

function duration(r: UsageRow): string {
  if (!r.started_at || !r.ended_at) return '—'
  const min = Math.round((new Date(r.ended_at).getTime() - new Date(r.started_at).getTime()) / 60000)
  return min < 60 ? `${min} min` : `${Math.floor(min / 60)} h ${min % 60} min`
}

type Load = { kind: 'loading' } | { kind: 'ready'; rows: UsageRow[] } | { kind: 'error' }

export function ConsumptionHistory({ pedestalId, resource, outletNumber, outletLabel }: {
  pedestalId: number
  resource: UsageResource
  /** The number the server filters on: 3 for Q3, 1 for V1. Never shown on its own. */
  outletNumber: number
  /** "Q3" / "V1" — the only way an outlet is named on screen (§4.5). */
  outletLabel: string
}) {
  const isAdmin = useAuthStore((s) => s.role) === 'admin'
  const [month, setMonth] = useState(currentMonth())
  const [state, setState] = useState<Load>({ kind: 'loading' })

  const load = useCallback(async () => {
    setState({ kind: 'loading' })
    try {
      setState({ kind: 'ready', rows: await getUsageHistory(pedestalId, resource, outletNumber, month) })
    } catch {
      setState({ kind: 'error' })
    }
  }, [pedestalId, resource, outletNumber, month])

  useEffect(() => { load() }, [load])

  const unit = UNIT[resource]
  const fmt = (v: number) => v.toFixed(DIGITS[resource])

  return (
    <section data-testid="consumption-history">
      <div className="flex flex-wrap items-center gap-2 mb-2">
        <button type="button" onClick={() => setMonth(shiftMonth(month, -1))}
          className="text-xs px-2 py-1 rounded border border-gray-600 text-gray-200 hover:bg-gray-700/60 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-400">
          ‹ Earlier
        </button>
        <h2 className="text-sm font-semibold text-gray-100" data-testid="history-month">{monthName(month)}</h2>
        {/* No "later" past the current month: absent, not disabled. */}
        {month < currentMonth() && (
          <button type="button" onClick={() => setMonth(shiftMonth(month, 1))}
            className="text-xs px-2 py-1 rounded border border-gray-600 text-gray-200 hover:bg-gray-700/60 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-400">
            Later ›
          </button>
        )}
        <button type="button" onClick={() => downloadUsageReport(pedestalId, month, isAdmin)}
          className="text-xs text-blue-300 hover:underline ml-auto focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-400">
          Monthly report (.txt)
        </button>
      </div>

      {state.kind === 'loading' && <p className="text-sm text-gray-400" role="status">Loading…</p>}
      {state.kind === 'error' && (
        <p className={`text-sm ${TONE.noticeText}`}>
          The history could not be loaded.{' '}
          <button type="button" onClick={load} className="underline">Try again</button>
        </p>
      )}
      {state.kind === 'ready' && <Rows rows={state.rows} unit={unit} fmt={fmt} outletLabel={outletLabel} month={month} />}
    </section>
  )
}

function Rows({ rows, unit, fmt, outletLabel, month }: {
  rows: UsageRow[]; unit: string; fmt: (v: number) => string; outletLabel: string; month: string
}) {
  if (rows.length === 0) {
    return <p className="text-sm text-gray-400">No completed sessions on {outletLabel} in {monthName(month)}.</p>
  }
  const unmeasured = rows.filter((r) => figure(r) === null).length
  const estimated = rows.filter((r) => figure(r) !== null && r.consumption_source === 'integrated_legacy')
  const total = rows.reduce((a, r) => a + (figure(r) ?? 0), 0)
  const est = estimated.reduce((a, r) => a + (figure(r) ?? 0), 0)

  return (
    <>
      <p className="text-sm text-gray-200 mb-2" data-testid="history-total">
        {unmeasured > 0
          ? `Total not shown: ${unmeasured} of ${rows.length} session(s) were not measured.`
          : `Total: ${fmt(total)} ${unit} across ${rows.length} session(s)`
            + (estimated.length ? ` (of which ${fmt(est)} ${unit} estimated)` : '')}
      </p>
      <ul className="divide-y divide-gray-800 text-sm" data-testid="history-rows">
        {rows.map((r) => {
          const v = figure(r)
          return (
            <li key={r.session_id} className="py-1.5 flex flex-wrap gap-x-3 gap-y-0.5 items-baseline">
              <span className="text-gray-300 w-40 shrink-0">
                {r.started_at ? new Date(r.started_at).toLocaleString() : '—'}
              </span>
              <span className="text-gray-500 w-20 shrink-0">{duration(r)}</span>
              <span className="text-gray-50 font-semibold tabular-nums w-24 shrink-0">
                {v === null ? <span className="text-gray-500">—</span> : `${fmt(v)} ${unit}`}
              </span>
              <span className={`text-xs ${v !== null && r.consumption_source === 'register' ? 'text-gray-500' : TONE.noticeText}`}>
                {provenance(r)}
              </span>
              {r.register_start != null && r.register_end != null && (
                <span className="text-xs text-gray-500 basis-full sm:basis-auto">
                  register {r.register_start} → {r.register_end} {unit}
                </span>
              )}
            </li>
          )
        })}
      </ul>
    </>
  )
}
