import { Link } from 'react-router-dom'
import type { BerthDetail } from '../../api/marina'
import { TONE } from './Status'
import { Section } from './DetailSection'

/** The provenance wording. The number never appears without it. */
function sourceLabel(source: string | null): string {
  if (source === 'register') return 'meter reading'
  if (source === 'integrated_legacy') return 'estimated — meter unavailable'
  if (source === 'unknown') return 'not measured'
  return ''
}

/**
 * L2 — "This month": the berth's month-to-date electricity WITH its provenance, and the way
 * to the sessions behind it. Split out of BerthDetail.tsx (§9, block 4, 2026-10-15) unchanged.
 */
export function MonthFigure({ d }: { d: BerthDetail }) {
  const c = d.consumption
  return (
    <Section title="This month">
      <div className="flex items-baseline gap-3 flex-wrap">
        <span className="text-sm text-gray-400 w-24">Electricity</span>
        <span className="text-xl font-semibold text-gray-50 tabular-nums">
          {/* NEVER 0.0 for an unmeasurable month. The sum of a partial set is not the
              total, and showing one would be a silent under-report. */}
          {c.kwh === null ? <span className="text-gray-500">—</span> : `${c.kwh} kWh`}
        </span>
        {sourceLabel(c.source) && (
          <span className={`text-xs ${c.source === 'register' ? 'text-gray-500' : TONE.noticeText}`}>
            {sourceLabel(c.source)}
          </span>
        )}
      </div>
      {/* The note is suppressed when it only restates the provenance label beside the
          figure — "meter reading" followed by "Meter reading." is noise, and noise is what
          stops people reading the line that matters. It still shows when it adds something:
          "No sessions this month", or why a figure could not be measured. */}
      {c.note && c.note.replace(/[.\s]/g, '').toLowerCase()
        !== sourceLabel(c.source).replace(/[.\s]/g, '').toLowerCase() && (
        <p className="text-xs text-gray-500 mt-1">{c.note}</p>
      )}
      {/* L3 history: the sessions behind the figure above, month by month. */}
      <Link
        to={`/marina/berth/${d.berth_id}/history`}
        className="text-xs text-blue-300 hover:underline mr-4 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-400"
      >
        History ›
      </Link>
      {/* Analytics is L3 (block 4, nav): reached from here, not from the nav. */}
      <Link
        to={`/analytics?pedestal=${d.pedestal_id}`}
        className="text-xs text-blue-300 hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-400"
      >
        Pedestal consumption history ›
      </Link>
    </Section>
  )
}
