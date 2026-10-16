import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { TONE } from '../../components/marina/Status'
import { getMarinaCore, type GuardBlock, type MarinaCore, type MarinaPedestal } from '../../api/marina'
import { getGuardStatus, type GuardCamera } from '../../api/guard'
import { EventList, GuardButton } from '../../components/marina/GuardReview'
import { useAuthStore } from '../../store/authStore'

/**
 * L2 — guard, per pedestal (spec §5.5, owner 2026-10-16).
 *
 * ONE SENTENCE PER STATE, THE SERVER'S. "No guard on this pedestal", "Guard not answering",
 * "Guard on", "Guard off", "Guard paused — <reason>": the words come from the backend's one
 * function, the same one /api/guard/status uses, so this screen and the API cannot describe a
 * state differently. This file keeps colour and help text only — it never words a state.
 *
 * A FAILED READING IS "Not measured" (§5.5.6) — never the last sentence on its own, which would
 * make an old state look like a measurement. The last reading stands below with its time IN the
 * sentence ("last seen 15:42: Guard on"), and no button is offered from it.
 *
 * ADMIN ONLY — Arm / Switch off, the event list, the recording and the labels (§5.5.2, §5.5.5).
 * The server refuses them to any other role as well; hiding a button is not access control.
 *
 * Guard is per CAMERA, which is per pedestal — not per berth.
 *
 * NO NOTIFICATIONS. Absent, not disabled: the owner's standing instruction.
 */

type State =
  | { kind: 'loading' }
  | { kind: 'ready'; core: MarinaCore; at: Date }
  | { kind: 'error'; message: string; stale: MarinaCore | null; at: Date | null }

function describeError(e: unknown): string {
  const err = e as { response?: { status?: number } }
  const s = err?.response?.status
  if (s === 401 || s === 403) return 'You are not signed in any more. Please sign in again.'
  if (s && s >= 500) return 'The server could not answer. It may be restarting.'
  return 'Cannot reach the server.'
}

const hhmm = (d: Date) =>
  d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })

const GUARD_STYLE: Record<GuardBlock['state'], { cls: string; icon: string; help: string }> = {
  on: { cls: TONE.ok, icon: '●', help: 'The camera is watching this pedestal.' },
  paused: {
    cls: TONE.attention,
    icon: '‖',
    help: 'Guard is switched on and its worker is running, but it is not looking right now.',
  },
  off: {
    cls: 'bg-gray-800 text-gray-300 border-gray-600',
    icon: '○',
    help: 'Guard has been switched off for this pedestal. Nobody is watching, by choice.',
  },
  not_answering: {
    // Deliberately NOT the grey of `off`: this is a fault, nobody chose it.
    cls: TONE.fault,
    icon: '?',
    help: 'Guard is not answering, so nothing is being watched. This is a fault, not a '
        + 'setting — tell the office.',
  },
  none: {
    cls: 'bg-gray-900 text-gray-400 border-gray-700',
    icon: '–',
    help: 'No guard has ever reported from this pedestal.',
  },
  on_while_off: { cls: TONE.fault, icon: '!', // S6: a fault said aloud (§5.5.1)
    help: 'Switched off, but the camera reports it is recording. The switch-off has been sent.' },
  not_measured: {
    cls: TONE.fault,
    icon: '?',
    help: 'The guard state could not be read. This says nothing about whether guard is watching.',
  },
}

export default function MarinaGuard() {
  const [state, setState] = useState<State>({ kind: 'loading' })
  const isAdmin = useAuthStore((s) => s.role) === 'admin'
  const [cameras, setCameras] = useState<GuardCamera[] | null>(null)

  const load = useCallback(async () => {
    try {
      const core = await getMarinaCore()
      setState({ kind: 'ready', core, at: new Date() })
    } catch (e) {
      setState((prev) => ({
        kind: 'error',
        message: describeError(e),
        stale: prev.kind === 'ready' ? prev.core : prev.kind === 'error' ? prev.stale : null,
        at: prev.kind === 'ready' ? prev.at : prev.kind === 'error' ? prev.at : null,
      }))
      return
    }
    if (isAdmin) {
      try {
        setCameras((await getGuardStatus()).cameras)
      } catch {
        setCameras(null)
      }
    }
  }, [isAdmin])

  useEffect(() => {
    load()
    const t = setInterval(load, 15_000)
    return () => clearInterval(t)
  }, [load])

  if (state.kind === 'loading') {
    return <div className="p-4 text-sm text-gray-400" role="status">Loading guard…</div>
  }

  const failed = state.kind === 'error'
  const core = state.kind === 'ready' ? state.core : state.stale

  return (
    <div className="p-3 sm:p-4 max-w-3xl" data-testid="marina-guard">
      <Back />
      <h1 className="text-lg font-semibold text-gray-100 mt-2 mb-1">Guard</h1>
      <p className="text-xs text-gray-400 mb-3">
        One camera per pedestal. It watches the whole pedestal, not a single berth.
      </p>

      {failed && (
        <div className="mb-3" data-testid="guard-error">
          <p className={`text-xs border ${TONE.notice} rounded px-2 py-1.5`}>
            {state.message} Guard is shown as not measured until the server answers again.
          </p>
          <button
            type="button"
            onClick={load}
            className="mt-2 text-sm px-3 py-1.5 rounded border border-gray-600 text-gray-200 hover:bg-gray-700/60 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-400"
          >
            Try again
          </button>
        </div>
      )}

      {failed && !core && (
        <p className="text-sm text-gray-200" data-testid="guard-sentence">Not measured</p>
      )}

      {core && (
        <div className="flex flex-col gap-3">
          {core.pedestals.map((p) => (
            <PedestalGuard
              key={p.pedestal_id}
              pedestal={p}
              failed={failed}
              lastAt={state.at}
              camera={cameras?.find((c) => c.pedestal_id === p.pedestal_id) ?? null}
              isAdmin={isAdmin}
              onChanged={load}
            />
          ))}
        </div>
      )}
    </div>
  )
}

function PedestalGuard({ pedestal: p, failed, lastAt, camera, isAdmin, onChanged }: {
  pedestal: MarinaPedestal
  failed: boolean
  lastAt: Date | null
  camera: GuardCamera | null
  isAdmin: boolean
  onChanged: () => void
}) {
  const code: GuardBlock['state'] = failed ? 'not_measured' : p.guard.state
  const g = GUARD_STYLE[code] ?? GUARD_STYLE.not_measured
  const budget = p.guard.auto_resumes
  return (
    <section
      className="border border-gray-700 rounded bg-gray-900/40 px-3 py-3"
      data-testid={`guard-pedestal-${p.pedestal_id}`}
    >
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <h2 className="text-sm font-semibold text-gray-100">
          {p.dock ? `Dock ${p.dock}` : 'Pedestal'}
          {p.cabinet_id && (
            <span className="ml-2 text-xs font-normal text-gray-500 font-mono">{p.cabinet_id}</span>
          )}
        </h2>
        <span
          className={`text-xs px-2 py-0.5 rounded border font-medium whitespace-nowrap ml-auto ${g.cls}`}
          data-testid="guard-sentence"
        >
          <span aria-hidden="true" className="mr-1">{g.icon}</span>
          {failed ? 'Not measured' : p.guard.sentence}
        </span>
      </div>

      {failed && lastAt && (
        <p className="text-xs text-gray-400 mt-1" data-testid="guard-last-seen">
          last seen {hhmm(lastAt)}: {p.guard.sentence}
        </p>
      )}

      <p className="text-xs text-gray-400 mt-2">{g.help}</p>

      {!failed && (code === 'on' || code === 'paused') && (
        <p className="text-xs text-gray-400 mt-1" data-testid="guard-resumes">
          {budget
            ? `Automatic resumes left today: ${Math.max(0, budget.max - budget.used)} of ${budget.max}`
            : 'Automatic resumes left: not measured'}
        </p>
      )}

      {!failed && isAdmin && camera && <GuardButton camera={camera} onDone={onChanged} />}

      <p className="text-xs text-gray-500 mt-2">
        Guard covers every berth on this pedestal, so anything it sees may come from any of them.
      </p>

      {!failed && isAdmin && camera && <EventList cameraId={camera.camera_id} />}
    </section>
  )
}

function Back() {
  return (
    <Link
      to="/marina"
      className="text-sm text-blue-300 hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-400"
    >
      ‹ Back to marina
    </Link>
  )
}
