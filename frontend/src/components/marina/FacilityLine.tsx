/**
 * One facility on a berth row, or one water outlet on the cabinet strip.
 *
 * THE RULE THIS COMPONENT EXISTS TO ENFORCE: when a control cannot be used, there is NO
 * CONTROL ELEMENT IN THE DOM. Not `disabled`, not `pointer-events-none`, not greyed —
 * absent, with one sentence in its place.
 *
 * `TC-UIR-03` asserts it by querying for the button and expecting to find nothing. A
 * `disabled` attribute would pass a "cannot be clicked" test while still showing marina staff
 * a control that looks like it should work.
 *
 * One figure per facility and nothing else — watts, or litres per minute. Temperature,
 * moisture, amps, phases and kWh totals do not appear at L1 at all.
 */

export type FigureUnit = string

export function FacilityLine({
  label,
  on,
  figure,
  unit,
  available,
  unavailableSentence,
  actionLabel,
  onAction,
  busy = false,
  note,
  stateWord,
}: {
  label: string
  on: boolean
  /** null renders as an em dash. NEVER as 0 — "measured nothing" is a different claim. */
  figure: number | null
  unit: FigureUnit
  available: boolean
  /** Shown in place of the control. Required when `available` is false. */
  unavailableSentence?: string
  actionLabel?: string
  onAction?: () => void
  busy?: boolean
  /** e.g. "(also berths 1, 2, 4)" — a monitoring clarification, never a billing caveat. */
  note?: string
  /** For a valve: 'unknown' must read differently from 'idle'. */
  stateWord?: string
}) {
  return (
    <div className="flex items-baseline gap-3 py-1 flex-wrap">
      <span className="text-sm text-gray-400 w-16 shrink-0">{label}</span>

      <span className="text-sm font-medium text-gray-100 w-20 shrink-0 whitespace-nowrap">
        {stateWord ?? (on ? 'ON' : 'OFF')}
      </span>

      {/* The one figure. Tabular so a column of rows lines up, large enough to read at arm's
          length on a wall-mounted screen. */}
      <span className="text-base font-semibold text-gray-50 tabular-nums min-w-[7rem]">
        {figure === null ? (
          <span className="text-gray-500" title="Not measured">—</span>
        ) : (
          <>
            {figure.toLocaleString()} <span className="text-sm font-normal text-gray-400">{unit}</span>
          </>
        )}
      </span>

      {available && actionLabel && onAction ? (
        <button
          type="button"
          onClick={onAction}
          disabled={busy}
          className="text-xs px-2.5 py-1 rounded border border-blue-700/60 bg-blue-900/40 text-blue-100 hover:bg-blue-800/60 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-400 disabled:opacity-50"
        >
          {busy ? 'Working…' : actionLabel}
        </button>
      ) : (
        /* NO button here. The sentence replaces it. */
        !available && unavailableSentence && (
          <span className="text-xs text-gray-400 italic">{unavailableSentence}</span>
        )
      )}

      {note && <span className="text-xs text-gray-500 basis-full pl-16">{note}</span>}
    </div>
  )
}
