import { useState } from 'react'
import type { ControlAction, UnavailableReason } from '../../api/marina'
import { FacilityLine } from './FacilityLine'

/**
 * A facility line that can be switched — row controls, block 4 (2026-10-15).
 *
 * The SERVER decides what one tap does (`action`) or why nothing can be done
 * (`unavailable_reason`); this component never works it out. One sentence per reason, from
 * the table below, and no control element in its place.
 *
 * After a tap it says what is actually known: the command was SENT — the row changes when the
 * pedestal reports back, on the next refresh. A refusal shows the server's own sentence, which
 * knows the rule that was broken (water without a scan, §15); a missing answer says that it is
 * not known whether anything switched, rather than guessing either way.
 */

export const UNAVAILABLE_SENTENCE: Record<NonNullable<UnavailableReason>, string> = {
  no_socket: 'No electricity socket at this berth',
  no_contact: 'No contact with the pedestal, so it cannot be switched from here',
  standalone: 'The pedestal is switching this itself',
  read_only: 'View only: your account cannot switch outlets',
  state_unknown: 'Not known whether it is free, so it is not switched from here',
  nothing_plugged: 'Nothing is plugged in',
  needs_scan: 'Water opens after the customer scans their card at the valve',
}

interface Switchable {
  on: boolean
  action: ControlAction
  available: boolean
  unavailable_reason: UnavailableReason
}

type Phase =
  | { kind: 'idle' }
  | { kind: 'confirming' }
  | { kind: 'busy' }
  | { kind: 'sent' }
  | { kind: 'failed'; message: string }

function refusal(e: unknown): string {
  const err = e as { response?: { status?: number; data?: { detail?: unknown } } }
  const detail = err?.response?.data?.detail
  // A refusal is an answer: nothing was switched, and the server says why.
  if (typeof detail === 'string' && detail) return `Not switched: ${detail}`
  if (err?.response?.status === 403) return 'Not switched: your account cannot switch outlets.'
  if (err?.response?.status) return `Not switched: the server refused (${err.response.status}).`
  // No answer is NOT a refusal — the command may have gone out.
  return 'No answer from the server. Whether it switched is not known; the row shows the '
    + 'pedestal\'s report on the next refresh.'
}

export function ControlledLine({
  label,
  facility,
  figure,
  unit,
  stateWord,
  note,
  confirmText,
  onSwitch,
  onDone,
  testId,
}: {
  label: string
  facility: Switchable
  figure: number | null
  unit: string
  stateWord?: string
  note?: string
  /** Asked before the tap acts — for a switch that affects more than this line suggests. */
  confirmText?: (action: 'on' | 'off') => string | undefined
  onSwitch: (action: 'on' | 'off') => Promise<unknown>
  onDone: () => void
  testId?: string
}) {
  const [phase, setPhase] = useState<Phase>({ kind: 'idle' })
  const action = facility.action
  const question = action ? confirmText?.(action) : undefined

  const run = async () => {
    if (!action) return
    setPhase({ kind: 'busy' })
    try {
      await onSwitch(action)
      setPhase({ kind: 'sent' })
      onDone()
    } catch (e) {
      setPhase({ kind: 'failed', message: refusal(e) })
    }
  }

  const tap = () => {
    if (question && phase.kind !== 'confirming') setPhase({ kind: 'confirming' })
    else run()
  }

  return (
    <div data-testid={testId}>
      <FacilityLine
        label={label}
        on={facility.on}
        figure={figure}
        unit={unit}
        stateWord={stateWord}
        // `!= null`: an older payload without the field offers nothing, never a guessed tap.
        available={facility.available && action != null}
        unavailableSentence={
          facility.unavailable_reason ? UNAVAILABLE_SENTENCE[facility.unavailable_reason] : undefined
        }
        actionLabel={phase.kind === 'confirming'
          ? `Yes, turn ${action}`
          : action === 'on' ? 'Turn on' : 'Turn off'}
        onAction={tap}
        busy={phase.kind === 'busy'}
        note={note}
      />
      {phase.kind === 'confirming' && question && (
        <div className="pl-16 flex flex-wrap items-baseline gap-2 text-xs">
          <span className="text-gray-200">{question}</span>
          <button
            type="button"
            onClick={() => setPhase({ kind: 'idle' })}
            className="px-2 py-0.5 rounded border border-gray-600 text-gray-300 hover:bg-gray-700/60 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-400"
          >
            Cancel
          </button>
        </div>
      )}
      {phase.kind === 'sent' && (
        <p className="pl-16 text-xs text-gray-400" role="status">
          Sent. The line changes when the pedestal reports back.
        </p>
      )}
      {phase.kind === 'failed' && (
        <p className="pl-16 text-xs text-gray-200" role="alert">
          {phase.message}
        </p>
      )}
    </div>
  )
}
