import { useCallback, useEffect, useRef, useState } from 'react'
import { useStore } from '../store'
import {
  getBerths, getBerthCalendar, triggerAnalysis,
  getReferenceImages, uploadReferenceImages, deleteReferenceImage, updateBerthConfig,
  type BerthOut, type CalendarEntry,
} from '../api/berths'
import { useAuthStore } from '../store/authStore'

// Status → visual properties
const STATUS_COLOR: Record<string, string> = {
  free: '#22c55e',
  occupied: '#6b7280',
  reserved: '#f59e0b',
}
const STATUS_LABEL: Record<string, string> = {
  free: 'Free',
  occupied: 'Occupied',
  reserved: 'Reserved',
}

export default function BerthOccupancy() {
  const { berthOccupancy, setBerthOccupancy, activeSessions } = useStore()
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)

  // Live-view modal
  const [liveModalBerth, setLiveModalBerth] = useState<BerthOut | null>(null)
  const [noCameraMsg, setNoCameraMsg] = useState<string | null>(null)

  // Calendar modal
  const [calendarBerth, setCalendarBerth] = useState<BerthOut | null>(null)
  const [calendarEntries, setCalendarEntries] = useState<CalendarEntry[]>([])
  const [calendarLoading, setCalendarLoading] = useState(false)

  // Analyze state
  const [analyzingId, setAnalyzingId] = useState<number | null>(null)
  const [analyzeResult, setAnalyzeResult] = useState<{ ok: boolean; text: string } | null>(null)

  // Reference images modal
  const [refModalBerth, setRefModalBerth] = useState<BerthOut | null>(null)

  // Berth config modal
  const [configBerth, setConfigBerth] = useState<BerthOut | null>(null)

  const refresh = useCallback(() =>
    getBerths()
      .then((data) => { setBerthOccupancy(data as any); setLoadError(null) })
      .catch(() => setLoadError('Failed to load berth data.')),
  [setBerthOccupancy])

  useEffect(() => { refresh().finally(() => setLoading(false)) }, [refresh])

  const openCalendar = async (berth: BerthOut) => {
    setCalendarBerth(berth)
    setCalendarLoading(true)
    try {
      setCalendarEntries(await getBerthCalendar(berth.id))
    } catch {
      setCalendarEntries([])
    }
    setCalendarLoading(false)
  }

  const handleLiveView = (berth: BerthOut) => {
    if (!berth.camera_stream_url) {
      setNoCameraMsg('No camera configured for this berth.')
      setTimeout(() => setNoCameraMsg(null), 4000)
      return
    }
    if (!berth.camera_reachable) {
      setNoCameraMsg('Live stream not detected — camera is unreachable.')
      setTimeout(() => setNoCameraMsg(null), 4000)
      return
    }
    setLiveModalBerth(berth)
  }

  const handleAnalyze = async (berth: BerthOut) => {
    if (!berth.camera_stream_url || !berth.camera_reachable) {
      setAnalyzeResult({ ok: false, text: 'Camera not available — configure and connect a camera first.' })
      setTimeout(() => setAnalyzeResult(null), 5000)
      return
    }
    setAnalyzingId(berth.id)
    setAnalyzeResult(null)
    try {
      const res = await triggerAnalysis(berth.id)
      setAnalyzeResult({ ok: res.ok, text: res.detected_status })
      await refresh()
    } catch (err: any) {
      const detail = err?.response?.data?.detail ?? 'Analysis failed'
      setAnalyzeResult({ ok: false, text: `⚠ ${detail}` })
    } finally {
      setAnalyzingId(null)
      setTimeout(() => setAnalyzeResult(null), 6000)
    }
  }

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-bold text-white">Berth Occupancy</h1>
        <p className="text-gray-400 text-sm mt-1">
          On-demand camera analysis — click Analyze to take a live snapshot and detect ship presence.
        </p>
      </div>

      {loadError && (
        <div className="px-4 py-3 rounded-lg bg-red-900/30 border border-red-700/40 text-red-400 text-sm">
          {loadError}
        </div>
      )}

      {noCameraMsg && (
        <div className="px-4 py-3 rounded-lg bg-yellow-900/30 border border-yellow-700/40 text-yellow-400 text-sm">
          📷 {noCameraMsg}
        </div>
      )}

      {analyzeResult && (
        <div className={`text-sm font-semibold px-4 py-2 rounded-lg border w-fit ${
          analyzeResult.ok
            ? 'bg-green-900/30 border-green-700/50 text-green-400'
            : 'bg-red-900/30 border-red-700/50 text-red-400'
        }`}>
          {analyzeResult.text}
        </div>
      )}

      {loading ? (
        <div className="text-gray-500 text-center py-16">Loading berth data…</div>
      ) : (
        <>
          {/* ── Dock SVG visualization ──────────────────────────────────────── */}
          <DockVisualization
            berths={berthOccupancy}
            onBerthClick={(b) => {
              if (b.camera_stream_url) handleLiveView(b as BerthOut)
              else if (b.status === 'reserved') openCalendar(b as BerthOut)
            }}
          />

          {/* ── Active pedestal summary ──────────────────────────────────────── */}
          {(() => {
            const activePedestalIds = new Set(activeSessions.map((s) => s.pedestal_id).filter(Boolean))
            const total = berthOccupancy.length
            const occupied = berthOccupancy.filter((b) => b.status === 'occupied').length
            const transit = berthOccupancy.filter((b) => b.berth_type === 'transit').length
            const yearly = berthOccupancy.filter((b) => b.berth_type === 'yearly').length
            return (
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                <SummaryCard label="Total Berths" value={total} color="text-white" />
                <SummaryCard label="Occupied" value={occupied} color="text-red-400" />
                <SummaryCard label="Active Pedestals" value={activePedestalIds.size} color="text-blue-400" />
                <div className="rounded-lg border border-gray-700 bg-gray-900 px-4 py-3 text-center">
                  <div className="text-xs text-gray-500 mb-1">Type Split</div>
                  <div className="text-sm text-gray-300">
                    <span className="text-cyan-400 font-bold">{transit}</span> transit
                    <span className="mx-1 text-gray-600">/</span>
                    <span className="text-purple-400 font-bold">{yearly}</span> yearly
                  </div>
                </div>
              </div>
            )
          })()}

          {/* ── Berth table ──────────────────────────────────────────────────── */}
          <div className="bg-gray-900 rounded-xl border border-gray-800">
            <div className="px-6 py-4 border-b border-gray-800 flex items-center justify-between">
              <h2 className="text-lg font-semibold text-white">Berth Status Summary</h2>
              {berthOccupancy.some((b) => b.alarm) && (
                <span className="flex items-center gap-2 text-sm font-bold text-red-400 animate-pulse">
                  🚨 {berthOccupancy.filter((b) => b.alarm).length} alarm(s) active
                </span>
              )}
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-gray-500 text-xs uppercase border-b border-gray-800">
                    <th className="px-4 py-3 text-left">Berth</th>
                    <th className="px-4 py-3 text-left">Type</th>
                    <th className="px-4 py-3 text-left">Status</th>
                    <th className="px-4 py-3 text-left">ML State</th>
                    <th className="px-4 py-3 text-left">Match Score</th>
                    <th className="px-4 py-3 text-left">Camera</th>
                    <th className="px-4 py-3 text-left">Analyzed</th>
                    <th className="px-4 py-3 text-left">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {berthOccupancy.map((b) => (
                    <tr
                      key={b.id}
                      className={`border-b border-gray-800 hover:bg-gray-800/40 ${
                        b.alarm ? 'bg-red-950/30' : ''
                      }`}
                    >
                      <td className="px-4 py-3 font-medium text-white">
                        {b.alarm ? '🚨 ' : ''}{b.name}
                      </td>
                      <td className="px-4 py-3"><BerthTypeBadge type={b.berth_type} /></td>
                      <td className="px-4 py-3"><StatusBadge status={b.status} /></td>
                      <td className="px-4 py-3"><StateCodeBadge stateCode={b.state_code} /></td>
                      <td className="px-4 py-3 text-xs font-mono">
                        {b.match_score !== null && b.match_score !== undefined ? (
                          <span className={b.match_ok_bit ? 'text-green-400' : 'text-red-400'}>
                            {b.match_score.toFixed(4)}
                          </span>
                        ) : (
                          <span className="text-gray-600">—</span>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        <CameraStatusDot reachable={b.camera_reachable ?? false} hasUrl={!!b.camera_stream_url} />
                      </td>
                      <td className="px-4 py-3 text-gray-400 text-xs">
                        {b.last_analyzed ? new Date(b.last_analyzed).toLocaleTimeString() : '—'}
                        {b.analysis_error && (
                          <div className="text-red-500 text-xs mt-0.5 max-w-[140px] truncate" title={b.analysis_error}>
                            ⚠ {b.analysis_error}
                          </div>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex gap-2 flex-wrap">
                          {/* Live view — only if camera is active */}
                          <button
                            onClick={() => handleLiveView(b as BerthOut)}
                            title={
                              !b.camera_stream_url
                                ? 'No camera configured'
                                : !b.camera_reachable
                                  ? 'Camera unreachable'
                                  : 'View live camera feed'
                            }
                            className={`text-xs border px-2 py-1 rounded transition-colors ${
                              b.camera_stream_url && b.camera_reachable
                                ? 'text-blue-400 hover:text-blue-300 border-blue-600/40'
                                : 'text-gray-600 border-gray-700/40 cursor-not-allowed'
                            }`}
                          >
                            📹 View
                          </button>

                          {/* Calendar for reserved berths */}
                          {b.status === 'reserved' && (
                            <button
                              onClick={() => openCalendar(b as BerthOut)}
                              className="text-xs text-amber-400 hover:text-amber-300 border border-amber-600/40 px-2 py-1 rounded"
                            >
                              📅 Calendar
                            </button>
                          )}

                          {/* On-demand analyze */}
                          <button
                            onClick={() => handleAnalyze(b as BerthOut)}
                            disabled={analyzingId === b.id}
                            className="text-xs text-gray-400 hover:text-gray-200 border border-gray-700 px-2 py-1 rounded disabled:opacity-50 disabled:cursor-wait"
                          >
                            {analyzingId === b.id ? '⏳ Analyzing…' : '🔄 Analyze'}
                          </button>

                          {/* Reference images */}
                          <button
                            onClick={() => setRefModalBerth(b as BerthOut)}
                            title="Manage reference ship images for matching"
                            className={`text-xs border px-2 py-1 rounded transition-colors ${
                              (b.reference_image_count ?? 0) > 0
                                ? 'text-green-400 border-green-700/50 hover:text-green-300'
                                : 'text-yellow-400 border-yellow-700/50 hover:text-yellow-300'
                            }`}
                          >
                            🖼 Refs {(b.reference_image_count ?? 0) > 0 ? `(${b.reference_image_count})` : ''}
                          </button>

                          {/* Berth config */}
                          <button
                            onClick={() => setConfigBerth(b as BerthOut)}
                            title="Configure berth"
                            className="text-xs text-gray-400 hover:text-gray-200 border border-gray-700 px-2 py-1 rounded"
                          >
                            ⚙ Config
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}

      {/* ── Modals ───────────────────────────────────────────────────────────── */}
      {liveModalBerth && (
        <LiveModal berth={liveModalBerth} onClose={() => setLiveModalBerth(null)} />
      )}

      {calendarBerth && (
        <CalendarModal
          berth={calendarBerth}
          entries={calendarEntries}
          loading={calendarLoading}
          onClose={() => { setCalendarBerth(null); setCalendarEntries([]) }}
        />
      )}

      {refModalBerth && (
        <RefImagesModal
          berth={refModalBerth}
          onClose={() => { setRefModalBerth(null); refresh() }}
        />
      )}

      {configBerth && (
        <BerthConfigModal
          berth={configBerth}
          onClose={() => { setConfigBerth(null); refresh() }}
        />
      )}
    </div>
  )
}

// ─── Summary card ─────────────────────────────────────────────────────────────

function SummaryCard({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <div className="rounded-lg border border-gray-700 bg-gray-900 px-4 py-3 text-center">
      <div className="text-xs text-gray-500 mb-1">{label}</div>
      <div className={`text-2xl font-bold ${color}`}>{value}</div>
    </div>
  )
}

// ─── Berth config modal ───────────────────────────────────────────────────────

function BerthConfigModal({ berth, onClose }: { berth: BerthOut; onClose: () => void }) {
  const [name, setName] = useState(berth.name)
  const [pedestalId, setPedestalId] = useState(String(berth.pedestal_id ?? ''))
  const [berthType, setBerthType] = useState<'transit' | 'yearly'>(berth.berth_type ?? 'transit')
  const [saving, setSaving] = useState(false)
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null)

  const handleSave = async () => {
    setSaving(true)
    setMsg(null)
    try {
      await updateBerthConfig(berth.id, {
        name: name.trim() || undefined,
        pedestal_id: pedestalId ? parseInt(pedestalId) : undefined,
        berth_type: berthType,
      })
      setMsg({ ok: true, text: 'Berth configuration saved.' })
    } catch {
      setMsg({ ok: false, text: 'Save failed.' })
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-4" onClick={onClose}>
      <div className="bg-gray-900 rounded-2xl border border-gray-700 max-w-sm w-full" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-800">
          <div>
            <h3 className="text-white font-bold text-lg">⚙ Berth Configuration</h3>
            <p className="text-gray-400 text-sm">{berth.name}</p>
          </div>
          <button onClick={onClose} className="w-8 h-8 rounded-full bg-gray-700 text-white text-sm flex items-center justify-center hover:bg-gray-600">✕</button>
        </div>

        <div className="p-6 space-y-4">
          <div>
            <label className="block text-xs text-gray-400 mb-1">Berth Name</label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-gray-200 text-sm focus:outline-none focus:border-blue-500"
            />
          </div>

          <div>
            <label className="block text-xs text-gray-400 mb-1">Pedestal ID</label>
            <input
              type="number"
              value={pedestalId}
              onChange={(e) => setPedestalId(e.target.value)}
              placeholder="e.g. 1"
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-gray-200 text-sm focus:outline-none focus:border-blue-500"
            />
          </div>

          <div>
            <label className="block text-xs text-gray-400 mb-2">Berth Type</label>
            <div className="grid grid-cols-2 gap-2">
              {(['transit', 'yearly'] as const).map((t) => (
                <button
                  key={t}
                  onClick={() => setBerthType(t)}
                  className={`py-2 rounded-lg text-sm font-semibold border transition-colors ${
                    berthType === t
                      ? t === 'transit'
                        ? 'bg-cyan-700/40 border-cyan-500 text-cyan-300'
                        : 'bg-purple-700/40 border-purple-500 text-purple-300'
                      : 'bg-gray-800 border-gray-700 text-gray-400 hover:border-gray-500'
                  }`}
                >
                  {t === 'transit' ? '⛵ Transit' : '🔒 Yearly'}
                </button>
              ))}
            </div>
            <p className="text-xs text-gray-600 mt-1.5">
              {berthType === 'transit' ? 'Short-stay visitors passing through.' : 'Long-term tenants with a yearly contract.'}
            </p>
          </div>

          {msg && (
            <div className={`text-sm px-3 py-2 rounded-lg ${msg.ok ? 'bg-green-900/30 text-green-400' : 'bg-red-900/30 text-red-400'}`}>
              {msg.text}
            </div>
          )}

          <div className="flex gap-2 pt-1">
            <button onClick={onClose} className="flex-1 py-2 rounded-lg border border-gray-700 text-gray-400 text-sm hover:text-gray-200">
              {msg?.ok ? 'Close' : 'Cancel'}
            </button>
            <button
              onClick={handleSave}
              disabled={saving}
              className="flex-1 py-2 rounded-lg bg-blue-700 hover:bg-blue-600 text-white text-sm font-medium disabled:opacity-50"
            >
              {saving ? 'Saving…' : 'Save'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

// ─── SVG Dock Visualization ───────────────────────────────────────────────────

function DockVisualization({
  berths,
  onBerthClick,
}: {
  berths: import('../store').BerthStatus[]
  onBerthClick: (b: BerthOut) => void
}) {
  const BERTH_W = 180
  const BERTH_H = 120
  const GAP = 30
  const START_X = 55
  const START_Y = 60

  return (
    <div className="bg-gray-900 rounded-xl border border-gray-800 p-6">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-semibold text-white">⚓ Marina Portorož — Dock A</h2>
        <div className="flex gap-4 text-xs text-gray-400">
          <LegendDot color="#22c55e" label="Free" />
          <LegendDot color="#6b7280" label="Occupied" />
          <LegendDot color="#f59e0b" label="Reserved" />
        </div>
      </div>

      <svg viewBox="0 0 800 260" className="w-full max-w-3xl mx-auto" style={{ fontFamily: 'sans-serif' }}>
        <rect x="0" y="0" width="800" height="260" fill="#0c1a2e" rx="12" />
        <rect x="30" y="200" width="740" height="40" fill="#374151" rx="4" />
        <text x="400" y="226" textAnchor="middle" fill="#9ca3af" fontSize="13" fontWeight="600">
          Pier — Marina Portorož
        </text>

        {berths.map((b, i) => {
          const x = START_X + i * (BERTH_W + GAP)
          const y = START_Y
          const color = STATUS_COLOR[b.status] ?? '#6b7280'
          const hasCamera = !!(b as any).camera_stream_url && (b as any).camera_reachable
          const isReserved = b.status === 'reserved'
          const clickable = hasCamera || isReserved

          return (
            <g key={b.id} style={{ cursor: clickable ? 'pointer' : 'default' }}
              onClick={() => clickable && onBerthClick(b as BerthOut)}>
              <rect x={x} y={y} width={BERTH_W} height={BERTH_H}
                fill={color + '22'} stroke={color} strokeWidth="2" rx="8" />
              <text x={x + BERTH_W / 2} y={y + 38} textAnchor="middle" fontSize="26">
                {b.status === 'free' ? '🟢' : b.status === 'occupied' ? '⛵' : '📅'}
              </text>
              <text x={x + BERTH_W / 2} y={y + 64} textAnchor="middle" fill="#f9fafb" fontSize="11" fontWeight="700">
                {b.name.length > 22 ? b.name.slice(0, 20) + '…' : b.name}
              </text>
              <text x={x + BERTH_W / 2} y={y + 82} textAnchor="middle" fill={color} fontSize="11" fontWeight="600">
                {STATUS_LABEL[b.status] ?? b.status}
              </text>
              {b.pedestal_id && (
                <text x={x + BERTH_W / 2} y={y + 98} textAnchor="middle" fill="#6b7280" fontSize="10">
                  Pedestal {b.pedestal_id}
                </text>
              )}
              {clickable && (
                <text x={x + BERTH_W / 2} y={y + 114} textAnchor="middle" fill="#60a5fa" fontSize="9">
                  {hasCamera ? '📹 tap to view' : '📅 tap for calendar'}
                </text>
              )}
              <line x1={x + 40} y1={y + BERTH_H} x2={x + 40} y2={200} stroke="#4b5563" strokeWidth="2" strokeDasharray="4,4" />
              <line x1={x + BERTH_W - 40} y1={y + BERTH_H} x2={x + BERTH_W - 40} y2={200} stroke="#4b5563" strokeWidth="2" strokeDasharray="4,4" />
            </g>
          )
        })}

        <text x="680" y="160" fill="#1e3a5f" fontSize="40" opacity="0.6">〰〰</text>
        <text x="30" y="180" fill="#1e3a5f" fontSize="28" opacity="0.4">〰〰〰</text>
      </svg>
    </div>
  )
}

// ─── Live Camera Modal ────────────────────────────────────────────────────────

function LiveModal({ berth, onClose }: { berth: BerthOut; onClose: () => void }) {
  const [imgSrc, setImgSrc] = useState<string | null>(null)
  const [streamError, setStreamError] = useState(false)
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const fetchSnapshot = useCallback(async () => {
    if (!berth.pedestal_id) return
    try {
      const token = useAuthStore.getState().token
      const res = await fetch(`/api/camera/${berth.pedestal_id}/snapshot`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      })
      if (!res.ok) { setStreamError(true); return }
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      setImgSrc((prev) => { if (prev) URL.revokeObjectURL(prev); return url })
      setStreamError(false)
    } catch {
      setStreamError(true)
    }
  }, [berth.pedestal_id])

  useEffect(() => {
    fetchSnapshot()
    intervalRef.current = setInterval(fetchSnapshot, 2000)
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current)
    }
  }, [fetchSnapshot])

  return (
    <div className="fixed inset-0 z-50 bg-black/80 flex items-center justify-center p-4" onClick={onClose}>
      <div className="bg-gray-950 rounded-2xl overflow-hidden max-w-3xl w-full" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center gap-3 px-5 py-4 border-b border-gray-800">
          <span className="flex items-center gap-1.5 bg-red-600 text-white text-xs font-bold px-2.5 py-1 rounded-full">
            <span className="w-1.5 h-1.5 rounded-full bg-white animate-pulse" />
            LIVE
          </span>
          <span className="flex-1 text-white font-semibold">{berth.name} — Berth Camera</span>
          <button onClick={onClose} className="w-8 h-8 rounded-full bg-gray-700 text-white text-sm flex items-center justify-center hover:bg-gray-600">
            ✕
          </button>
        </div>

        <div className="min-h-[300px] bg-black flex items-center justify-center">
          {streamError ? (
            <div className="text-center text-gray-400 py-16">
              <div className="text-4xl mb-3">📷</div>
              <div className="text-sm font-medium">Live stream not detected</div>
              <div className="text-xs text-gray-600 mt-1">Check camera connection and stream URL</div>
            </div>
          ) : imgSrc ? (
            <img src={imgSrc} alt="Live berth view" className="w-full max-h-[70vh] object-contain" />
          ) : (
            <div className="text-gray-500 text-sm">Connecting to camera…</div>
          )}
        </div>

        <div className="px-5 py-3 text-center text-xs text-gray-500 border-t border-gray-800">
          📍 Marina Portorož — {berth.name} · Refreshing every 2 s
        </div>
      </div>
    </div>
  )
}

// ─── Reference Images Modal ───────────────────────────────────────────────────

function RefImagesModal({ berth, onClose }: { berth: BerthOut; onClose: () => void }) {
  const [images, setImages] = useState<string[]>([])
  const [loading, setLoading] = useState(true)
  const [uploading, setUploading] = useState(false)
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const load = async () => {
    setLoading(true)
    try { setImages(await getReferenceImages(berth.id)) } catch { setImages([]) }
    setLoading(false)
  }

  useEffect(() => { load() }, [berth.id])

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files
    if (!files || files.length === 0) return
    setUploading(true)
    const fd = new FormData()
    for (let i = 0; i < files.length; i++) fd.append('files', files[i])
    try {
      const res = await uploadReferenceImages(berth.id, fd)
      setMsg({ ok: true, text: `✓ ${res.count} image(s) uploaded` })
      await load()
    } catch {
      setMsg({ ok: false, text: 'Upload failed' })
    } finally {
      setUploading(false)
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }

  const handleDelete = async (fname: string) => {
    try {
      await deleteReferenceImage(berth.id, fname)
      await load()
    } catch {
      setMsg({ ok: false, text: 'Delete failed' })
    }
  }

  return (
    <div className="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-4" onClick={onClose}>
      <div className="bg-gray-900 rounded-2xl border border-gray-700 max-w-lg w-full" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-800">
          <div>
            <h3 className="text-white font-bold text-lg">🖼 Reference Ship Images</h3>
            <p className="text-gray-400 text-sm">{berth.name} — used for ship matching during analysis</p>
          </div>
          <button onClick={onClose} className="w-8 h-8 rounded-full bg-gray-700 text-white text-sm flex items-center justify-center hover:bg-gray-600">✕</button>
        </div>

        <div className="p-6 space-y-4">
          <p className="text-xs text-gray-500">
            Upload photos of the expected ship for this berth. During analysis, a live snapshot is compared
            against these images. High similarity → correct ship. Low similarity → alarm.
          </p>

          {msg && (
            <div className={`text-sm px-3 py-2 rounded-lg ${msg.ok ? 'bg-green-900/30 text-green-400' : 'bg-red-900/30 text-red-400'}`}>
              {msg.text}
            </div>
          )}

          {/* Upload */}
          <div>
            <input
              ref={fileInputRef}
              type="file"
              accept="image/jpeg,image/png,image/webp"
              multiple
              className="hidden"
              onChange={handleUpload}
            />
            <button
              onClick={() => fileInputRef.current?.click()}
              disabled={uploading}
              className="w-full py-2 rounded-lg bg-blue-700 hover:bg-blue-600 text-white text-sm font-medium transition-colors disabled:opacity-50"
            >
              {uploading ? 'Uploading…' : '+ Upload Reference Images'}
            </button>
          </div>

          {/* Image list */}
          {loading ? (
            <div className="text-gray-500 text-center py-4 text-sm">Loading…</div>
          ) : images.length === 0 ? (
            <div className="text-center text-gray-500 py-4 text-sm">
              No reference images yet. Upload photos of the expected ship.
            </div>
          ) : (
            <div className="space-y-2 max-h-64 overflow-y-auto">
              {images.map((fname) => (
                <div key={fname} className="flex items-center justify-between px-3 py-2 rounded-lg bg-gray-800/60 border border-gray-700">
                  <span className="text-sm text-gray-300 font-mono truncate flex-1">{fname}</span>
                  <button
                    onClick={() => handleDelete(fname)}
                    className="ml-3 text-xs text-red-400 hover:text-red-300 border border-red-700/40 px-2 py-1 rounded"
                  >
                    Delete
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

// ─── Calendar Modal ───────────────────────────────────────────────────────────

function CalendarModal({
  berth, entries, loading, onClose,
}: { berth: BerthOut; entries: CalendarEntry[]; loading: boolean; onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-4" onClick={onClose}>
      <div className="bg-gray-900 rounded-2xl border border-gray-700 max-w-lg w-full" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-800">
          <div>
            <h3 className="text-white font-bold text-lg">📅 Reservation Calendar</h3>
            <p className="text-gray-400 text-sm">{berth.name}</p>
          </div>
          <button onClick={onClose} className="w-8 h-8 rounded-full bg-gray-700 text-white text-sm flex items-center justify-center hover:bg-gray-600">✕</button>
        </div>
        <div className="p-6">
          {loading ? (
            <div className="text-gray-500 text-center py-8">Loading…</div>
          ) : entries.length === 0 ? (
            <div className="text-center text-gray-500 py-8">No reservations for this berth.</div>
          ) : (
            <div className="space-y-3">
              {entries.map((e) => (
                <div key={e.reservation_id} className={`rounded-lg border px-4 py-3 flex items-center justify-between ${
                  e.status === 'confirmed' ? 'bg-amber-900/30 border-amber-700/50' : 'bg-gray-800 border-gray-700 opacity-50'
                }`}>
                  <div>
                    <div className="text-white text-sm font-semibold">{e.check_in_date} → {e.check_out_date}</div>
                    <div className="text-gray-400 text-xs mt-0.5">Customer #{e.customer_id}</div>
                  </div>
                  <span className={`text-xs font-bold px-2 py-1 rounded-full ${
                    e.status === 'confirmed' ? 'bg-amber-500/20 text-amber-400' : 'bg-gray-700 text-gray-500'
                  }`}>{e.status}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

// ─── Small helpers ────────────────────────────────────────────────────────────

function CameraStatusDot({ reachable, hasUrl }: { reachable: boolean; hasUrl: boolean }) {
  if (!hasUrl) return <span className="text-xs text-gray-600">No camera</span>
  return (
    <span className="flex items-center gap-1.5">
      <span className={`w-2 h-2 rounded-full flex-shrink-0 ${reachable ? 'bg-green-400 animate-pulse' : 'bg-red-600'}`} />
      <span className={`text-xs ${reachable ? 'text-green-400' : 'text-red-400'}`}>
        {reachable ? 'Live' : 'Offline'}
      </span>
    </span>
  )
}

function BerthTypeBadge({ type }: { type: string }) {
  return type === 'yearly'
    ? <span className="text-xs font-semibold px-2 py-0.5 rounded-full border bg-purple-500/20 text-purple-400 border-purple-700/40">Yearly</span>
    : <span className="text-xs font-semibold px-2 py-0.5 rounded-full border bg-cyan-500/20 text-cyan-400 border-cyan-700/40">Transit</span>
}

function StatusBadge({ status }: { status: string }) {
  const cfg: Record<string, string> = {
    free: 'bg-green-500/20 text-green-400 border-green-700/40',
    occupied: 'bg-gray-600/30 text-gray-400 border-gray-600/40',
    reserved: 'bg-amber-500/20 text-amber-400 border-amber-700/40',
  }
  return (
    <span className={`text-xs font-semibold px-2 py-0.5 rounded-full border ${cfg[status] ?? 'bg-gray-700/20 text-gray-500 border-gray-700/40'}`}>
      {STATUS_LABEL[status] ?? status}
    </span>
  )
}

function LegendDot({ color, label }: { color: string; label: string }) {
  return (
    <div className="flex items-center gap-1.5">
      <span className="w-3 h-3 rounded-full" style={{ backgroundColor: color }} />
      <span>{label}</span>
    </div>
  )
}

function StateCodeBadge({ stateCode }: { stateCode: number }) {
  const cfg: Record<number, { label: string; cls: string }> = {
    0: { label: 'FREE',         cls: 'bg-green-500/20 text-green-400 border-green-700/40' },
    1: { label: 'OK — MATCH',   cls: 'bg-blue-500/20  text-blue-400  border-blue-700/40'  },
    2: { label: '⚠ WRONG SHIP', cls: 'bg-red-500/20   text-red-400   border-red-700/40 animate-pulse' },
  }
  const c = cfg[stateCode] ?? { label: `code ${stateCode}`, cls: 'bg-gray-700 text-gray-400 border-gray-600' }
  return (
    <span className={`text-xs font-bold px-2 py-0.5 rounded-full border ${c.cls}`}>
      {c.label}
    </span>
  )
}
