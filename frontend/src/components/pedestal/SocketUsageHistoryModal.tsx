import { useEffect, useState } from 'react'
import {
  getUsageHistory,
  downloadUsageReport,
  deleteUsageReport,
  type UsageRow,
  type UsageResource,
} from '../../api/usage'

// v3.31 — per-socket / per-valve usage history + monthly plain-text report
// download. Read-only for everyone with access; report DELETION is admin-only.

interface Props {
  pedestalId: number
  socketId: number
  resource: UsageResource
  /** Display label, e.g. "Q1" or "V1". */
  label: string
  isAdmin: boolean
  onClose: () => void
}

/** Last 12 months as "YYYY-MM", newest first (browser-local clock). */
function recentMonths(): string[] {
  const out: string[] = []
  const d = new Date()
  for (let i = 0; i < 12; i++) {
    const y = d.getFullYear()
    const m = String(d.getMonth() + 1).padStart(2, '0')
    out.push(`${y}-${m}`)
    d.setMonth(d.getMonth() - 1)
  }
  return out
}

export default function SocketUsageHistoryModal({
  pedestalId, socketId, resource, label, isAdmin, onClose,
}: Props) {
  const months = recentMonths()
  const [month, setMonth] = useState(months[0])
  const [rows, setRows] = useState<UsageRow[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState<'download' | 'delete' | null>(null)
  const [note, setNote] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setRows(null); setError(null)
    getUsageHistory(pedestalId, resource, socketId, month)
      .then((r) => { if (!cancelled) setRows(r) })
      .catch((e) => { if (!cancelled) setError(e?.response?.data?.detail ?? 'Failed to load history') })
    return () => { cancelled = true }
  }, [pedestalId, socketId, resource, month])

  const isWater = resource === 'water'

  const handleDownload = async () => {
    setBusy('download'); setNote(null)
    try {
      await downloadUsageReport(pedestalId, month)
      setNote(`Downloaded report for ${month}`)
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setNote(detail ?? 'Download failed')
    } finally {
      setBusy(null)
    }
  }

  const handleDelete = async () => {
    if (!window.confirm(`Delete the ${month} report for pedestal ${pedestalId}? This cannot be undone.`)) return
    setBusy('delete'); setNote(null)
    try {
      await deleteUsageReport(pedestalId, month)
      setNote(`Deleted report for ${month}`)
    } catch (e: unknown) {
      const status = (e as { response?: { status?: number } })?.response?.status
      setNote(status === 404 ? 'No stored report for that month yet' : 'Delete failed')
    } finally {
      setBusy(null)
    }
  }

  const fmt = (iso: string | null) => (iso ? new Date(iso).toLocaleString() : '—')

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" role="dialog" aria-modal="true">
      <div className="bg-gray-900 border border-gray-700 rounded-lg p-4 w-full max-w-2xl mx-4 max-h-[85vh] flex flex-col">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-semibold text-gray-100">
            Usage history — {label} ({isWater ? 'water' : 'electricity'})
          </h3>
          <button
            type="button"
            onClick={onClose}
            className="text-xs text-gray-400 hover:text-gray-100 px-2 py-1 rounded hover:bg-gray-800"
            aria-label="Close"
          >
            ✕
          </button>
        </div>

        <div className="flex items-center gap-2 mb-3 flex-wrap">
          <label className="text-xs text-gray-400">Month</label>
          <select
            value={month}
            onChange={(e) => setMonth(e.target.value)}
            className="bg-gray-800 border border-gray-600 rounded px-2 py-1 text-xs text-gray-200"
          >
            {months.map((m) => <option key={m} value={m}>{m}</option>)}
          </select>
          <button
            type="button"
            onClick={handleDownload}
            disabled={busy !== null}
            className="text-xs px-2 py-1 rounded border border-blue-700/50 bg-blue-900/40 text-blue-200 hover:bg-blue-800/50 disabled:opacity-50"
          >
            {busy === 'download' ? 'Downloading…' : '⬇ Download report (.txt)'}
          </button>
          {isAdmin && (
            <button
              type="button"
              onClick={handleDelete}
              disabled={busy !== null}
              className="text-xs px-2 py-1 rounded border border-red-700/50 bg-red-900/40 text-red-200 hover:bg-red-800/50 disabled:opacity-50"
              title="Delete the stored monthly report file (admin only)"
            >
              {busy === 'delete' ? 'Deleting…' : '🗑 Delete report'}
            </button>
          )}
        </div>

        {note && <p className="text-xs text-amber-300 mb-2">{note}</p>}

        <div className="overflow-y-auto flex-1">
          {error && <p className="text-xs text-red-300">{error}</p>}
          {!error && rows == null && <p className="text-xs text-gray-400">Loading…</p>}
          {!error && rows != null && rows.length === 0 && (
            <p className="text-xs text-gray-500">No completed sessions for {label} in {month}.</p>
          )}
          {!error && rows != null && rows.length > 0 && (
            <table className="w-full text-xs">
              <thead>
                <tr className="text-gray-500 text-left border-b border-gray-700/60">
                  <th className="py-1 pr-2">Started</th>
                  <th className="py-1 pr-2">Ended</th>
                  <th className="py-1 pr-2 text-right">{isWater ? 'Liters' : 'kWh'}</th>
                  <th className="py-1 pl-2">Customer / NFC</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.session_id} className="border-b border-gray-800/60">
                    <td className="py-1 pr-2 font-mono text-gray-300">{fmt(r.started_at)}</td>
                    <td className="py-1 pr-2 font-mono text-gray-400">{fmt(r.ended_at)}</td>
                    <td className="py-1 pr-2 text-right font-mono text-gray-200">
                      {isWater
                        ? (r.water_liters != null ? r.water_liters.toFixed(1) : '—')
                        : (r.energy_kwh != null ? r.energy_kwh.toFixed(3) : '—')}
                    </td>
                    <td className="py-1 pl-2 text-gray-300">
                      {r.customer_name
                        ? <>{r.customer_name}{r.customer_id != null ? ` (#${r.customer_id})` : ''}</>
                        : <span className="text-gray-600">—</span>}
                      {r.nfc_user_id && <span className="text-purple-300"> · nfc:{r.nfc_user_id}</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  )
}
