import { useMemo } from 'react'
import { Link } from 'react-router-dom'
import { switchFacility, type MarinaPedestal } from '../../api/marina'
import { statusSortKey, TONE, guardFault } from './Status'
import { ControlledLine } from './ControlledLine'
import { BerthRow } from './BerthRow'

/**
 * L1 — one pedestal on the marina dashboard: its berth rows, then the cabinet-level pool of
 * water, the light and guard. Split out of MarinaDashboard.tsx (§9, block 4, 2026-10-15)
 * unchanged.
 */
export function PedestalBlock({ pedestal, showAll, onChanged }: {
  pedestal: MarinaPedestal
  showAll: boolean
  onChanged: () => void
}) {
  const berths = useMemo(() => {
    // `unknown` BELONGS in the needs-attention view, and leaving it out was a real bug the
    // e2e specs caught: a pedestal that has gone silent produces only `unknown` berths, so
    // the default filter rendered an EMPTY dashboard — the exact blank screen this profile
    // exists to avoid, in the exact situation where someone needs to be told.
    //
    // "We cannot see berth 3" needs a person as much as "berth 3 has a leak" does. What
    // differs is where they go: the pedestal, not the berth. That is why the two keep
    // separate STATUSES and separate sentences, and why `unknown` sorts below `attention`
    // rather than being filtered out.
    const rows = showAll
      ? [...pedestal.berths]
      : pedestal.berths.filter((b) => b.status === 'attention' || b.status === 'unknown')
    return rows.sort((a, b) => {
      const k = statusSortKey(a.status) - statusSortKey(b.status)
      if (k !== 0) return k
      return (a.berth_number ?? 9999) - (b.berth_number ?? 9999)
    })
  }, [pedestal.berths, showAll])

  const standalone = !pedestal.smart_mode

  return (
    <section className="border border-gray-700 rounded bg-gray-900/40">
      <header className="flex flex-wrap items-center gap-2 px-3 py-2 border-b border-gray-700">
        <h2 className="text-sm font-semibold text-gray-100">
          {pedestal.dock ? `Dock ${pedestal.dock}` : 'Pedestal'}
          {pedestal.cabinet_id && (
            <span className="ml-2 text-xs font-normal text-gray-500 font-mono">
              {pedestal.cabinet_id}
            </span>
          )}
        </h2>
        <span className="ml-auto text-xs text-gray-400">
          {pedestal.alarm_count > 0
            ? `${pedestal.alarm_count} alarm${pedestal.alarm_count === 1 ? '' : 's'}`
            : 'No alarms'}
        </span>
      </header>

      {berths.length === 0 ? (
        <p className="px-3 py-3 text-sm text-gray-400">
          {showAll
            ? 'No berths are set up on this pedestal yet.'
            : 'Nothing needs attention here, and every berth is reporting.'}
        </p>
      ) : (
        <ul className="divide-y divide-gray-800">
          {berths.map((b) => (
            <BerthRow
              key={b.berth_id}
              berth={b}
              pedestalId={pedestal.pedestal_id}
              standalone={standalone}
              onChanged={onChanged}
            />
          ))}
        </ul>
      )}

      {/* Water is a CABINET-LEVEL pool. The two valves are not piped to specific berths —
          a customer walks to whichever is free and scans the tag on it. Putting a water line
          on each berth row would claim a relationship the plumbing does not have. */}
      <div className="px-3 py-2 border-t border-gray-800">
        <div className="flex items-baseline gap-2 mb-1">
          <h3 className="text-[11px] uppercase tracking-wide text-gray-500">
            Water — shared, {pedestal.water_outlets.length} outlets
          </h3>
          <Link
            to="/marina/water"
            className="text-[11px] text-blue-300 hover:underline ml-auto focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-400"
          >
            Details ›
          </Link>
        </div>
        {pedestal.water_outlets.length === 0 ? (
          <p className="text-xs text-gray-500">
            This pedestal has not reported any water outlets.
          </p>
        ) : (
          pedestal.water_outlets.map((w) => (
            <ControlledLine
              key={w.outlet}
              testId={`water-${w.outlet}`}
              label={w.outlet}
              facility={w}
              stateWord={w.state === 'unknown' ? 'Not known' : w.on ? 'IN USE' : 'FREE'}
              figure={w.litres_per_min}
              unit={w.unit}
              confirmText={(a) => (a === 'off' ? `Close ${w.outlet}? The session on it ends.` : undefined)}
              onSwitch={(a) => switchFacility(pedestal.pedestal_id, { kind: 'valve', outlet: w.outlet }, a)}
              onDone={onChanged}
              note={
                w.state === 'unknown'
                  ? 'The pedestal has not reported this outlet recently.'
                  : w.rated_liters_per_min
                    ? `up to ${w.rated_liters_per_min} L/min`
                    : undefined
              }
            />
          ))
        )}
      </div>

      {/* Light and guard are one per cabinet, so four berth rows would be four views of one
          switch. Kept here, labelled, rather than repeated per row. */}
      <div className="px-3 py-2 border-t border-gray-800 flex flex-wrap gap-x-6 gap-y-1 items-baseline">
        <ControlledLine
          testId="light"
          label="Light"
          facility={pedestal.light}
          figure={null}
          unit=""
          // One light per cabinet: a tap switches it for every berth, so say so first (§5.1).
          confirmText={(a) => `This light covers ${berthList(pedestal)}. Turn it ${a} for all of them?`}
          onSwitch={(a) => switchFacility(pedestal.pedestal_id, { kind: 'light' }, a)}
          onDone={onChanged}
          note={`Covers every berth on this pedestal`}
        />
        <Link
          to="/marina/guard"
          className="text-sm text-gray-400 hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-400"
        >
          Guard{' '}
          <span
            className={
              pedestal.guard.state === 'on'
                ? TONE.okText
                : guardFault(pedestal.guard.state)
                  ? TONE.noticeText
                  : 'text-gray-300'
            }
          >
            {/* The server's sentence verbatim (§5.5.1). 'not_answering' is a fault and must
                never be shown as 'off', which would claim a decision nobody made. */}
            {pedestal.guard.sentence}
          </span>
        </Link>
      </div>
    </section>
  )
}

function berthList(p: MarinaPedestal): string {
  const n = p.berths.map((b) => b.berth_number).filter((x): x is number => x != null)
    .sort((a, b) => a - b)
  if (n.length === 0) return 'every berth on this pedestal'
  if (n.length === 1) return `berth ${n[0]}`
  return `berths ${n.slice(0, -1).join(', ')} and ${n[n.length - 1]}`
}
