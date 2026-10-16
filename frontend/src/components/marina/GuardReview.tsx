import { useCallback, useEffect, useState } from 'react'
import { TONE } from './Status'
import {
  armGuard, fetchGuardVideo, getGuardEvents, labelGuardEvent, switchOffGuard,
  type GuardCamera, type GuardListRow,
} from '../../api/guard'

/**
 * The admin half of /marina/guard (spec §5.5.2, §5.5.4, §5.5.5): Arm / Switch off, the event
 * list, playback and the labels. Rendered only for admin by MarinaGuard; the API refuses every
 * one of these calls to any other role as well.
 */

const when = (iso: string) => {
  const d = new Date(iso)
  const t = d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })
  return `${d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })} ${t}`
}

/** Arm when off, Switch off when on or paused; nothing for "no guard" or "not answering" —
 *  there is nothing a tap could do (Rule 6: absent, not disabled). "Sent" after a tap: the
 *  sentence follows the worker's confirmation, never the tap. */
export function GuardButton({ camera, onDone }: { camera: GuardCamera; onDone: () => void }) {
  const [phase, setPhase] = useState<'idle' | 'sending' | 'sent' | 'refused'>('idle')
  const [refusal, setRefusal] = useState<string | null>(null)
  const action = camera.sentence_code === 'off' ? 'arm'
    : camera.sentence_code === 'on' || camera.sentence_code === 'paused' ? 'off' : null
  if (!action) return null
  const tap = async () => {
    setPhase('sending')
    try {
      await (action === 'arm' ? armGuard(camera.camera_id) : switchOffGuard(camera.camera_id))
      setPhase('sent')
      onDone()
    } catch (e) {
      const err = e as { response?: { data?: { detail?: string } } }
      setRefusal(typeof err.response?.data?.detail === 'string'
        ? err.response.data.detail
        : 'No answer — it is not known whether guard was switched.')
      setPhase('refused')
    }
  }
  return (
    <div className="mt-2 flex items-center gap-2">
      <button
        type="button"
        onClick={tap}
        disabled={phase === 'sending'}
        data-testid="guard-button"
        className="text-sm px-3 py-1.5 rounded border border-gray-600 text-gray-100 hover:bg-gray-700/60 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-400"
      >
        {phase === 'sent' ? 'Sent' : action === 'arm' ? 'Arm' : 'Switch off'}
      </button>
      {phase === 'refused' && refusal && (
        <span className={`text-xs ${TONE.noticeText}`}>{refusal}</span>
      )}
    </div>
  )
}

const PAGE = 50

/** Admin only (§5.5.5): 14 days as retention keeps them, newest first, 50 per page (§5.5.4). */
export function EventList({ cameraId }: { cameraId: number }) {
  const [offset, setOffset] = useState(0)
  const [data, setData] = useState<{ total: number; events: GuardListRow[] } | 'failed' | null>(null)

  const load = useCallback(async () => {
    try {
      setData(await getGuardEvents(cameraId, offset, PAGE))
    } catch {
      setData('failed')
    }
  }, [cameraId, offset])

  useEffect(() => { load() }, [load])

  return (
    <div className="mt-3 border-t border-gray-800 pt-2" data-testid="guard-events">
      <h3 className="text-xs font-semibold text-gray-300 mb-1">Recent</h3>
      {data === null && <p className="text-xs text-gray-400">Loading…</p>}
      {data === 'failed' && <p className="text-xs text-gray-200">Not measured</p>}
      {data && data !== 'failed' && (
        <>
          {data.events.length === 0 && (
            <p className="text-xs text-gray-400">Nothing recorded in the last 14 days.</p>
          )}
          <ul className="flex flex-col gap-2">
            {data.events.map((ev) => (
              <EventRow key={`${ev.kind}-${ev.id}`} ev={ev} onLabelled={load} />
            ))}
          </ul>
          <div className="flex gap-2 mt-2">
            {offset > 0 && (
              <button type="button" className="text-xs text-blue-300 hover:underline"
                      onClick={() => setOffset(Math.max(0, offset - PAGE))}>Newer</button>
            )}
            {offset + PAGE < data.total && (
              <button type="button" className="text-xs text-blue-300 hover:underline"
                      onClick={() => setOffset(offset + PAGE)}>Older</button>
            )}
          </div>
        </>
      )}
    </div>
  )
}

function EventRow({ ev, onLabelled }: { ev: GuardListRow; onLabelled: () => void }) {
  if (ev.kind !== 'person') {
    return (
      <li className="text-xs text-gray-300" data-testid="guard-state-row">
        {when(ev.at_utc)}{'   '}
        {ev.kind === 'paused_cpu' ? 'Guard paused — processor overloaded'
          : ev.kind === 'unknown_state' ? `Guard reported a state we cannot read: ${ev.reason}` : 'Guard resumed on its own'}
      </li>
    )
  }
  const status = ev.label === 'correct' ? 'Person seen — marked correct'
    : ev.label === 'false_alarm' ? 'Person seen — marked false alarm'
      : 'Person seen — needs checking'
  return (
    <li className="text-xs text-gray-200" data-testid="guard-event-row">
      <div>{when(ev.at_utc)}{'   '}{status}</div>
      <Recording ev={ev} />
      <div className="flex gap-2 mt-1">
        {(['correct', 'false_alarm'] as const).map((l) => (
          <button
            key={l}
            type="button"
            onClick={async () => { await labelGuardEvent(ev.id, l); onLabelled() }}
            className="text-xs px-2 py-0.5 rounded border border-gray-600 text-gray-200 hover:bg-gray-700/60"
          >
            {l === 'correct' ? 'Correct' : 'False alarm'}
          </button>
        ))}
      </div>
    </li>
  )
}

function noClipSentence(reason: string | null): string {
  if (reason === 'no_disk') return 'No recording — there was no space to record'
  if (reason === 'assembly_failed') return 'No recording — it could not be assembled'
  return 'No recording'
}

function Recording({ ev }: { ev: Extract<GuardListRow, { kind: 'person' }> }) {
  const [clip, setClip] = useState<{ url: string } | { gone: string } | null>(null)
  if (!ev.has_video) {
    return <p className="text-xs text-gray-400 mt-1">{noClipSentence(ev.video_skip_reason)}</p>
  }
  if (clip && 'url' in clip) {
    // The clip is the camera's own codec, stream-copied (§5.5.4). A browser may not play H.265,
    // so the file is always offered as a download as well; §13.6c F.7 reads the real codec.
    return (
      <div className="mt-1">
        <video src={clip.url} controls className="max-w-full" data-testid="guard-video" />
        <a href={clip.url} download={`guard-event-${ev.id}.mp4`}
           className="text-xs text-blue-300 hover:underline">Download the recording</a>
      </div>
    )
  }
  if (clip && 'gone' in clip) {
    return <p className="text-xs text-gray-400 mt-1">{clip.gone}</p>
  }
  return (
    <button
      type="button"
      className="mt-1 text-xs px-2 py-0.5 rounded border border-gray-600 text-gray-100 hover:bg-gray-700/60"
      onClick={async () => {
        const r = await fetchGuardVideo(ev.id)
        if (r.ok) setClip({ url: r.url })
        else if (r.status === 410) setClip({ gone: 'Recording deleted after 14 days' })
        else setClip({ gone: noClipSentence(r.reason) })
      }}
    >
      ▶ Play recording
    </button>
  )
}
