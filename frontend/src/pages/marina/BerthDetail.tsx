import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import {
  getBerthDetail, switchFacility, type BerthDetail as BerthDetailData,
} from '../../api/marina'
import { Status, TONE } from '../../components/marina/Status'
import { ControlledLine } from '../../components/marina/ControlledLine'
import { PhaseBlock } from '../../components/marina/PhaseBlock'
import { Row, Section } from '../../components/marina/DetailSection'
import { MonthFigure } from '../../components/marina/MonthFigure'

/**
 * L2 — one berth, with the detail L1 deliberately leaves out.
 *
 * This is where someone goes to investigate, so it carries the things a row must not: which
 * socket serves this berth and at what rating, the month-to-date figure WITH its provenance,
 * and the vessel photo. Still no temperature, moisture, breaker state or CPU — those are
 * cabinet health and live in the admin profile.
 *
 * §9 (block 4, 2026-10-15): "This month" is components/marina/MonthFigure.tsx, the section and
 * row blocks components/marina/DetailSection.tsx.
 */

type State =
  | { kind: 'loading' }
  | { kind: 'ready'; data: BerthDetailData }
  | { kind: 'error'; message: string }

function describeError(e: unknown): string {
  const err = e as { response?: { status?: number } }
  const s = err?.response?.status
  if (s === 404) return 'That berth no longer exists.'
  if (s === 401 || s === 403) return 'You are not signed in any more. Please sign in again.'
  if (s && s >= 500) return 'The server could not answer. It may be restarting.'
  return 'Cannot reach the server.'
}

export default function BerthDetail() {
  const { berthId } = useParams<{ berthId: string }>()
  const [state, setState] = useState<State>({ kind: 'loading' })

  const load = useCallback(async () => {
    if (!berthId) return
    try {
      setState({ kind: 'ready', data: await getBerthDetail(Number(berthId)) })
    } catch (e) {
      setState({ kind: 'error', message: describeError(e) })
    }
  }, [berthId])

  useEffect(() => {
    load()
    const t = setInterval(load, 15_000)
    return () => clearInterval(t)
  }, [load])

  if (state.kind === 'loading') {
    return <div className="p-4 text-sm text-gray-400" role="status">Loading the berth…</div>
  }

  if (state.kind === 'error') {
    return (
      <div className="p-4 max-w-md" data-testid="berth-error">
        <BackLink />
        <p className={`text-sm ${TONE.noticeText} my-3`}>{state.message}</p>
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

  const d = state.data
  const spec = d.outlet_spec

  return (
    <div className="p-3 sm:p-4 max-w-3xl" data-testid="berth-detail">
      <BackLink />

      <div className="flex flex-wrap items-center gap-3 mt-2 mb-4">
        <h1 className="text-xl font-semibold text-gray-50">
          Berth {d.berth_number ?? '—'}
        </h1>
        <Status status={d.status} sentence={d.status_sentence} size="header" />
      </div>

      {/* ── This berth ─────────────────────────────────────────────────────── */}
      <Section title="This berth">
        <dl className="text-sm">
          <Row label="Power">
            {spec.outlet ? (
              <>
                socket <span className="font-mono">{spec.outlet}</span>
                {/* Ratings come from the cabinet's own opta/config/hardware, never a
                    constant — Q1 is 32 A three-phase while Q3/Q4 are 16 A, and "this berth
                    is on a 16 A socket and the customer wants 32 A" is a question staff ask. */}
                {spec.rated_amps != null && <> · {spec.rated_amps} A</>}
                {spec.phases != null && (
                  <> · {spec.phases === 3 ? 'three phase' : 'single phase'}</>
                )}
                {spec.rated_amps == null && (
                  <span className="text-gray-500"> · rating not reported by this cabinet yet</span>
                )}
              </>
            ) : (
              <span className="text-gray-400">No electricity socket at this berth</span>
            )}
          </Row>
          <Row label="Water">
            <span className="text-gray-400">
              Shared across the pedestal — see the marina screen
            </span>
          </Row>
          <Row label="Pedestal">
            <span className="font-mono text-gray-300">{d.cabinet_id ?? '—'}</span>
          </Row>
        </dl>
      </Section>

      {/* ── Now ────────────────────────────────────────────────────────────── */}
      <Section title="Now">
        <ControlledLine
          testId="detail-power"
          label="Power"
          facility={d.power}
          figure={d.power.amps}
          unit={d.power.unit}
          confirmText={(a) => (a === 'off'
            ? `Turn off power at berth ${d.berth_number ?? ''}? The session there ends.`
            : undefined)}
          onSwitch={(a) => switchFacility(d.pedestal_id, { kind: 'socket', outlet: d.power.outlet ?? '' }, a)}
          onDone={load}
        />
        <PhaseBlock phases={d.power.phase_amps} />
      </Section>

      {/* ── This month ─────────────────────────────────────────────────────── */}
      <MonthFigure d={d} />

      {/* ── Vessel ─────────────────────────────────────────────────────────── */}
      <Section title="Vessel">
        {d.vessel_match_configured ? (
          <p className="text-sm text-gray-300">
            {d.vessel_matches === true
              ? 'The boat here matches the reference photo.'
              : d.vessel_matches === false
                ? 'The boat here does not match the reference photo.'
                : 'Not known whether a boat here matches the reference photo — the berth has '
                  + 'not been checked, the last check failed, or there was nothing to compare.'}
          </p>
        ) : (
          <p className="text-sm text-gray-400">
            No reference photo is set for this berth, so no check is made.
          </p>
        )}
        <p className="text-xs text-gray-500 mt-1">
          {d.occupied_known
            ? d.occupied
              ? 'The berth is occupied.'
              : 'The berth is empty.'
            : 'We do not know whether this berth is in use.'}
        </p>
      </Section>

      {/* ── Guard ──────────────────────────────────────────────────────────── */}
      <Section title="Guard">
        <p className="text-sm text-gray-200">{d.guard.sentence}</p>
        {/* One camera per pedestal, so the events are the CABINET's. Saying so prevents
            attributing a stranger walking past berth 1 to berth 3. */}
        <p className="text-xs text-gray-500 mt-1">{d.guard_scope_note}</p>
        <Link
          to="/marina/guard"
          className="text-xs text-blue-300 hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-400"
        >
          Open guard ›
        </Link>
      </Section>

      {d.alarm_count > 0 && (
        <Link
          to="/marina/alarms"
          className={`inline-block text-sm ${TONE.noticeText} hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-400`}
        >
          {d.alarm_count} alarm{d.alarm_count === 1 ? '' : 's'} at this pedestal ›
        </Link>
      )}
    </div>
  )
}

function BackLink() {
  return (
    <Link
      to="/marina"
      className="text-sm text-blue-300 hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-400"
    >
      ‹ Back to marina
    </Link>
  )
}
