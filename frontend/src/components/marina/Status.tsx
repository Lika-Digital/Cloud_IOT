import type { BerthStatus } from '../../api/marina'

/**
 * The one way status is rendered in the marina profile.
 *
 * COLOUR + ICON + WORD, ALL THREE, ALWAYS — and the component makes that structural rather
 * than a review note. The UI v2 audit found the compliant cases were compliant by accident:
 * each component worded and coloured its own states, and the ones that got it right got it
 * right by luck.
 *
 * `status` and `sentence` are both required props. There is no way to render a colour alone
 * from here, and `TC-UIR-01` scans `pages/marina/**` and `components/marina/**` for raw
 * colour classes so no component can go around it.
 *
 * Three states and no more. `unknown` is NOT a shade of ok: it means the berth's condition is
 * genuinely not known, which leads to a different action than "fine" or "needs attention".
 */

export type StatusSize = 'row' | 'header'

const STYLES: Record<BerthStatus, { cls: string; icon: string; word: string }> = {
  // Each entry carries all three, so a new state cannot be added with only a colour.
  ok: {
    cls: 'bg-green-900/30 text-green-300 border-green-700/50',
    icon: '✓',
    word: 'OK',
  },
  attention: {
    cls: 'bg-amber-900/40 text-amber-200 border-amber-600/60',
    icon: '▲',
    word: 'Needs attention',
  },
  unknown: {
    // Dashed, and visibly not a filled state — "we cannot see this" must not look like a
    // quieter version of "fine". A customer sent to a berth we know nothing about walks to
    // the far end of the pontoon to find out.
    cls: 'bg-gray-800 text-gray-400 border-gray-600 border-dashed',
    icon: '?',
    word: 'Not known',
  },
}

export function Status({
  status,
  sentence,
  size = 'row',
}: {
  status: BerthStatus
  /** The server's sentence. Null only when status is `ok`. */
  sentence: string | null
  size?: StatusSize
}) {
  const s = STYLES[status] ?? STYLES.unknown
  const pad = size === 'header' ? 'px-3 py-1 text-sm' : 'px-2 py-0.5 text-xs'

  return (
    /* `flex-wrap` and NO truncation. At 380 px the sentence drops onto its own line under
       the badge rather than being clipped — "This outlet has not reported re..." told an
       operator nothing, on exactly the device this row is designed to be read on. A row that
       is two lines tall on a phone is the correct trade. */
    <span className="inline-flex items-baseline gap-x-2 gap-y-1 flex-wrap min-w-0">
      <span
        className={`inline-flex items-center gap-1.5 rounded border font-medium shrink-0 ${pad} ${s.cls}`}
        /* The word is inside the badge, so a screen reader and a colour-blind user get the
           same information as everyone else without a separate aria-label to keep in step. */
      >
        <span aria-hidden="true">{s.icon}</span>
        <span>{s.word}</span>
      </span>
      {sentence && <span className="text-sm text-gray-200">{sentence}</span>}
    </span>
  )
}

/**
 * The sort order for the dashboard: needs-attention first, then not-known, then berth number.
 *
 * Exported from here rather than written inline in the page, because "which rows are at the
 * top" is part of what the status means. On a phone the rows that need someone must be
 * visible without scrolling — that is the whole point of the screen.
 */
export function statusSortKey(status: BerthStatus): number {
  if (status === 'attention') return 0
  if (status === 'unknown') return 1
  return 2
}
