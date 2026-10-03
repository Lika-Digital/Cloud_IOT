import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { getMarinaCore, type GuardBlock, type MarinaCore } from '../../api/marina'

/**
 * L2 — guard, per pedestal.
 *
 * FOUR WORDS, AND ONE OF THEM IS NOT "OFF". `unavailable` is a FAULT — nothing is watching
 * and nobody chose that. `off` is a DECISION someone made. The whole liveness design behind
 * guard (the last will, the heartbeat, the in-memory `worker_seen_at`) exists to keep those
 * two apart, and rendering them the same would throw it away at the last step.
 *
 * Guard is per CAMERA, which is per pedestal — not per berth. On a four-berth cabinet the
 * events are the cabinet's, and this screen says so rather than letting someone attribute a
 * stranger near berth 1 to berth 3.
 *
 * NO NOTIFICATIONS. Not disabled, not behind a flag — absent. The owner's standing
 * instruction is that notifications stay off until a week has been watched, and a
 * built-and-disabled path is something that gets switched on by accident.
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

const GUARD_STYLE: Record<GuardBlock['state'], { cls: string; icon: string; help: string }> = {
  on: {
    cls: 'bg-green-900/30 text-green-300 border-green-700/50',
    icon: '●',
    help: 'The camera is watching this pedestal.',
  },
  paused: {
    cls: 'bg-amber-900/40 text-amber-200 border-amber-600/60',
    icon: '‖',
    help: 'Watching has stopped for now. It will resume on its own when the reason clears.',
  },
  off: {
    cls: 'bg-gray-800 text-gray-300 border-gray-600',
    icon: '○',
    help: 'Guard has been switched off for this pedestal. Nobody is watching, by choice.',
  },
  unavailable: {
    // Deliberately NOT the same grey as `off`. Dashed, amber text: this is a fault.
    cls: 'bg-gray-900 text-amber-200 border-amber-700/50 border-dashed',
    icon: '?',
    help: 'Guard is not answering, so nothing is being watched. This is a fault, not a '
        + 'setting — tell the office.',
  },
}

export default function MarinaGuard() {
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
    return <div className="p-4 text-sm text-gray-400" role="status">Loading guard…</div>
  }

  if (!core) {
    return (
      <div className="p-4 max-w-md" data-testid="guard-error">
        <Back />
        <p className="text-sm text-amber-200 my-3">
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
    <div className="p-3 sm:p-4 max-w-3xl" data-testid="marina-guard">
      <Back />
      <h1 className="text-lg font-semibold text-gray-100 mt-2 mb-1">Guard</h1>
      <p className="text-xs text-gray-400 mb-3">
        One camera per pedestal. It watches the whole pedestal, not a single berth.
      </p>

      {state.kind === 'error' && (
        <p
          className="text-xs text-amber-200 border border-amber-700/50 bg-amber-900/20 rounded px-2 py-1.5 mb-3"
          data-testid="guard-stale-banner"
        >
          {state.message} Showing the last readings — they may be out of date.
        </p>
      )}

      <div className="flex flex-col gap-3">
        {core.pedestals.map((p) => {
          const g = GUARD_STYLE[p.guard.state] ?? GUARD_STYLE.unavailable
          return (
            <section
              key={p.pedestal_id}
              className="border border-gray-700 rounded bg-gray-900/40 px-3 py-3"
            >
              <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
                <h2 className="text-sm font-semibold text-gray-100">
                  {p.dock ? `Dock ${p.dock}` : 'Pedestal'}
                  {p.cabinet_id && (
                    <span className="ml-2 text-xs font-normal text-gray-500 font-mono">
                      {p.cabinet_id}
                    </span>
                  )}
                </h2>
                <span
                  className={`text-xs px-2 py-0.5 rounded border font-medium whitespace-nowrap ml-auto ${g.cls}`}
                >
                  <span aria-hidden="true" className="mr-1">{g.icon}</span>
                  {/* The SERVER's sentence, not a local mapping. One source of words, so this
                      screen and the dashboard cannot describe the same state differently. */}
                  {p.guard.sentence}
                </span>
              </div>

              <p className="text-xs text-gray-400 mt-2">{g.help}</p>

              <p className="text-xs text-gray-500 mt-2">
                Guard covers every berth on this pedestal, so anything it sees may come from
                any of them.
              </p>
            </section>
          )
        })}
      </div>

      <p className="text-xs text-gray-500 mt-4 border-t border-gray-800 pt-3">
        Recordings and the review of what guard saw are handled from the office. This screen
        shows whether guard is watching.
      </p>
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
