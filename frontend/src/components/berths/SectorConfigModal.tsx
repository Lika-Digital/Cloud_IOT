import { useCallback, useEffect, useRef, useState } from 'react'
import {
  getLatestFrame,
  updateBerthConfig,
  uploadSampleEmbedding,
  type BerthOut,
} from '../../api/berths'

interface Zone {
  x1: number
  y1: number
  x2: number
  y2: number
}

interface Props {
  berth: BerthOut
  onClose: () => void
}

export default function SectorConfigModal({ berth, onClose }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const imgRef = useRef<HTMLImageElement | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const [frameB64, setFrameB64] = useState<string | null>(null)
  const [frameLoading, setFrameLoading] = useState(false)
  const [zone, setZone] = useState<Zone>({
    x1: berth.zone_x1 ?? 0.1,
    y1: berth.zone_y1 ?? 0.1,
    x2: berth.zone_x2 ?? 0.9,
    y2: berth.zone_y2 ?? 0.9,
  })
  const [useZone, setUseZone] = useState(!!berth.use_detection_zone)
  const [isDragging, setIsDragging] = useState(false)
  const [dragStart, setDragStart] = useState<{ x: number; y: number } | null>(null)
  const [embeddingStatus, setEmbeddingStatus] = useState({
    exists: !!berth.sample_embedding_path,
    updatedAt: berth.sample_updated_at ?? null,
  })
  const [berthNumber, setBerthNumber] = useState<string>(
    berth.berth_number != null ? String(berth.berth_number) : ''
  )
  const [saving, setSaving] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null)

  // Stable original values for Reset
  const originalZone = useRef<Zone>({
    x1: berth.zone_x1 ?? 0.1,
    y1: berth.zone_y1 ?? 0.1,
    x2: berth.zone_x2 ?? 0.9,
    y2: berth.zone_y2 ?? 0.9,
  })
  const originalUseZone = useRef(!!berth.use_detection_zone)

  // ── Draw canvas ───────────────────────────────────────────────────────────

  const drawCanvas = useCallback(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    ctx.clearRect(0, 0, canvas.width, canvas.height)

    if (imgRef.current && imgRef.current.complete) {
      ctx.drawImage(imgRef.current, 0, 0, canvas.width, canvas.height)
    } else {
      ctx.fillStyle = '#1f2937'
      ctx.fillRect(0, 0, canvas.width, canvas.height)
      ctx.fillStyle = '#6b7280'
      ctx.font = '14px sans-serif'
      ctx.textAlign = 'center'
      ctx.fillText('No frame available', canvas.width / 2, canvas.height / 2)
    }

    // Draw zone rectangle
    const x = zone.x1 * canvas.width
    const y = zone.y1 * canvas.height
    const w = (zone.x2 - zone.x1) * canvas.width
    const h = (zone.y2 - zone.y1) * canvas.height

    ctx.save()
    ctx.strokeStyle = useZone ? '#3b82f6' : '#6b7280'
    ctx.lineWidth = 2
    ctx.setLineDash([8, 4])
    ctx.strokeRect(x, y, w, h)
    ctx.restore()

    // Fill overlay
    ctx.save()
    ctx.fillStyle = useZone ? 'rgba(59,130,246,0.12)' : 'rgba(107,114,128,0.08)'
    ctx.fillRect(x, y, w, h)
    ctx.restore()

    // Label inside rect
    ctx.save()
    ctx.fillStyle = useZone ? '#93c5fd' : '#9ca3af'
    ctx.font = 'bold 11px sans-serif'
    ctx.textAlign = 'center'
    ctx.textBaseline = 'middle'
    ctx.fillText(`Berth ${berth.id}`, x + w / 2, y + h / 2)
    ctx.restore()
  }, [zone, useZone, berth.id])

  // Redraw whenever zone/frame/useZone changes
  useEffect(() => {
    drawCanvas()
  }, [drawCanvas])

  // ── Load frame ────────────────────────────────────────────────────────────

  const loadFrame = useCallback(async () => {
    if (!berth.pedestal_id) return
    setFrameLoading(true)
    try {
      const data = await getLatestFrame(berth.pedestal_id)
      setFrameB64(data.frame_b64)
      if (data.frame_b64) {
        const img = new Image()
        img.onload = () => {
          imgRef.current = img
          drawCanvas()
        }
        img.src = `data:image/jpeg;base64,${data.frame_b64}`
      }
    } catch {
      setFrameB64(null)
    } finally {
      setFrameLoading(false)
    }
  }, [berth.pedestal_id, drawCanvas])

  useEffect(() => {
    loadFrame()
  }, [loadFrame])

  // ── Canvas mouse handlers ─────────────────────────────────────────────────

  const getCanvasCoords = (e: React.MouseEvent<HTMLCanvasElement>): { x: number; y: number } => {
    const canvas = canvasRef.current!
    const rect = canvas.getBoundingClientRect()
    return {
      x: (e.clientX - rect.left) / rect.width,
      y: (e.clientY - rect.top) / rect.height,
    }
  }

  const handleMouseDown = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const coords = getCanvasCoords(e)
    setIsDragging(true)
    setDragStart(coords)
  }

  const handleMouseMove = (e: React.MouseEvent<HTMLCanvasElement>) => {
    if (!isDragging || !dragStart) return
    const coords = getCanvasCoords(e)
    const x1 = Math.min(dragStart.x, coords.x)
    const y1 = Math.min(dragStart.y, coords.y)
    const x2 = Math.max(dragStart.x, coords.x)
    const y2 = Math.max(dragStart.y, coords.y)
    setZone({ x1, y1, x2, y2 })
  }

  const handleMouseUp = (e: React.MouseEvent<HTMLCanvasElement>) => {
    if (!isDragging || !dragStart) return
    const coords = getCanvasCoords(e)
    const x1 = Math.min(dragStart.x, coords.x)
    const y1 = Math.min(dragStart.y, coords.y)
    const x2 = Math.max(dragStart.x, coords.x)
    const y2 = Math.max(dragStart.y, coords.y)
    // Ensure minimum zone size
    const finalZone = {
      x1: Math.max(0, x1),
      y1: Math.max(0, y1),
      x2: Math.min(1, x2 < x1 + 0.02 ? x1 + 0.02 : x2),
      y2: Math.min(1, y2 < y1 + 0.02 ? y1 + 0.02 : y2),
    }
    setZone(finalZone)
    setIsDragging(false)
    setDragStart(null)
  }

  const handleMouseLeave = () => {
    if (isDragging) {
      setIsDragging(false)
      setDragStart(null)
    }
  }

  // ── Save zone config ──────────────────────────────────────────────────────

  const handleSave = async () => {
    setSaving(true)
    setMsg(null)
    try {
      const parsedNum = berthNumber.trim() !== '' ? parseInt(berthNumber, 10) : undefined
      await updateBerthConfig(berth.id, {
        zone_x1: zone.x1,
        zone_y1: zone.y1,
        zone_x2: zone.x2,
        zone_y2: zone.y2,
        use_detection_zone: useZone ? 1 : 0,
        ...(parsedNum !== undefined && !isNaN(parsedNum) ? { berth_number: parsedNum } : {}),
      })
      setMsg({ ok: true, text: 'Sector configuration saved.' })
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Save failed.'
      setMsg({ ok: false, text: detail })
    } finally {
      setSaving(false)
    }
  }

  const handleReset = () => {
    setZone({ ...originalZone.current })
    setUseZone(originalUseZone.current)
    setMsg(null)
  }

  // ── Upload sample image ───────────────────────────────────────────────────

  const handleUploadSample = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    setUploading(true)
    setMsg(null)
    const fd = new FormData()
    fd.append('file', file)
    try {
      await uploadSampleEmbedding(berth.id, fd)
      setEmbeddingStatus({ exists: true, updatedAt: new Date().toISOString() })
      setMsg({ ok: true, text: 'Ship sample embedding saved.' })
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Upload failed.'
      setMsg({ ok: false, text: detail })
    } finally {
      setUploading(false)
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }

  const fmtPct = (v: number) => `${(v * 100).toFixed(1)}%`

  return (
    <div
      className="fixed inset-0 z-50 bg-black/80 flex items-center justify-center p-4"
      onClick={onClose}
    >
      <div
        className="bg-gray-900 rounded-2xl border border-gray-700 w-full max-w-4xl flex flex-col"
        style={{ maxHeight: '90vh' }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-800">
          <div>
            <h3 className="text-white font-bold text-lg">Configure Sectors — {berth.name}</h3>
            <p className="text-gray-400 text-sm">Draw a detection zone on the camera frame</p>
          </div>
          <button
            onClick={onClose}
            className="w-8 h-8 rounded-full bg-gray-700 text-white text-sm flex items-center justify-center hover:bg-gray-600"
          >
            ✕
          </button>
        </div>

        {/* Body */}
        <div className="flex flex-1 overflow-hidden">
          {/* Canvas — left 60% */}
          <div className="flex flex-col" style={{ width: '60%', minWidth: 0 }}>
            <div className="px-4 pt-4 flex items-center gap-2">
              <span className="text-xs text-gray-400">Camera frame</span>
              {frameLoading && <span className="text-xs text-blue-400 animate-pulse">Loading…</span>}
              {!frameB64 && !frameLoading && (
                <span className="text-xs text-amber-400">No buffered frame — analyze first</span>
              )}
              <button
                onClick={loadFrame}
                disabled={frameLoading || !berth.pedestal_id}
                className="ml-auto text-xs px-2 py-1 rounded bg-gray-700 hover:bg-gray-600 text-gray-300 disabled:opacity-50"
              >
                Refresh Frame
              </button>
            </div>
            <div className="p-4 flex-1 flex items-center justify-center">
              <canvas
                ref={canvasRef}
                width={560}
                height={380}
                className="rounded-lg border border-gray-700 cursor-crosshair w-full"
                style={{ maxHeight: 380 }}
                onMouseDown={handleMouseDown}
                onMouseMove={handleMouseMove}
                onMouseUp={handleMouseUp}
                onMouseLeave={handleMouseLeave}
              />
            </div>
            <p className="px-4 pb-3 text-xs text-gray-600">
              Drag to draw a new detection zone rectangle
            </p>
          </div>

          {/* Config panel — right 40% */}
          <div
            className="border-l border-gray-800 flex flex-col gap-4 px-5 py-5 overflow-y-auto"
            style={{ width: '40%' }}
          >
            {/* Berth info */}
            <div>
              <div className="text-xs text-gray-500 uppercase tracking-wide mb-1">Berth</div>
              <div className="text-white font-semibold">{berth.name}</div>
              <div className="text-gray-500 text-xs">ID {berth.id} · Pedestal {berth.pedestal_id ?? '—'}</div>
            </div>

            {/* Berth number */}
            <div>
              <label className="block text-xs text-gray-500 uppercase tracking-wide mb-1">
                Berth Number
              </label>
              <input
                type="number"
                min={1}
                value={berthNumber}
                onChange={(e) => setBerthNumber(e.target.value)}
                placeholder="e.g. 1"
                className="w-full bg-gray-800 border border-gray-700 text-white text-sm rounded-lg px-3 py-2 focus:outline-none focus:border-blue-500"
              />
              <p className="text-xs text-gray-600 mt-1">Displayed identifier for this sector (e.g. Berth 1).</p>
            </div>

            {/* Zone coordinates */}
            <div>
              <div className="text-xs text-gray-500 uppercase tracking-wide mb-2">Zone Coordinates</div>
              <div className="grid grid-cols-2 gap-2">
                {(['x1', 'y1', 'x2', 'y2'] as const).map((k) => (
                  <div key={k} className="bg-gray-800 rounded-lg px-3 py-2">
                    <div className="text-xs text-gray-500">{k.toUpperCase()}</div>
                    <div className="text-sm font-mono text-blue-300">{fmtPct(zone[k])}</div>
                  </div>
                ))}
              </div>
            </div>

            {/* Use Detection Zone toggle */}
            <div className="flex items-center gap-3">
              <label className="relative inline-flex items-center cursor-pointer">
                <input
                  type="checkbox"
                  checked={useZone}
                  onChange={(e) => setUseZone(e.target.checked)}
                  className="sr-only peer"
                />
                <div className="w-9 h-5 bg-gray-700 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-blue-600" />
              </label>
              <span className="text-sm text-gray-300">Enable Detection Zone</span>
            </div>

            {/* Ship sample */}
            <div>
              <div className="text-xs text-gray-500 uppercase tracking-wide mb-2">Ship Sample Image</div>
              {embeddingStatus.exists ? (
                <div className="text-xs text-green-400 mb-2">
                  Embedding stored
                  {embeddingStatus.updatedAt && (
                    <span className="text-gray-500 ml-1">
                      — {new Date(embeddingStatus.updatedAt).toLocaleDateString()}
                    </span>
                  )}
                </div>
              ) : (
                <div className="text-xs text-amber-400 mb-2">No sample uploaded</div>
              )}
              <input
                ref={fileInputRef}
                type="file"
                accept="image/jpeg,image/png,image/webp"
                className="hidden"
                onChange={handleUploadSample}
              />
              <button
                onClick={() => fileInputRef.current?.click()}
                disabled={uploading}
                className="w-full py-1.5 rounded-lg border border-blue-700/50 text-blue-400 hover:text-blue-300 text-xs font-medium disabled:opacity-50"
              >
                {uploading ? 'Uploading…' : 'Upload Ship Sample'}
              </button>
              <p className="text-xs text-gray-600 mt-1">
                Upload a photo of the expected ship — used for Re-ID matching.
              </p>
            </div>

            {/* Status message */}
            {msg && (
              <div
                className={`text-sm px-3 py-2 rounded-lg ${
                  msg.ok ? 'bg-green-900/30 text-green-400' : 'bg-red-900/30 text-red-400'
                }`}
              >
                {msg.text}
              </div>
            )}

            {/* Action buttons */}
            <div className="flex gap-2 pt-1 mt-auto">
              <button
                onClick={handleReset}
                className="flex-1 py-2 rounded-lg border border-gray-700 text-gray-400 text-sm hover:text-gray-200"
              >
                Reset
              </button>
              <button
                onClick={handleSave}
                disabled={saving}
                className="flex-1 py-2 rounded-lg bg-blue-700 hover:bg-blue-600 text-white text-sm font-medium disabled:opacity-50"
              >
                {saving ? 'Saving…' : 'Save Zone'}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
