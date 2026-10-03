import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { getMarinaAlarms, type MarinaAlarm } from '../../api/marina'

/**
 * L2 — the alarm list. Plain sentences, newest first, active ones on top.
 *
 * Every string here comes from the server's sentence table. There is NO mapping in this
 * component from an alarm type to words, because the moment there is one it drifts from the
 * dashboard's and the same condition reads two ways on two screens.
 *
 * This is a MARINA-SCOPED endpoint, not the admin alarm panel re-gated: re-gating would leak
 * admin diagnostic detail into this profile by default, and the next field added to the admin
 * payload would appear here without anyone deciding so.
 */

type State =
  | { kind: 'loading' }
  | { kind: 'ready'; alarms: MarinaAlarm[] }
  | { kind: 'error'; message: string; stale: MarinaAlarm[] | null }

function describeError(e: unknown): string {
  const err = e as { response?: { status?: number } }
  const s = err?.response?.status
  if (s === 401 || s === 403) return 'You are not signed in any more. Please sign in again.'
  if (s && s >= 500) return 'The server could not answer. It may be restarting.'
  return 'Cannot reach the server.'
}

function when(iso: string | null): string {
  if (!iso) return 'time not recorded'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return 'time not recorded'
  return d.toLocaleString(undefined, {
    day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit',
  })
}

export default function MarinaAlarms() {
  const [state, setState] = useState<State>({ kind: 'loading' })
  const [activeOnly, setActiveOnly] = useState(true)

  const load = useCallback(async () => {
    try {
      const { alarms } = await getMarinaAlarms()
      setState({ kind: 'ready', alarms })
    } catch (e) {
      setState((prev) => ({
        kind: 'error',
        message: describeError(e),
        stale: prev.kind === 'ready' ? prev.alarms : prev.kind === 'error' ? prev.stale : null,
      }))
    }
  }, [])

  useEffect(() => {
    load()
    const t = setInterval(load, 20_000)
    return () => clearInterval(t)
  }, [load])

  const alarms =
    state.kind === 'ready' ? state.alarms : state.kind === 'error' ? state.stale : null

  const shown = useMemo(
    () => (alarms ?? []).filter((a) => (activeOnly ? a.active : true)),
    [alarms, activeOnly],
  )
  const activeCount = (alarms ?? []).filter((a) => a.active).length

  if (state.kind === 'loading') {
    return <div className="p-4 text-sm text-gray-400" role="status">Loading alarms…</div>
  }

  if (!alarms) {
    return (
      <div className="p-4 max-w-md" data-testid="alarms-error">
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
    <div className="p-3 sm:p-4 max-w-3xl" data-testid="marina-alarms">
      <Back />

      <div className="flex flex-wrap items-center gap-3 mt-2 mb-3">
        <h1 className="text-lg font-semibold text-gray-100">Alarms</h1>
        <div className="flex gap-2 ml-auto">
          <button
            type="button"
            onClick={() => setActiveOnly(true)}
            aria-pressed={activeOnly}
            className={`text-xs px-2.5 py-1 rounded border ${
              activeOnly
                ? 'border-amber-600/60 bg-amber-900/40 text-amber-100'
                : 'border-gray-600 text-gray-300 hover:bg-gray-700/60'
            }`}
          >
            Still active ({activeCount})
          </button>
          <button
            type="button"
            onClick={() => setActiveOnly(false)}
            aria-pressed={!activeOnly}
            className={`text-xs px-2.5 py-1 rounded border ${
              !activeOnly
                ? 'border-blue-700/60 bg-blue-900/40 text-blue-100'
                : 'border-gray-600 text-gray-300 hover:bg-gray-700/60'
            }`}
          >
            All ({alarms.length})
          </button>
        </div>
      </div>

      {state.kind === 'error' && (
        <p
          className="text-xs text-amber-200 border border-amber-700/50 bg-amber-900/20 rounded px-2 py-1.5 mb-3"
          data-testid="alarms-stale-banner"
        >
          {state.message} Showing the last list — it may be out of date.
        </p>
      )}

      {shown.length === 0 ? (
        <p className="text-sm text-gray-400">
          {activeOnly ? 'Nothing is wrong right now.' : 'No alarms have been recorded.'}
        </p>
      ) : (
        <ul className="flex flex-col gap-2">
          {shown.map((a) => (
            <li
              key={a.alarm_id}
              className={`border rounded px-3 py-2 ${
                a.active
                  ? 'border-amber-700/50 bg-amber-900/15'
                  : 'border-gray-700 bg-gray-900/40'
              }`}
            >
              <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                {/* The server's sentence, verbatim. An error code on this screen is exactly
                    what the audit called out. */}
                <span className="text-sm font-medium text-gray-50">{a.sentence}</span>
                <span
                  className={`text-[11px] px-1.5 py-0.5 rounded border ${
                    a.active
                      ? 'bg-amber-900/40 text-amber-200 border-amber-600/60'
                      : 'bg-gray-800 text-gray-400 border-gray-600'
                  }`}
                >
                  {a.active ? 'Still active' : 'Cleared'}
                </span>
              </div>
              <p className="text-xs text-gray-400 mt-0.5">
                {a.cabinet_id ? (
                  <span className="font-mono">{a.cabinet_id}</span>
                ) : (
                  'Pedestal not identified'
                )}
                {' · '}
                {when(a.raised_at)}
                {!a.active && a.resolved_at && <> · cleared {when(a.resolved_at)}</>}
              </p>
            </li>
          ))}
        </ul>
      )}
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
