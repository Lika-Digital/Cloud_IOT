import { Link, useParams } from 'react-router-dom'
import { ConsumptionHistory } from '../../components/marina/ConsumptionHistory'

/**
 * L3 — /marina/water/:pedestalId/:outlet/history. One valve's water history (block 4,
 * 2026-10-15). Water is a pool, not a berth facility, so its history belongs to the valve;
 * without this, removing /history from the staff nav would take water history away.
 */
export default function WaterHistory() {
  const { pedestalId, outlet } = useParams<{ pedestalId: string; outlet: string }>()
  const valid = !!outlet && /^V[12]$/.test(outlet)
  return (
    <div className="p-3 sm:p-4 max-w-3xl" data-testid="water-history">
      <Link to="/marina/water"
        className="text-sm text-blue-300 hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-400">
        ‹ Back to water
      </Link>
      <h1 className="text-lg font-semibold text-gray-100 mt-2 mb-1">
        Water outlet <span className="font-mono">{valid ? outlet : '—'}</span>: history
      </h1>
      {!valid ? (
        <p className="text-sm text-gray-400">There is no such water outlet.</p>
      ) : (
        <>
          <p className="text-xs text-gray-500 mb-3">
            Months are calendar months in UTC, as in the monthly report.
          </p>
          <ConsumptionHistory pedestalId={Number(pedestalId)} resource="water"
            outletNumber={Number(outlet.slice(1))} outletLabel={outlet} />
        </>
      )}
    </div>
  )
}
