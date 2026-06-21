import { useEffect, useState } from 'react'
import { useStore } from '../../store'
import {
  listNfcTags, provisionNfcTag, provisionNfcTagsBulk, removeNfcTag,
  type NfcTag,
} from '../../api/nfc'

const SOCKETS = ['Q1', 'Q2', 'Q3', 'Q4'] as const

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

export default function NfcProvisioningTable({ cabinetId, pedestalId, isAdmin, onFeedback }: Props) {
  const computed = useStore((s) => s.socketComputedStates)
  const [tags, setTags] = useState<Record<string, NfcTag | undefined>>({})
  const [inputs, setInputs] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState<string | null>(null)

  const reload = async () => {
    try {
      const list = await listNfcTags(cabinetId)
      const bySocket: Record<string, NfcTag> = {}
      for (const t of list) bySocket[t.socket_id] = t
      setTags(bySocket)
      setInputs((prev) => {
        const next = { ...prev }
        for (const s of SOCKETS) if (!(s in next)) next[s] = bySocket[s]?.nfc_tag_id ?? ''
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

  const liveStatus = (socket: string): string =>
    computed[`${pedestalId}-${socket.replace('Q', '')}`] ?? 'idle'

  const provisionOne = async (socket: string) => {
    const val = (inputs[socket] ?? '').trim()
    if (!val) return
    setBusy(socket)
    try {
      await provisionNfcTag(cabinetId, socket, val)
      onFeedback(`nfc-prov-${socket}`, 'success', `${socket}: NFC tag saved`)
      await reload()
    } catch (e: any) {
      onFeedback(`nfc-prov-${socket}`, 'error', e?.response?.data?.detail ?? 'Provisioning failed')
    } finally {
      setBusy(null)
    }
  }

  const removeOne = async (socket: string) => {
    if (!window.confirm(`Remove the NFC tag mapping for ${socket}?`)) return
    setBusy(socket)
    try {
      await removeNfcTag(cabinetId, socket)
      setInputs((p) => ({ ...p, [socket]: '' }))
      onFeedback(`nfc-rm-${socket}`, 'success', `${socket}: NFC tag removed`)
      await reload()
    } catch (e: any) {
      onFeedback(`nfc-rm-${socket}`, 'error', e?.response?.data?.detail ?? 'Remove failed')
    } finally {
      setBusy(null)
    }
  }

  const saveAll = async () => {
    const items = SOCKETS
      .map((s) => ({ socket_id: s, nfc_tag_id: (inputs[s] ?? '').trim() }))
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

  return (
    <div className="space-y-3">
      <p className="text-xs text-gray-500">
        Enter the NFC tag ID physically placed next to each socket. One tag per socket;
        a tag already assigned elsewhere is rejected.
      </p>
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-xs text-gray-500 border-b border-gray-700">
            <th className="py-1.5 pr-2">Socket</th>
            <th className="py-1.5 pr-2">Status</th>
            <th className="py-1.5 pr-2">NFC tag ID</th>
            {isAdmin && <th className="py-1.5 text-right">Actions</th>}
          </tr>
        </thead>
        <tbody>
          {SOCKETS.map((s) => {
            const st = liveStatus(s)
            return (
              <tr key={s} className="border-b border-gray-800">
                <td className="py-2 pr-2 font-medium text-gray-100">{s}</td>
                <td className="py-2 pr-2">
                  <span className={`text-[11px] px-1.5 py-0.5 rounded border ${STATUS_STYLE[st] ?? STATUS_STYLE.idle}`}>
                    {st}
                  </span>
                </td>
                <td className="py-2 pr-2">
                  <input
                    type="text"
                    value={inputs[s] ?? ''}
                    onChange={(e) => setInputs((p) => ({ ...p, [s]: e.target.value }))}
                    disabled={!isAdmin}
                    placeholder="e.g. 04:A2:3B:…"
                    className="w-full bg-gray-900 border border-gray-700 rounded px-2 py-1 text-gray-200 text-xs font-mono disabled:opacity-60"
                  />
                </td>
                {isAdmin && (
                  <td className="py-2 text-right whitespace-nowrap">
                    <button
                      onClick={() => provisionOne(s)}
                      disabled={busy !== null}
                      className="text-xs px-2 py-1 rounded border border-blue-700/50 bg-blue-900/40 text-blue-200 hover:bg-blue-800/60 disabled:opacity-40"
                    >
                      {busy === s ? 'Saving…' : 'Provision'}
                    </button>
                    {tags[s] && (
                      <button
                        onClick={() => removeOne(s)}
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
          })}
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
        {SOCKETS.map((s) => (
          <div key={s} className="flex justify-between">
            <span>{s}</span>
            <span className="font-mono text-gray-300">{tags[s]?.nfc_tag_id ?? '—'}</span>
          </div>
        ))}
      </div>
    </div>
  )
}
