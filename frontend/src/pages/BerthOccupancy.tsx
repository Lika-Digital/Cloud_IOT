import { useEffect, useRef, useState } from 'react'
import { useStore } from '../store'
import { getBerths, getBerthCalendar, triggerAnalysis, captureBackground, type BerthOut, type CalendarEntry } from '../api/berths'

// Video assets (bundled via Vite)
import berthFullVideo from '../assets/Berth Full.mp4'
import berthEmptyVideo from '../assets/Berth empty.mp4'

// Map video_source filename → bundled asset URL
function resolveVideoUrl(videoSource: string | null): string | null {
  if (!videoSource) return null
  if (videoSource.toLowerCase().includes('full')) return berthFullVideo
  if (videoSource.toLowerCase().includes('empty')) return berthEmptyVideo
  return null
}

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
  const { berthOccupancy, setBerthOccupancy } = useStore()
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [videoModalBerth, setVideoModalBerth] = useState<BerthOut | null>(null)
  const [calendarBerth, setCalendarBerth] = useState<BerthOut | null>(null)
  const [calendarEntries, setCalendarEntries] = useState<CalendarEntry[]>([])
  const [calendarLoading, setCalendarLoading] = useState(false)
  const [analyzingId, setAnalyzingId] = useState<number | null>(null)
  const [analyzeResult, setAnalyzeResult] = useState<string | null>(null)
  const [capturingId, setCapturingId] = useState<number | null>(null)

  const refresh = () =>
    getBerths()
      .then((data: import('../store').BerthStatus[]) => { setBerthOccupancy(data); setLoadError(null) })
      .catch(() => setLoadError('Failed to load berth data. Retrying on next refresh.'))

  // Load berths on mount
  useEffect(() => {
    refresh().finally(() => setLoading(false))
  }, [])

  const openCalendar = async (berth: BerthOut) => {
    setCalendarBerth(berth)
    setCalendarLoading(true)
    try {
      const entries = await getBerthCalendar(berth.id)
      setCalendarEntries(entries)
    } catch {
      setCalendarEntries([])
    }
    setCalendarLoading(false)
  }

  const handleCaptureBackground = async (berthId: number) => {
    setCapturingId(berthId)
    try {
      const res = await captureBackground(berthId)
      setAnalyzeResult(`✓ Background set (${res.width}×${res.height})`)
      await refresh()
    } catch {
      setAnalyzeResult('⚠ Failed to capture background')
    } finally {
      setCapturingId(null)
      setTimeout(() => setAnalyzeResult(null), 5000)
    }
  }

  const handleManualAnalyze = async (berthId: number) => {
    setAnalyzingId(berthId)
    setAnalyzeResult(null)
    try {
      const res = await triggerAnalysis(berthId)
      setAnalyzeResult(`✓ ${res.detected_status}`)
      await refresh()
    } catch {
      setAnalyzeResult('⚠ ML Worker unavailable')
    } finally {
      setAnalyzingId(null)
      setTimeout(() => setAnalyzeResult(null), 4000)
    }
  }

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-bold text-white">Berth Occupancy</h1>
        <p className="text-gray-400 text-sm mt-1">Real-time dock status — updated every 30 s by camera analysis</p>
      </div>

      {loadError && (
        <div className="px-4 py-3 rounded-lg bg-red-900/30 border border-red-700/40 text-red-400 text-sm">
          {loadError}
        </div>
      )}

      {analyzeResult && (
        <div className={`text-sm font-semibold px-4 py-2 rounded-lg border w-fit ${
          analyzeResult.startsWith('✓')
            ? 'bg-green-900/30 border-green-700/50 text-green-400'
            : 'bg-red-900/30 border-red-700/50 text-red-400'
        }`}>
          {analyzeResult}
        </div>
      )}

      {loading ? (
        <div className="text-gray-500 text-center py-16">Loading berth data…</div>
      ) : (
        <>
          {/* ── Dock SVG visualization ─────────────────────────────────────── */}
          <DockVisualization
            berths={berthOccupancy}
            onBerthClick={(b) => {
              if (b.video_source) setVideoModalBerth(b)
              else if (b.status === 'reserved') openCalendar(b)
            }}
          />

          {/* ── Occupancy table ────────────────────────────────────────────── */}
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
                    <th className="px-4 py-3 text-left">Status</th>
                    <th className="px-4 py-3 text-left">ML State</th>
                    <th className="px-4 py-3 text-left">Match Score</th>
                    <th className="px-4 py-3 text-left">Pedestal</th>
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
                      <td className="px-4 py-3">
                        <StatusBadge status={b.status} />
                      </td>
                      <td className="px-4 py-3">
                        <StateCodeBadge stateCode={b.state_code} />
                      </td>
                      <td className="px-4 py-3 text-xs font-mono">
                        {b.match_score !== null && b.match_score !== undefined ? (
                          <span className={b.match_ok_bit ? 'text-green-400' : 'text-red-400'}>
                            {b.match_score.toFixed(4)}
                          </span>
                        ) : (
                          <span className="text-gray-600">—</span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-gray-400">
                        {b.pedestal_id ? `Pedestal ${b.pedestal_id}` : '—'}
                      </td>
                      <td className="px-4 py-3 text-gray-400 text-xs">
                        {b.last_analyzed
                          ? new Date(b.last_analyzed).toLocaleTimeString()
                          : '—'}
                        {b.analysis_error && (
                          <div className="text-red-500 text-xs mt-0.5 max-w-[140px] truncate" title={b.analysis_error}>
                            ⚠ {b.analysis_error}
                          </div>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex gap-2">
                          {b.video_source && (
                            <button
                              onClick={() => setVideoModalBerth(b)}
                              className="text-xs text-blue-400 hover:text-blue-300 border border-blue-600/40 px-2 py-1 rounded"
                            >
                              📹 View
                            </button>
                          )}
                          {b.status === 'reserved' && (
                            <button
                              onClick={() => openCalendar(b)}
                              className="text-xs text-amber-400 hover:text-amber-300 border border-amber-600/40 px-2 py-1 rounded"
                            >
                              📅 Calendar
                            </button>
                          )}
                          <button
                            onClick={() => handleManualAnalyze(b.id)}
                            disabled={analyzingId === b.id}
                            className="text-xs text-gray-400 hover:text-gray-200 border border-gray-700 px-2 py-1 rounded disabled:opacity-50 disabled:cursor-wait"
                          >
                            {analyzingId === b.id ? '⏳ Analyzing…' : '🔄 Analyze'}
                          </button>
                          {b.video_source && (
                            <button
                              onClick={() => handleCaptureBackground(b.id)}
                              disabled={capturingId === b.id}
                              title={b.background_image ? `Background set: ${b.background_image}` : 'Capture current video frame as empty-berth baseline'}
                              className={`text-xs border px-2 py-1 rounded disabled:opacity-50 disabled:cursor-wait transition-colors ${
                                b.background_image
                                  ? 'text-green-400 border-green-700/50 hover:text-green-300'
                                  : 'text-yellow-400 border-yellow-700/50 hover:text-yellow-300'
                              }`}
                            >
                              {capturingId === b.id ? '⏳…' : b.background_image ? '🖼 BG ✓' : '🖼 Set BG'}
                            </button>
                          )}
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

      {/* ── Video modal ──────────────────────────────────────────────────────── */}
      {videoModalBerth && (
        <VideoModal
          berth={videoModalBerth}
          onClose={() => setVideoModalBerth(null)}
        />
      )}

      {/* ── Calendar modal ───────────────────────────────────────────────────── */}
      {calendarBerth && (
        <CalendarModal
          berth={calendarBerth}
          entries={calendarEntries}
          loading={calendarLoading}
          onClose={() => { setCalendarBerth(null); setCalendarEntries([]) }}
        />
      )}
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
  // Layout: 3 berths side by side in a simple top-down dock view
  // viewBox 800×320, dock pier at bottom, berths above it
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

      <svg
        viewBox="0 0 800 260"
        className="w-full max-w-3xl mx-auto"
        style={{ fontFamily: 'sans-serif' }}
      >
        {/* Water background */}
        <rect x="0" y="0" width="800" height="260" fill="#0c1a2e" rx="12" />

        {/* Pier / dock walkway */}
        <rect x="30" y="200" width="740" height="40" fill="#374151" rx="4" />
        <text x="400" y="226" textAnchor="middle" fill="#9ca3af" fontSize="13" fontWeight="600">
          Pier — Marina Portorož
        </text>

        {/* Berth slots */}
        {berths.map((b, i) => {
          const x = START_X + i * (BERTH_W + GAP)
          const y = START_Y
          const color = STATUS_COLOR[b.status] ?? '#6b7280'
          const hasVideo = !!b.video_source
          const isReserved = b.status === 'reserved'

          return (
            <g
              key={b.id}
              style={{ cursor: hasVideo || isReserved ? 'pointer' : 'default' }}
              onClick={() => onBerthClick(b as BerthOut)}
            >
              {/* Berth rectangle */}
              <rect
                x={x} y={y}
                width={BERTH_W} height={BERTH_H}
                fill={color + '22'}
                stroke={color}
                strokeWidth="2"
                rx="8"
              />

              {/* Status icon */}
              <text x={x + BERTH_W / 2} y={y + 38} textAnchor="middle" fontSize="26">
                {b.status === 'free' ? '🟢' : b.status === 'occupied' ? '⛵' : '📅'}
              </text>

              {/* Berth name */}
              <text
                x={x + BERTH_W / 2} y={y + 64}
                textAnchor="middle" fill="#f9fafb" fontSize="11" fontWeight="700"
              >
                {b.name.length > 22 ? b.name.slice(0, 20) + '…' : b.name}
              </text>

              {/* Status label */}
              <text
                x={x + BERTH_W / 2} y={y + 82}
                textAnchor="middle" fill={color} fontSize="11" fontWeight="600"
              >
                {STATUS_LABEL[b.status] ?? b.status}
              </text>

              {/* Pedestal label */}
              {b.pedestal_id && (
                <text
                  x={x + BERTH_W / 2} y={y + 98}
                  textAnchor="middle" fill="#6b7280" fontSize="10"
                >
                  Pedestal {b.pedestal_id}
                </text>
              )}

              {/* Click hint */}
              {(hasVideo || isReserved) && (
                <text
                  x={x + BERTH_W / 2} y={y + 114}
                  textAnchor="middle" fill="#60a5fa" fontSize="9"
                >
                  {hasVideo ? '▶ tap to view' : '📅 tap for calendar'}
                </text>
              )}

              {/* Mooring lines to pier */}
              <line
                x1={x + 40} y1={y + BERTH_H}
                x2={x + 40} y2={200}
                stroke="#4b5563" strokeWidth="2" strokeDasharray="4,4"
              />
              <line
                x1={x + BERTH_W - 40} y1={y + BERTH_H}
                x2={x + BERTH_W - 40} y2={200}
                stroke="#4b5563" strokeWidth="2" strokeDasharray="4,4"
              />
            </g>
          )
        })}

        {/* Water waves decoration */}
        <text x="680" y="160" fill="#1e3a5f" fontSize="40" opacity="0.6">〰〰</text>
        <text x="30" y="180" fill="#1e3a5f" fontSize="28" opacity="0.4">〰〰〰</text>
      </svg>
    </div>
  )
}

// ─── Video Modal ──────────────────────────────────────────────────────────────

function VideoModal({ berth, onClose }: { berth: BerthOut; onClose: () => void }) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const videoUrl = resolveVideoUrl(berth.video_source)

  return (
    <div
      className="fixed inset-0 z-50 bg-black/80 flex items-center justify-center p-4"
      onClick={onClose}
    >
      <div
        className="bg-gray-950 rounded-2xl overflow-hidden max-w-3xl w-full"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center gap-3 px-5 py-4 border-b border-gray-800">
          <span className="flex items-center gap-1.5 bg-red-600 text-white text-xs font-bold px-2.5 py-1 rounded-full">
            <span className="w-1.5 h-1.5 rounded-full bg-white" />
            LIVE
          </span>
          <span className="flex-1 text-white font-semibold">{berth.name} — Berth Camera</span>
          <button
            onClick={onClose}
            className="w-8 h-8 rounded-full bg-gray-700 text-white text-sm flex items-center justify-center hover:bg-gray-600"
          >
            ✕
          </button>
        </div>

        {/* Video */}
        {videoUrl ? (
          <video
            ref={videoRef}
            src={videoUrl}
            className="w-full max-h-[70vh] object-contain bg-black"
            autoPlay
            loop
            controls
          />
        ) : (
          <div className="flex items-center justify-center h-48 text-gray-500">
            No video stream available
          </div>
        )}

        {/* Footer */}
        <div className="px-5 py-3 text-center text-xs text-gray-500 border-t border-gray-800">
          📍 Marina Portorož — {berth.name}
        </div>
      </div>
    </div>
  )
}

// ─── Calendar Modal ───────────────────────────────────────────────────────────

function CalendarModal({
  berth,
  entries,
  loading,
  onClose,
}: {
  berth: BerthOut
  entries: CalendarEntry[]
  loading: boolean
  onClose: () => void
}) {
  return (
    <div
      className="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-4"
      onClick={onClose}
    >
      <div
        className="bg-gray-900 rounded-2xl border border-gray-700 max-w-lg w-full"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-800">
          <div>
            <h3 className="text-white font-bold text-lg">📅 Reservation Calendar</h3>
            <p className="text-gray-400 text-sm">{berth.name}</p>
          </div>
          <button
            onClick={onClose}
            className="w-8 h-8 rounded-full bg-gray-700 text-white text-sm flex items-center justify-center hover:bg-gray-600"
          >
            ✕
          </button>
        </div>

        <div className="p-6">
          {loading ? (
            <div className="text-gray-500 text-center py-8">Loading…</div>
          ) : entries.length === 0 ? (
            <div className="text-center text-gray-500 py-8">No reservations for this berth.</div>
          ) : (
            <div className="space-y-3">
              {entries.map((e) => (
                <div
                  key={e.reservation_id}
                  className={`rounded-lg border px-4 py-3 flex items-center justify-between ${
                    e.status === 'confirmed'
                      ? 'bg-amber-900/30 border-amber-700/50'
                      : 'bg-gray-800 border-gray-700 opacity-50'
                  }`}
                >
                  <div>
                    <div className="text-white text-sm font-semibold">
                      {e.check_in_date} → {e.check_out_date}
                    </div>
                    <div className="text-gray-400 text-xs mt-0.5">
                      Customer #{e.customer_id}
                    </div>
                  </div>
                  <span
                    className={`text-xs font-bold px-2 py-1 rounded-full ${
                      e.status === 'confirmed'
                        ? 'bg-amber-500/20 text-amber-400'
                        : 'bg-gray-700 text-gray-500'
                    }`}
                  >
                    {e.status}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function StatusBadge({ status }: { status: 'free' | 'occupied' | 'reserved' | string }) {
  const cfg: Record<string, string> = {
    free: 'bg-green-500/20 text-green-400 border-green-700/40',
    occupied: 'bg-gray-600/30 text-gray-400 border-gray-600/40',
    reserved: 'bg-amber-500/20 text-amber-400 border-amber-700/40',
  }
  const cls = cfg[status] ?? 'bg-gray-700/20 text-gray-500 border-gray-700/40'
  return (
    <span className={`text-xs font-semibold px-2 py-0.5 rounded-full border ${cls}`}>
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
    0: { label: 'FREE',             cls: 'bg-green-500/20 text-green-400 border-green-700/40' },
    1: { label: 'OK — MATCH',       cls: 'bg-blue-500/20  text-blue-400  border-blue-700/40'  },
    2: { label: '⚠ WRONG SHIP',     cls: 'bg-red-500/20   text-red-400   border-red-700/40 animate-pulse' },
  }
  const c = cfg[stateCode] ?? { label: `code ${stateCode}`, cls: 'bg-gray-700 text-gray-400 border-gray-600' }
  return (
    <span className={`text-xs font-bold px-2 py-0.5 rounded-full border ${c.cls}`}>
      {c.label}
    </span>
  )
}
