import { useCallback, useEffect, useMemo, useState } from 'react'
import { getMarinaCore, type MarinaCore } from '../../api/marina'
import { TONE } from '../../components/marina/Status'
import { PedestalBlock } from '../../components/marina/PedestalBlock'

/**
 * L1 — the marina dashboard. One row per berth, needs-attention first.
 *
 * Narrow-first: this must work at 360 px with no page-level horizontal scroll, because it is
 * read on a phone standing on a pontoon as often as on a wall-mounted screen.
 *
 * WHAT THIS COMPONENT DOES NOT DO: compute status. Every `status`, `status_sentence` and
 * `available` flag comes from CORE. There is no local rule about when a berth needs
 * attention, which is what keeps the web UI, the mobile app and the ERP saying the same thing.
 *
 * §9 (block 4, 2026-10-15): the pedestal block and the berth row live in
 * components/marina/PedestalBlock.tsx and BerthRow.tsx.
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
        <p className={`text-sm ${TONE.noticeText} mb-3`}>
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
                ? TONE.attentionSelected
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
          className={`text-xs border ${TONE.notice} rounded px-2 py-1.5 mb-3`}
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
          <PedestalBlock key={p.pedestal_id} pedestal={p} showAll={showAll} onChanged={load} />
        ))}
      </div>
    </div>
  )
}
