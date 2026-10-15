import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import {
  getBerthAssignments, getMarinaCore, putBerthAssignments,
  type MarinaPedestal,
} from '../../api/marina'
import { listCabinetOutlets, type CabinetOutlet } from '../../api/nfc'
import { SetupPhotos } from '../../components/marina/SetupPhotos'
import { SetupSockets, type RowDraft } from '../../components/marina/SetupSockets'
import { TONE } from '../../components/marina/Status'

/**
 * Control panel — 3 steps, admin, re-runnable.
 *
 * Step 2 captures WHICH SOCKET SERVES WHICH BERTH, and that is the whole reason the wizard
 * exists: without it the L1 row cannot render power at all. The wizard is the right place
 * because it is the one moment someone is physically at the cabinet and can see which outlet
 * serves which boat.
 *
 * THERE IS NO WATER COLUMN. Water serves a maximum of two users at a time via two valves that
 * are not piped to specific berths, so there is nothing to assign — a customer walks to
 * whichever is free and scans it. A water dropdown here would ask for information that does
 * not exist and record a relationship the plumbing does not have.
 *
 * SMART MODE DOES NOT APPEAR. The marina must not be able to switch it, and the endpoint
 * refuses the role regardless of what renders — enforcement is in the backend, never by
 * hiding a control.
 *
 * §9 (block 4, 2026-10-15): step 2 is components/marina/SetupSockets.tsx, step 3's per-berth
 * photos components/marina/SetupPhotos.tsx.
 */

type Step = 1 | 2 | 3

export default function MarinaSetup() {
  const { pedestalId } = useParams<{ pedestalId: string }>()
  const pid = Number(pedestalId)

  const [step, setStep] = useState<Step>(1)
  const [pedestal, setPedestal] = useState<MarinaPedestal | null>(null)
  const [outlets, setOutlets] = useState<CabinetOutlet[]>([])
  const [reported, setReported] = useState<boolean | null>(null)
  const [rows, setRows] = useState<RowDraft[]>([])
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    setError(null)
    try {
      const core = await getMarinaCore()
      const p = core.pedestals.find((x) => x.pedestal_id === pid) ?? null
      setPedestal(p)
      if (!p) {
        setError('That pedestal no longer exists.')
        return
      }

      const assigned = await getBerthAssignments(pid)
      const byBerth = new Map(assigned.assignments.map((a) => [a.berth_id, a.socket_id]))
      setRows(
        p.berths.map((b) => ({
          berth_id: b.berth_id,
          berth_number: b.berth_number,
          socket_id: byBerth.get(b.berth_id) ?? null,
        })),
      )

      if (p.cabinet_id) {
        const cab = await listCabinetOutlets(p.cabinet_id)
        setOutlets(cab.outlets.filter((o) => o.outlet_type === 'socket'))
        setReported(cab.reported)
      }
    } catch (e) {
      const err = e as { response?: { status?: number; data?: { detail?: string } } }
      setError(err?.response?.data?.detail ?? 'Cannot reach the server.')
    }
  }, [pid])

  useEffect(() => { load() }, [load])

  const duplicate = useMemo(() => {
    const seen = new Set<number>()
    for (const r of rows) {
      if (r.socket_id == null) continue
      if (seen.has(r.socket_id)) return r.socket_id
      seen.add(r.socket_id)
    }
    return null
  }, [rows])

  const save = async () => {
    setBusy(true)
    setError(null)
    setSaved(null)
    try {
      await putBerthAssignments(
        pid,
        rows.map((r) => ({ berth_id: r.berth_id, socket_id: r.socket_id })),
      )
      setSaved('Saved. The marina screen will show these berths on their sockets.')
    } catch (e) {
      const err = e as { response?: { status?: number; data?: { detail?: string } } }
      // The server's message, not a local paraphrase. It knows exactly which rule was broken
      // and says so in a sentence; restating it here would drift from the real rule.
      setError(err?.response?.data?.detail ?? 'Could not save. Please try again.')
    } finally {
      setBusy(false)
    }
  }

  if (!pedestal && !error) {
    return <div className="p-4 text-sm text-gray-400" role="status">Loading the pedestal…</div>
  }

  return (
    <div className="p-3 sm:p-4 max-w-2xl" data-testid="marina-setup">
      <Link
        to="/marina"
        className="text-sm text-blue-300 hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-400"
      >
        ‹ Back to marina
      </Link>

      <h1 className="text-lg font-semibold text-gray-100 mt-2 mb-1">Set up this pedestal</h1>
      <p className="text-xs text-gray-400 mb-3">
        Step {step} of 3
        {pedestal?.cabinet_id && (
          <span className="ml-2 font-mono text-gray-500">{pedestal.cabinet_id}</span>
        )}
      </p>

      {error && (
        <p
          className={`text-sm border ${TONE.notice} rounded px-2 py-1.5 mb-3`}
          data-testid="setup-error"
        >
          {error}
        </p>
      )}
      {saved && (
        <p
          className={`text-sm border ${TONE.done} rounded px-2 py-1.5 mb-3`}
          data-testid="setup-saved"
        >
          {saved}
        </p>
      )}

      {/* ── Step 1 ─────────────────────────────────────────────────────────── */}
      {step === 1 && (
        <section className="border border-gray-700 rounded bg-gray-900/40 p-3">
          <h2 className="text-sm font-semibold text-gray-100 mb-2">
            Which dock does this pedestal serve?
          </h2>
          <dl className="text-sm">
            <div className="flex gap-3 py-1 flex-wrap">
              <dt className="text-gray-400 w-24">Dock</dt>
              <dd className="text-gray-100">{pedestal?.dock ?? 'Not set'}</dd>
            </div>
            <div className="flex gap-3 py-1 flex-wrap">
              <dt className="text-gray-400 w-24">Pedestal</dt>
              <dd className="font-mono text-gray-300">{pedestal?.cabinet_id ?? '—'}</dd>
            </div>
          </dl>
          <p className="text-xs text-gray-500 mt-2">
            The pedestal name comes from the cabinet itself and cannot be changed here.
          </p>
        </section>
      )}

      {/* ── Step 2 — the one that matters ──────────────────────────────────── */}
      {step === 2 && (
        <SetupSockets rows={rows} outlets={outlets} reported={reported} duplicate={duplicate}
          onPick={(berthId, socketId) => {
            setRows((prev) =>
              prev.map((x) => (x.berth_id === berthId ? { ...x, socket_id: socketId } : x)))
            setSaved(null)
          }} />
      )}

      {/* ── Step 3 ─────────────────────────────────────────────────────────── */}
      {step === 3 && (
        <section className="border border-gray-700 rounded bg-gray-900/40 p-3">
          <h2 className="text-sm font-semibold text-gray-100 mb-1">
            Per berth: a photo of the boat that belongs there, then save
          </h2>
          <p className="text-xs text-gray-400 mb-2">
            A boat at a berth with a photo is checked against it; a berth without one is not.
            Photos are stored as soon as they are added.
          </p>
          <ul className="divide-y divide-gray-800">
            {rows.map((r) => (
              <SetupPhotos key={r.berth_id} berthId={r.berth_id}
                label={`Berth ${r.berth_number ?? r.berth_id}`}
                socket={r.socket_id == null ? 'No socket' : `Q${r.socket_id}`} />
            ))}
          </ul>
          <p className="text-xs text-gray-500 mt-3">
            Save stores the sockets from step 2. It replaces the whole mapping for this
            pedestal, and records who changed it.
          </p>
          <button
            type="button"
            onClick={save}
            disabled={busy || duplicate != null}
            className="mt-3 text-sm px-3 py-1.5 rounded bg-blue-600 hover:bg-blue-500 text-white font-medium disabled:opacity-40 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-400"
          >
            {busy ? 'Saving…' : 'Save'}
          </button>
        </section>
      )}

      <div className="flex gap-2 mt-4">
        <button
          type="button"
          onClick={() => setStep((s) => (s > 1 ? ((s - 1) as Step) : s))}
          disabled={step === 1}
          className="text-sm px-3 py-1.5 rounded border border-gray-600 text-gray-200 hover:bg-gray-700/60 disabled:opacity-40 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-400"
        >
          Back
        </button>
        <button
          type="button"
          onClick={() => setStep((s) => (s < 3 ? ((s + 1) as Step) : s))}
          disabled={step === 3}
          className="text-sm px-3 py-1.5 rounded border border-blue-700/60 bg-blue-900/40 text-blue-100 hover:bg-blue-800/60 disabled:opacity-40 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-400"
        >
          Next
        </button>
      </div>
    </div>
  )
}
