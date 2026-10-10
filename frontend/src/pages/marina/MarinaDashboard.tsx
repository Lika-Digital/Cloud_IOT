import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  getMarinaCore,
  type Berth,
  type MarinaCore,
  type MarinaPedestal,
} from '../../api/marina'
import { Status, statusSortKey } from '../../components/marina/Status'
import { FacilityLine } from '../../components/marina/FacilityLine'

/**
 * L1 — the marina dashboard. One row per berth, needs-attention first.
 *
 * Narrow-first: this must work at 360 px with no page-level horizontal scroll, because it is
 * read on a phone standing on a pontoon as often as on a wall-mounted screen.
 *
 * WHAT THIS COMPONENT DOES NOT DO: compute status. Every `status`, `status_sentence` and
 * `available` flag comes from CORE. There is no local rule about when a berth needs
 * attention, which is what keeps the web UI, the mobile app and the ERP saying the same thing.
 */

type LoadState =
  | { kind: 'loading' }
  | { kind: 'ready'; core: MarinaCore }
  /**
   * An error state that still says something useful. A dashboard that goes blank because one
   * call failed is worse than one that says "no contact" — and if a previous payload is in
   * hand, the rows stay on screen with a banner rather than disappearing. Stale data clearly
   * marked stale beats no data.
   */
  | { kind: 'error'; message: string; stale: MarinaCore | null }

const REFRESH_MS = 15_000

function describeError(e: unknown): string {
  const err = e as { response?: { status?: number }; code?: string; message?: string }
  const status = err?.response?.status
  if (status === 401 || status === 403) return 'You are not signed in any more. Please sign in again.'
  if (status === 404) return 'The marina dashboard is not available on this server.'
  if (status && status >= 500) return 'The server could not answer. It may be restarting.'
  if (err?.code === 'ECONNABORTED') return 'The server took too long to answer.'
  return 'Cannot reach the server.'
}

export default function MarinaDashboard() {
  const [state, setState] = useState<LoadState>({ kind: 'loading' })
  const [showAll, setShowAll] = useState(false)

  const load = useCallback(async () => {
    try {
      const core = await getMarinaCore()
      setState({ kind: 'ready', core })
    } catch (e) {
      setState((prev) => ({
        kind: 'error',
        message: describeError(e),
        // Keep whatever we last rendered, so a blip does not empty the screen.
        stale: prev.kind === 'ready' ? prev.core : prev.kind === 'error' ? prev.stale : null,
      }))
    }
  }, [])

  useEffect(() => {
    load()
    const t = setInterval(load, REFRESH_MS)
    return () => clearInterval(t)
  }, [load])

  const core = state.kind === 'ready' ? state.core : state.kind === 'error' ? state.stale : null

  const counts = useMemo(() => {
    // Counts what the filter SHOWS, including `unknown`. A button reading "Needs attention
    // (2)" that reveals four rows is its own small lie, and the two numbers drifting apart is
    // how someone stops trusting the filter.
    let needsSomeone = 0
    let total = 0
    for (const p of core?.pedestals ?? []) {
      for (const b of p.berths) {
        total += 1
        if (b.status === 'attention' || b.status === 'unknown') needsSomeone += 1
      }
    }
    return { needsSomeone, total }
  }, [core])

  if (state.kind === 'loading') {
    return (
      <div className="p-4 text-sm text-gray-400" role="status">
        Loading the marina…
      </div>
    )
  }

  if (!core) {
    // No payload at all, ever. The one case where there is nothing to show — so say what
    // happened and offer the only useful action.
    return (
      <div className="p-4 max-w-md" data-testid="marina-error">
        <h1 className="text-lg font-semibold text-gray-100 mb-2">Marina</h1>
        <p className="text-sm text-amber-200 mb-3">
          {state.kind === 'error' ? state.message : 'Cannot reach the server.'}
        </p>
        <button
          type="button"
          onClick={load}
          className="text-sm px-3 py-1.5 rounded border border-gray-600 text-gray-200 hover:bg-gray-700/60 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-400"
        >
          Try again
        </button>
      </div>
    )
  }

  return (
    <div className="p-3 sm:p-4" data-testid="marina-dashboard">
      <div className="flex flex-wrap items-center gap-3 mb-3">
        <h1 className="text-lg font-semibold text-gray-100">Marina</h1>
        <div className="flex gap-2 ml-auto">
          <button
            type="button"
            onClick={() => setShowAll(false)}
            aria-pressed={!showAll}
            className={`text-xs px-2.5 py-1 rounded border ${
              !showAll
                ? 'border-amber-600/60 bg-amber-900/40 text-amber-100'
                : 'border-gray-600 text-gray-300 hover:bg-gray-700/60'
            }`}
          >
            Needs attention ({counts.needsSomeone})
          </button>
          <button
            type="button"
            onClick={() => setShowAll(true)}
            aria-pressed={showAll}
            className={`text-xs px-2.5 py-1 rounded border ${
              showAll
                ? 'border-blue-700/60 bg-blue-900/40 text-blue-100'
                : 'border-gray-600 text-gray-300 hover:bg-gray-700/60'
            }`}
          >
            All ({counts.total})
          </button>
        </div>
      </div>

      {state.kind === 'error' && (
        /* Stale rows stay, clearly marked. Blanking the screen on one failed poll loses the
           operator's place and tells them nothing. */
        <p
          className="text-xs text-amber-200 border border-amber-700/50 bg-amber-900/20 rounded px-2 py-1.5 mb-3"
          data-testid="marina-stale-banner"
        >
          {state.message} Showing the last readings — they may be out of date.
        </p>
      )}

      {core.pedestals.length === 0 && (
        <p className="text-sm text-gray-400">
          No pedestals are set up yet. An administrator needs to add one.
        </p>
      )}

      <div className="flex flex-col gap-4">
        {core.pedestals.map((p) => (
          <PedestalBlock key={p.pedestal_id} pedestal={p} showAll={showAll} />
        ))}
      </div>
    </div>
  )
}

function PedestalBlock({ pedestal, showAll }: { pedestal: MarinaPedestal; showAll: boolean }) {
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
            <BerthRow key={b.berth_id} berth={b} standalone={standalone} />
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
            <FacilityLine
              key={w.outlet}
              label={w.outlet}
              on={w.on}
              stateWord={w.state === 'unknown' ? 'Not known' : w.on ? 'IN USE' : 'FREE'}
              figure={w.litres_per_min}
              unit={w.unit}
              available={w.available}
              unavailableSentence={
                w.unavailable_reason === 'standalone'
                  ? 'The pedestal is switching this itself'
                  : undefined
              }
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
        <FacilityLine
          label="Light"
          on={pedestal.light.on}
          figure={null}
          unit=""
          available={pedestal.light.available}
          unavailableSentence={
            pedestal.light.unavailable_reason === 'standalone'
              ? 'The pedestal is switching this itself'
              : undefined
          }
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
                ? 'text-green-300'
                : pedestal.guard.state === 'unavailable'
                  ? 'text-amber-200'
                  : 'text-gray-300'
            }
          >
            {/* The server's sentence verbatim. 'unavailable' is a fault and must never be
                shown as 'off', which would claim a decision nobody made. */}
            {pedestal.guard.sentence}
          </span>
        </Link>
      </div>
    </section>
  )
}

function BerthRow({ berth, standalone }: { berth: Berth; standalone: boolean }) {
  const p = berth.power

  const occupancy = !berth.occupied_known
    ? 'We do not know if this berth is in use'
    : berth.occupied
      ? 'Occupied'
      : 'Empty'

  const match =
    !berth.vessel_match_configured
      ? null
      : berth.vessel_matches
        ? 'photo matches'
        : 'does not match the photo'

  return (
    <li className="px-3 py-2.5">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 mb-1">
        <Link
          to={`/marina/berth/${berth.berth_id}`}
          className="text-base font-semibold text-gray-50 hover:text-blue-300 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-400"
        >
          Berth {berth.berth_number ?? '—'}
        </Link>
        <Status status={berth.status} sentence={berth.status_sentence} />
      </div>

      <p className="text-xs text-gray-400 mb-1">
        {occupancy}
        {match && ` · ${match}`}
      </p>

      <FacilityLine
        label="Power"
        on={p.on}
        figure={p.amps}
        unit={p.unit}
        available={p.available}
        unavailableSentence={
          p.unavailable_reason === 'no_socket'
            ? 'No electricity socket at this berth'
            : 'The pedestal is switching this itself'
        }
        note={p.outlet ? `socket ${p.outlet}` : undefined}
      />

      {standalone && (
        <p className="text-xs text-gray-400 italic mt-1">
          The marina office can start and stop outlets here once this pedestal is reconnected.
        </p>
      )}

      {berth.alarm_count > 0 && (
        <Link
          to="/marina/alarms"
          className="text-xs text-amber-200 hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-400"
        >
          {berth.alarm_count} alarm{berth.alarm_count === 1 ? '' : 's'} ›
        </Link>
      )}
    </li>
  )
}
