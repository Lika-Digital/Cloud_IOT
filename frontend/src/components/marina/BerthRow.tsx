import { Link } from 'react-router-dom'
import { switchFacility, type Berth } from '../../api/marina'
import { Status, TONE } from './Status'
import { ControlledLine } from './ControlledLine'

/**
 * L1 — one berth's row on the marina dashboard. Split out of MarinaDashboard.tsx (§9, block 4,
 * 2026-10-15) unchanged: status, occupancy, the power line with its controls, alarms.
 */
export function BerthRow({ berth, pedestalId, standalone, onChanged }: {
  berth: Berth
  pedestalId: number
  standalone: boolean
  onChanged: () => void
}) {
  const p = berth.power

  const occupancy = !berth.occupied_known
    ? 'We do not know if this berth is in use'
    : berth.occupied
      ? 'Occupied'
      : 'Empty'

  // null = NOT KNOWN (never analysed, analysis failed, no boat, nothing to compare) — never
  // "does not match": that is said only when the analysis measured a mismatch.
  const match =
    !berth.vessel_match_configured
      ? null
      : berth.vessel_matches === true
        ? 'photo matches'
        : berth.vessel_matches === false
          ? 'does not match the photo'
          : 'photo match not known'

  return (
    <li className="px-3 py-2.5">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 mb-1">
        <Link
          to={`/marina/berth/${berth.berth_id}`}
          className="text-base font-semibold text-gray-50 hover:text-blue-300 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-400"
        >
          Berth {berth.berth_number ?? '—'}
        </Link>
        <Status status={berth.status} sentence={berth.status_sentence} />
      </div>

      <p className="text-xs text-gray-400 mb-1">
        {occupancy}
        {match && ` · ${match}`}
      </p>

      <ControlledLine
        testId={`power-${berth.berth_id}`}
        label="Power"
        facility={p}
        figure={p.amps}
        unit={p.unit}
        confirmText={(a) => (a === 'off'
          ? `Turn off power at berth ${berth.berth_number ?? ''}? The session there ends.`
          : undefined)}
        onSwitch={(a) => switchFacility(pedestalId, { kind: 'socket', outlet: p.outlet ?? '' }, a)}
        onDone={onChanged}
        note={p.outlet ? `socket ${p.outlet}` : undefined}
      />

      {standalone && (
        <p className="text-xs text-gray-400 italic mt-1">
          The marina office can start and stop outlets here once this pedestal is reconnected.
        </p>
      )}

      {berth.alarm_count > 0 && (
        <Link
          to="/marina/alarms"
          className={`text-xs ${TONE.noticeText} hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-400`}
        >
          {berth.alarm_count} alarm{berth.alarm_count === 1 ? '' : 's'} ›
        </Link>
      )}
    </li>
  )
}
