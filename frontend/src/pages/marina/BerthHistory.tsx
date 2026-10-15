import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { getBerthDetail, type BerthDetail } from '../../api/marina'
import { ConsumptionHistory } from '../../components/marina/ConsumptionHistory'
import { TONE } from '../../components/marina/Status'

/**
 * L3 — /marina/berth/:berthId/history. The electricity history of the socket that serves this
 * berth (block 4, 2026-10-15). Replaces the global /history list for staff: history without a
 * berth is a report, not a screen (§8).
 *
 * The berth has no water of its own — water is a pool of valves (§2.1) — so its water history
 * lives on each valve, reached from the water page.
 */
export default function BerthHistory() {
  const { berthId } = useParams<{ berthId: string }>()
  const [berth, setBerth] = useState<BerthDetail | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    getBerthDetail(Number(berthId)).then(setBerth).catch(() => setFailed(true))
  }, [berthId])

  const outlet = berth?.power.outlet ?? null          // "Q3"
  return (
    <div className="p-3 sm:p-4 max-w-3xl" data-testid="berth-history">
      <Link to={`/marina/berth/${berthId}`}
        className="text-sm text-blue-300 hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-400">
        ‹ Back to berth
      </Link>
      <h1 className="text-lg font-semibold text-gray-100 mt-2 mb-1">
        Berth {berth?.berth_number ?? '—'}: electricity history
      </h1>
      {failed && <p className={`text-sm ${TONE.noticeText}`}>That berth could not be loaded.</p>}
      {!failed && !berth && <p className="text-sm text-gray-400" role="status">Loading…</p>}
      {berth && !outlet && (
        <p className="text-sm text-gray-400">This berth has no electricity socket, so it has no electricity history.</p>
      )}
      {berth && outlet && (
        <>
          {/* Assignments can change (the wizard re-points a berth), and sessions are recorded
              per socket. Say whose history this is rather than imply the berth always had it. */}
          <p className="text-xs text-gray-500 mb-3">
            Sessions on socket <span className="font-mono">{outlet}</span>, which serves this berth now.
            Months are calendar months in UTC, as in the monthly report.
          </p>
          <ConsumptionHistory pedestalId={berth.pedestal_id} resource="electricity"
            outletNumber={Number(outlet.slice(1))} outletLabel={outlet} />
        </>
      )}
    </div>
  )
}
