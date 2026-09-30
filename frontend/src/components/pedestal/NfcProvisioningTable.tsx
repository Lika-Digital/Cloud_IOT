import { useEffect, useState } from 'react'
import { useStore } from '../../store'
import {
  listCabinetOutlets, listNfcTags, provisionNfcTag, provisionNfcTagsBulk, removeNfcTag,
  type CabinetOutlet, type NfcTag,
} from '../../api/nfc'

interface Props {
  cabinetId: string
  pedestalId: number
  isAdmin: boolean
  onFeedback: (key: string, type: 'success' | 'error', text: string) => void
}

const STATUS_STYLE: Record<string, string> = {
  active: 'bg-green-900/40 text-green-300 border-green-700/50',
  pending: 'bg-yellow-900/40 text-yellow-300 border-yellow-700/50',
  fault: 'bg-red-900/40 text-red-300 border-red-700/50',
  idle: 'bg-gray-800 text-gray-400 border-gray-700',
}

// v3.43 — the outlet list is no longer a constant in this file.
//
// It was `['Q1','Q2','Q3','Q4']`, which was wrong twice: it omitted the two water outlets
// entirely — a cabinet carries SIX NFC tags, one per outlet — and it asserted four identical
// sockets when `opta/config/hardware` says Q1 is three-phase at 32 A while Q3/Q4 are 16 A.
//
// The cabinet enumerates itself, so the table asks it. `/api/nfc/outlets/{cabinet}` returns
// what the cabinet reported, or the canonical six with `reported: false` when it has never
// published its hardware config — a distinction this component surfaces rather than hides.

/** What the outlet's rating reads as, for the row. Empty when the cabinet has not said. */
function ratingLabel(o: CabinetOutlet): string {
  if (o.outlet_type === 'valve') {
    return o.rated_liters_per_min != null ? `${o.rated_liters_per_min} L/min` : ''
  }
  const parts: string[] = []
  if (o.rated_amps != null) parts.push(`${o.rated_amps} A`)
  // Only worth saying when it is not the single-phase default — "1-phase" on three rows and
  // "3-phase" on one is noise; the difference is what staff need to see.
  if (o.phases != null && o.phases > 1) parts.push(`${o.phases}-phase`)
  return parts.join(' · ')
}

export default function NfcProvisioningTable({ cabinetId, pedestalId, isAdmin, onFeedback }: Props) {
  const computed = useStore((s) => s.socketComputedStates)
  const [outlets, setOutlets] = useState<CabinetOutlet[]>([])
  const [reported, setReported] = useState<boolean | null>(null)
  const [tags, setTags] = useState<Record<string, NfcTag | undefined>>({})
  const [inputs, setInputs] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState<string | null>(null)

  const reload = async () => {
    try {
      const [cab, list] = await Promise.all([
        listCabinetOutlets(cabinetId),
        listNfcTags(cabinetId),
      ])
      setOutlets(cab.outlets)
      setReported(cab.reported)
      const byOutlet: Record<string, NfcTag> = {}
      for (const t of list) byOutlet[t.socket_id] = t
      setTags(byOutlet)
      setInputs((prev) => {
        const next = { ...prev }
        for (const o of cab.outlets) {
          if (!(o.outlet_name in next)) next[o.outlet_name] = byOutlet[o.outlet_name]?.nfc_tag_id ?? ''
        }
        return next
      })
    } catch {
      onFeedback(`nfc-load-${cabinetId}`, 'error', 'Failed to load NFC tags')
    }
  }

  useEffect(() => {
    reload()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cabinetId])

  /** Live state for an electricity socket. Valves have none — see the render below. */
  const liveStatus = (outletName: string): string =>
    computed[`${pedestalId}-${outletName.replace('Q', '')}`] ?? 'idle'

  const provisionOne = async (o: CabinetOutlet) => {
    const name = o.outlet_name
    const val = (inputs[name] ?? '').trim()
    if (!val) return
    setBusy(name)
    try {
      await provisionNfcTag(cabinetId, name, val, o.outlet_type)
      onFeedback(`nfc-prov-${name}`, 'success', `${name}: NFC tag saved`)
      await reload()
    } catch (e: any) {
      onFeedback(`nfc-prov-${name}`, 'error', e?.response?.data?.detail ?? 'Provisioning failed')
    } finally {
      setBusy(null)
    }
  }

  const removeOne = async (o: CabinetOutlet) => {
    const name = o.outlet_name
    const what = o.outlet_type === 'valve' ? 'water outlet' : 'socket'
    if (!window.confirm(`Remove the NFC tag mapping for ${what} ${name}?`)) return
    setBusy(name)
    try {
      await removeNfcTag(cabinetId, name)
      setInputs((p) => ({ ...p, [name]: '' }))
      onFeedback(`nfc-rm-${name}`, 'success', `${name}: NFC tag removed`)
      await reload()
    } catch (e: any) {
      onFeedback(`nfc-rm-${name}`, 'error', e?.response?.data?.detail ?? 'Remove failed')
    } finally {
      setBusy(null)
    }
  }

  const saveAll = async () => {
    // Each item carries its own outlet_type, so the server can refuse a mismatch rather than
    // guess. A valve row saved as a socket would point a water tag at electricity.
    const items = outlets
      .map((o) => ({
        socket_id: o.outlet_name,
        nfc_tag_id: (inputs[o.outlet_name] ?? '').trim(),
        outlet_type: o.outlet_type,
      }))
      .filter((it) => it.nfc_tag_id && it.nfc_tag_id !== tags[it.socket_id]?.nfc_tag_id)
    if (items.length === 0) {
      onFeedback(`nfc-saveall-${cabinetId}`, 'success', 'Nothing to save')
      return
    }
    setBusy('all')
    try {
      await provisionNfcTagsBulk(cabinetId, items)
      onFeedback(`nfc-saveall-${cabinetId}`, 'success', `Saved ${items.length} NFC tag(s)`)
      await reload()
    } catch (e: any) {
      onFeedback(`nfc-saveall-${cabinetId}`, 'error', e?.response?.data?.detail ?? 'Save All failed')
    } finally {
      setBusy(null)
    }
  }

  const sockets = outlets.filter((o) => o.outlet_type === 'socket')
  const valves = outlets.filter((o) => o.outlet_type === 'valve')

  const renderRow = (o: CabinetOutlet) => {
    const name = o.outlet_name
    const isValve = o.outlet_type === 'valve'
    const rating = ratingLabel(o)
    return (
      <tr key={name} className="border-b border-gray-800">
        <td className="py-2 pr-2 font-medium text-gray-100">
          {name}
          {rating && <span className="ml-1.5 text-[10px] font-normal text-gray-500">{rating}</span>}
        </td>
        <td className="py-2 pr-2">
          {isValve ? (
            /* The firmware publishes no per-valve state equivalent to a socket's, so there is
               nothing to show. A dash says that; borrowing the socket badge would show a
               green "idle" that no signal supports. */
            <span
              className="text-[11px] text-gray-500"
              title="The cabinet does not report a state for water outlets"
            >
              —
            </span>
          ) : (
            <span className={`text-[11px] px-1.5 py-0.5 rounded border ${STATUS_STYLE[liveStatus(name)] ?? STATUS_STYLE.idle}`}>
              {liveStatus(name)}
            </span>
          )}
        </td>
        <td className="py-2 pr-2">
          <input
            type="text"
            value={inputs[name] ?? ''}
            onChange={(e) => setInputs((p) => ({ ...p, [name]: e.target.value }))}
            disabled={!isAdmin}
            placeholder="e.g. 04:A2:3B:…"
            className="w-full bg-gray-900 border border-gray-700 rounded px-2 py-1 text-gray-200 text-xs font-mono disabled:opacity-60"
          />
        </td>
        {isAdmin && (
          <td className="py-2 text-right whitespace-nowrap">
            <button
              onClick={() => provisionOne(o)}
              disabled={busy !== null}
              className="text-xs px-2 py-1 rounded border border-blue-700/50 bg-blue-900/40 text-blue-200 hover:bg-blue-800/60 disabled:opacity-40"
            >
              {busy === name ? 'Saving…' : 'Provision'}
            </button>
            {tags[name] && (
              <button
                onClick={() => removeOne(o)}
                disabled={busy !== null}
                className="ml-1.5 text-xs px-2 py-1 rounded border border-red-700/50 bg-red-900/30 text-red-200 hover:bg-red-800/50 disabled:opacity-40"
              >
                Remove
              </button>
            )}
          </td>
        )}
      </tr>
    )
  }

  const colSpan = isAdmin ? 4 : 3

  return (
    <div className="space-y-3">
      <p className="text-xs text-gray-500">
        Enter the NFC tag ID physically placed next to each outlet — electricity sockets and
        water outlets alike. One tag per outlet; a tag already assigned elsewhere is rejected.
      </p>

      {reported === false && (
        /* Not cosmetic. The fallback list is the canonical six, but an admin looking at six
           rows deserves to know whether the cabinet confirmed them or we assumed them. */
        <p className="text-[11px] text-yellow-300/80 border border-yellow-700/40 bg-yellow-900/20 rounded px-2 py-1.5">
          This cabinet has not reported its hardware configuration. The outlets below are the
          standard set; ratings are unknown until the cabinet publishes
          <span className="font-mono"> opta/config/hardware</span>.
        </p>
      )}

      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-xs text-gray-500 border-b border-gray-700">
            <th className="py-1.5 pr-2">Outlet</th>
            <th className="py-1.5 pr-2">Status</th>
            <th className="py-1.5 pr-2">NFC tag ID</th>
            {isAdmin && <th className="py-1.5 text-right">Actions</th>}
          </tr>
        </thead>
        <tbody>
          {sockets.length > 0 && (
            <tr className="border-b border-gray-800">
              <td colSpan={colSpan} className="pt-2 pb-1 text-[10px] uppercase tracking-wide text-gray-500">
                Electricity
              </td>
            </tr>
          )}
          {sockets.map(renderRow)}
          {valves.length > 0 && (
            <tr className="border-b border-gray-800">
              <td colSpan={colSpan} className="pt-3 pb-1 text-[10px] uppercase tracking-wide text-gray-500">
                Water
              </td>
            </tr>
          )}
          {valves.map(renderRow)}
          {outlets.length === 0 && (
            <tr>
              <td colSpan={colSpan} className="py-3 text-xs text-gray-500">
                No outlets found for this cabinet.
              </td>
            </tr>
          )}
        </tbody>
      </table>

      {isAdmin && (
        <div className="flex justify-end">
          <button
            onClick={saveAll}
            disabled={busy !== null}
            className="text-xs px-3 py-1.5 rounded bg-blue-600 hover:bg-blue-500 text-white font-medium disabled:opacity-40"
          >
            {busy === 'all' ? 'Saving…' : 'Save All'}
          </button>
        </div>
      )}

      {/* Summary */}
      <div className="rounded border border-gray-700 bg-gray-900/40 p-2 text-[11px] text-gray-400 space-y-0.5">
        <p className="font-medium text-gray-300">Configuration</p>
        {outlets.map((o) => (
          <div key={o.outlet_name} className="flex justify-between">
            <span>
              {o.outlet_name}
              <span className="ml-1 text-gray-600">
                {o.outlet_type === 'valve' ? 'water' : 'electricity'}
              </span>
            </span>
            <span className="font-mono text-gray-300">{tags[o.outlet_name]?.nfc_tag_id ?? '—'}</span>
          </div>
        ))}
      </div>
    </div>
  )
}
