import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { TONE } from '../../components/marina/Status'
import { getMarinaCore, type MarinaCore } from '../../api/marina'
import { UNAVAILABLE_SENTENCE } from '../../components/marina/ControlledLine'

/**
 * L2 — water, in detail.
 *
 * WATER IS A POOL, NOT A BERTH FACILITY. Two valves serve a maximum of two users at a time,
 * and they are not piped to specific berths: a customer walks to whichever is free and scans
 * the tag on it. So this screen is organised by OUTLET, and it answers the two questions a
 * customer standing at the pedestal actually asks — "is one free?" and "how much is running?"
 *
 * It deliberately does NOT try to say which berth is using an outlet. Attribution is by
 * scanned tag and lives in the ERP; inventing a berth column here would be a guess printed as
 * a fact, and the customer's name is not shown to marina staff in any case.
 */

type State =
  | { kind: 'loading' }
  | { kind: 'ready'; core: MarinaCore }
  | { kind: 'error'; message: string; stale: MarinaCore | null }

function describeError(e: unknown): string {
  const err = e as { response?: { status?: number } }
  const s = err?.response?.status
  if (s === 401 || s === 403) return 'You are not signed in any more. Please sign in again.'
  if (s && s >= 500) return 'The server could not answer. It may be restarting.'
  return 'Cannot reach the server.'
}

/** The three words a water outlet can be in. There is no `pending` — see below. */
function stateWords(state: string, on: boolean): { word: string; cls: string; note?: string } {
  if (state === 'unknown') {
    return {
      word: 'Not known',
      cls: 'bg-gray-800 text-gray-400 border-gray-600 border-dashed',
      // `unknown` must not read as `idle`: "the cabinet has not told us" and "the outlet is
      // free" lead to different actions, and a customer sent to an outlet we know nothing
      // about walks to the far end of the pontoon to find out.
      note: 'The pedestal has not reported this outlet recently.',
    }
  }
  if (on || state === 'active') {
    return { word: 'In use', cls: 'bg-blue-900/40 text-blue-200 border-blue-700/50' }
  }
  return { word: 'Free', cls: TONE.ok }
}

export default function MarinaWater() {
  const [state, setState] = useState<State>({ kind: 'loading' })

  const load = useCallback(async () => {
    try {
      setState({ kind: 'ready', core: await getMarinaCore() })
    } catch (e) {
      setState((prev) => ({
        kind: 'error',
        message: describeError(e),
        stale: prev.kind === 'ready' ? prev.core : prev.kind === 'error' ? prev.stale : null,
      }))
    }
  }, [])

  useEffect(() => {
    load()
    const t = setInterval(load, 15_000)
    return () => clearInterval(t)
  }, [load])

  const core = state.kind === 'ready' ? state.core : state.kind === 'error' ? state.stale : null

  if (state.kind === 'loading') {
    return <div className="p-4 text-sm text-gray-400" role="status">Loading water outlets…</div>
  }

  if (!core) {
    return (
      <div className="p-4 max-w-md" data-testid="water-error">
        <Back />
        <p className={`text-sm ${TONE.noticeText} my-3`}>
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
    <div className="p-3 sm:p-4 max-w-3xl" data-testid="marina-water">
      <Back />
      <h1 className="text-lg font-semibold text-gray-100 mt-2 mb-1">Water</h1>
      <p className="text-xs text-gray-400 mb-3">
        Water outlets are shared across each pedestal — any berth can use any free outlet.
      </p>

      {state.kind === 'error' && (
        <p
          className={`text-xs border ${TONE.notice} rounded px-2 py-1.5 mb-3`}
          data-testid="water-stale-banner"
        >
          {state.message} Showing the last readings — they may be out of date.
        </p>
      )}

      <div className="flex flex-col gap-4">
        {core.pedestals.map((p) => {
          const free = p.water_outlets.filter((w) => !w.on && w.state === 'idle').length
          const unknown = p.water_outlets.filter((w) => w.state === 'unknown').length
          return (
            <section key={p.pedestal_id} className="border border-gray-700 rounded bg-gray-900/40">
              <header className="flex flex-wrap items-center gap-2 px-3 py-2 border-b border-gray-700">
                <h2 className="text-sm font-semibold text-gray-100">
                  {p.dock ? `Dock ${p.dock}` : 'Pedestal'}
                  {p.cabinet_id && (
                    <span className="ml-2 text-xs font-normal text-gray-500 font-mono">
                      {p.cabinet_id}
                    </span>
                  )}
                </h2>
                <span className="ml-auto text-xs text-gray-400">
                  {unknown > 0
                    ? `${unknown} outlet${unknown === 1 ? '' : 's'} not reporting`
                    : `${free} of ${p.water_outlets.length} free`}
                </span>
              </header>

              {p.water_outlets.length === 0 ? (
                <p className="px-3 py-3 text-sm text-gray-400">
                  This pedestal has not reported any water outlets.
                </p>
              ) : (
                <ul className="divide-y divide-gray-800">
                  {p.water_outlets.map((w) => {
                    const s = stateWords(w.state, w.on)
                    return (
                      <li key={w.outlet} className="px-3 py-3">
                        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                          <span className="text-base font-semibold text-gray-50 font-mono w-10">
                            {w.outlet}
                          </span>
                          <span
                            className={`text-xs px-2 py-0.5 rounded border font-medium whitespace-nowrap ${s.cls}`}
                          >
                            {s.word}
                          </span>
                          <span className="text-lg font-semibold text-gray-50 tabular-nums ml-auto">
                            {/* An em dash, never 0 — "not measured" is not "measured nothing". */}
                            {w.litres_per_min === null ? (
                              <span className="text-gray-500" title="Not measured">—</span>
                            ) : (
                              <>
                                {w.litres_per_min}{' '}
                                <span className="text-sm font-normal text-gray-400">{w.unit}</span>
                              </>
                            )}
                          </span>
                        </div>

                        <p className="text-xs text-gray-500 mt-1">
                          {s.note ??
                            (w.rated_liters_per_min
                              ? `Up to ${w.rated_liters_per_min} L/min`
                              : 'Flow rate not reported by this cabinet yet')}
                        </p>

                        {/* No control when the NUC cannot act — the element is ABSENT, and a
                            sentence takes its place. Never a greyed-out button. */}
                        {!w.available && (
                          <p className="text-xs text-gray-400 italic mt-1">
                            {/* The same sentence as the dashboard row, from one table — the
                                reason is the server's (block 4, row controls). */}
                            {w.unavailable_reason
                              ? UNAVAILABLE_SENTENCE[w.unavailable_reason]
                              : 'This outlet cannot be switched from here'}
                          </p>
                        )}
                      </li>
                    )
                  })}
                </ul>
              )}
            </section>
          )
        })}
      </div>
    </div>
  )
}

function Back() {
  return (
    <Link
      to="/marina"
      className="text-sm text-blue-300 hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-400"
    >
      ‹ Back to marina
    </Link>
  )
}
