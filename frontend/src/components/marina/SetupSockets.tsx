import { useMemo } from 'react'
import type { CabinetOutlet } from '../../api/nfc'
import { TONE } from './Status'

export interface RowDraft {
  berth_id: number
  berth_number: number | null
  socket_id: number | null
}

/**
 * Wizard step 2 — which socket serves which berth, the one that matters. Split out of
 * MarinaSetup.tsx (§9, block 4, 2026-10-15) unchanged.
 */
export function SetupSockets({ rows, outlets, reported, duplicate, onPick }: {
  rows: RowDraft[]
  /** The cabinet's own sockets with ratings; empty = never reported, the standard set is offered. */
  outlets: CabinetOutlet[]
  reported: boolean | null
  /** A socket chosen for more than one berth, or null. */
  duplicate: number | null
  onPick: (berthId: number, socketId: number | null) => void
}) {
  /** A socket already taken by a DIFFERENT berth. Shown while choosing, not after saving. */
  const takenBy = useMemo(() => {
    const m = new Map<number, number>()
    for (const r of rows) {
      if (r.socket_id != null) m.set(r.socket_id, r.berth_id)
    }
    return m
  }, [rows])

  const rated = (n: number) => outlets.find((o) => o.outlet_name === `Q${n}`)?.rated_amps

  return (
    <section className="border border-gray-700 rounded bg-gray-900/40 p-3">
      <h2 className="text-sm font-semibold text-gray-100 mb-1">
        Which berths does it serve, and which socket each?
      </h2>
      <p className="text-xs text-gray-400 mb-3">
        Each berth has its own electricity socket. Water is shared across the pedestal, so
        there is nothing to choose for it.
      </p>

      {reported === false && (
        /* "Never heard from this cabinet" must not render the same as "this cabinet has
           no sockets". The admin is choosing from an assumed list and deserves to know. */
        <p className={`text-xs border ${TONE.notice} rounded px-2 py-1.5 mb-3`}>
          This pedestal has not reported its sockets yet, so the list below is the standard
          set. Ratings will appear once it does.
        </p>
      )}

      {rows.length === 0 ? (
        <p className="text-sm text-gray-400">
          No berths are set up for this pedestal yet. They are added in Berth Occupancy.
        </p>
      ) : (
        <ul className="flex flex-col gap-2">
          {rows.map((r) => (
            <li key={r.berth_id} className="flex flex-wrap items-center gap-2">
              <span className="text-sm text-gray-100 w-24">
                Berth {r.berth_number ?? r.berth_id}
              </span>
              <select
                value={r.socket_id ?? ''}
                onChange={(e) => onPick(r.berth_id, e.target.value === '' ? null : Number(e.target.value))}
                className="bg-gray-900 border border-gray-700 rounded px-2 py-1 text-sm text-gray-200 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-400"
              >
                <option value="">No socket</option>
                {(outlets.length
                  ? outlets.map((o) => Number(o.outlet_name.slice(1)))
                  : [1, 2, 3, 4]
                ).map((n) => (
                  <option key={n} value={n}>
                    Q{n}{rated(n) ? ` · ${rated(n)} A` : ''}
                  </option>
                ))}
              </select>
              {r.socket_id != null && takenBy.get(r.socket_id) !== r.berth_id && (
                /* Shown WHILE choosing, not after saving — the person sees the
                   consequence while they are still deciding. */
                <span className={`text-xs ${TONE.noticeText}`}>also chosen for another berth</span>
              )}
            </li>
          ))}
        </ul>
      )}

      {duplicate != null && (
        <p className={`text-xs ${TONE.noticeText} mt-3`} data-testid="setup-duplicate">
          Socket Q{duplicate} is chosen for more than one berth. A socket serves exactly one
          berth, or there is no way to tell whose electricity it was.
        </p>
      )}
    </section>
  )
}
