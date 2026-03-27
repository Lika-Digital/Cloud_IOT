import { useEffect, useRef, useState } from 'react'
import { getCameraDetections } from '../../api'
import { getPedestalConfig } from '../../api/pedestalConfig'
import { useAuthStore } from '../../store/authStore'
import type { DetectionFrame } from '../../api'

interface CameraModalProps {
  pedestalId: number
  dataMode: 'synthetic' | 'real'
  cameraIp: string | null
  onClose: () => void
}

export default function CameraModal({ pedestalId, dataMode, cameraIp, onClose }: CameraModalProps) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const animRef = useRef<number>(0)
  const [frames, setFrames] = useState<DetectionFrame[]>([])
  const [loadingDetections, setLoadingDetections] = useState(true)
  const [detectionError, setDetectionError] = useState(false)
  const [currentDetections, setCurrentDetections] = useState<DetectionFrame | null>(null)

  // Live stream state
  const [streamUrl, setStreamUrl] = useState<string | null>(null)
  const [streamReachable, setStreamReachable] = useState(false)
  const [configLoading, setConfigLoading] = useState(true)
  const [liveImgSrc, setLiveImgSrc] = useState<string | null>(null)
  const liveIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const token = useAuthStore((s) => s.token)

  // Fetch pedestal config to get camera_stream_url / camera_reachable
  useEffect(() => {
    getPedestalConfig(pedestalId)
      .then((cfg) => {
        setStreamUrl(cfg.camera_stream_url ?? null)
        setStreamReachable(cfg.camera_reachable)
      })
      .catch(() => {
        setStreamUrl(null)
        setStreamReachable(false)
      })
      .finally(() => setConfigLoading(false))
  }, [pedestalId])

  // Start/stop live snapshot polling when stream is confirmed reachable
  const hasLiveStream = !configLoading && !!streamUrl && streamReachable

  useEffect(() => {
    if (!hasLiveStream) return

    const fetchSnapshot = async () => {
      try {
        const resp = await fetch(`/api/camera/${pedestalId}/snapshot`, {
          headers: { Authorization: `Bearer ${token}` },
        })
        if (!resp.ok) return
        const blob = await resp.blob()
        const url = URL.createObjectURL(blob)
        setLiveImgSrc((prev) => {
          if (prev) URL.revokeObjectURL(prev)
          return url
        })
      } catch {
        // ignore snapshot errors silently
      }
    }

    fetchSnapshot()
    liveIntervalRef.current = setInterval(fetchSnapshot, 2000)
    return () => {
      if (liveIntervalRef.current) clearInterval(liveIntervalRef.current)
      setLiveImgSrc((prev) => { if (prev) URL.revokeObjectURL(prev); return null })
    }
  }, [hasLiveStream, pedestalId, token])

  // Fetch YOLO detections for synthetic mode (only when no live stream)
  useEffect(() => {
    if (hasLiveStream || configLoading) return
    if (dataMode !== 'synthetic') {
      setLoadingDetections(false)
      return
    }
    getCameraDetections(pedestalId)
      .then((data) => {
        setFrames(data.frames)
        setLoadingDetections(false)
      })
      .catch(() => {
        setDetectionError(true)
        setLoadingDetections(false)
      })
  }, [pedestalId, dataMode, hasLiveStream, configLoading])

  // Animation loop — read video time, find matching detections, draw on canvas
  useEffect(() => {
    if (hasLiveStream || dataMode !== 'synthetic' || frames.length === 0) return
    const video = videoRef.current
    const canvas = canvasRef.current
    if (!video || !canvas) return

    const ctx = canvas.getContext('2d')!

    function draw() {
      if (!video || !canvas || !ctx) return

      if (canvas.width !== video.clientWidth || canvas.height !== video.clientHeight) {
        canvas.width = video.clientWidth
        canvas.height = video.clientHeight
      }

      const currentTime = video.currentTime
      const frame = frames.reduce((prev, curr) =>
        Math.abs(curr.time_s - currentTime) < Math.abs(prev.time_s - currentTime) ? curr : prev,
        frames[0]
      )

      setCurrentDetections(frame)
      ctx.clearRect(0, 0, canvas.width, canvas.height)

      const videoW = video.videoWidth || 1280
      const videoH = video.videoHeight || 720
      const scaleX = canvas.width / videoW
      const scaleY = canvas.height / videoH

      for (const det of frame.detections) {
        const x = det.x1 * scaleX
        const y = det.y1 * scaleY
        const w = (det.x2 - det.x1) * scaleX
        const h = (det.y2 - det.y1) * scaleY

        ctx.strokeStyle = '#22c55e'
        ctx.lineWidth = 2
        ctx.strokeRect(x, y, w, h)

        const label = `${det.label} ${(det.confidence * 100).toFixed(0)}%`
        ctx.font = 'bold 13px monospace'
        const textW = ctx.measureText(label).width
        ctx.fillStyle = 'rgba(0, 0, 0, 0.65)'
        ctx.fillRect(x, y - 20, textW + 8, 20)
        ctx.fillStyle = '#22c55e'
        ctx.fillText(label, x + 4, y - 5)
      }

      animRef.current = requestAnimationFrame(draw)
    }

    animRef.current = requestAnimationFrame(draw)
    return () => cancelAnimationFrame(animRef.current)
  }, [frames, dataMode, hasLiveStream])

  const shipDetected = (currentDetections?.detections.length ?? 0) > 0

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="relative bg-gray-900 rounded-2xl shadow-2xl border border-gray-700 overflow-hidden w-full max-w-3xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-3 border-b border-gray-700">
          <div className="flex items-center gap-3">
            <div className={`w-3 h-3 rounded-full ${hasLiveStream ? 'bg-green-400 animate-pulse' : 'bg-gray-500'}`} />
            <h3 className="font-semibold text-white">Live Camera</h3>
            {hasLiveStream ? (
              <span className="text-xs bg-green-900/50 text-green-300 px-2 py-0.5 rounded-full">
                {streamUrl}
              </span>
            ) : !configLoading && (
              <>
                {dataMode === 'synthetic' && (
                  <span className="text-xs bg-blue-900/50 text-blue-300 px-2 py-0.5 rounded-full">Synthetic · YOLO overlay</span>
                )}
                {dataMode === 'real' && cameraIp && (
                  <span className="text-xs bg-amber-900/50 text-amber-300 px-2 py-0.5 rounded-full">
                    {cameraIp}
                  </span>
                )}
                <span className="text-xs bg-gray-800 text-gray-400 px-2 py-0.5 rounded-full border border-gray-700">
                  No live stream available
                </span>
              </>
            )}
          </div>
          <div className="flex items-center gap-3">
            {!hasLiveStream && shipDetected && (
              <span className="flex items-center gap-1.5 text-sm text-green-400 font-medium">
                <span className="w-2 h-2 rounded-full bg-green-400 animate-pulse" />
                Ship detected
              </span>
            )}
            <button onClick={onClose} className="text-gray-400 hover:text-white text-xl leading-none">✕</button>
          </div>
        </div>

        {/* Video area */}
        <div className="relative bg-black" style={{ aspectRatio: '16/9' }}>
          {configLoading ? (
            <div className="flex items-center justify-center h-full text-gray-500 text-sm">
              <p>Loading camera info…</p>
            </div>
          ) : hasLiveStream ? (
            liveImgSrc ? (
              <img
                src={liveImgSrc}
                alt="Live IP camera"
                className="w-full h-full object-contain"
              />
            ) : (
              <div className="flex items-center justify-center h-full text-gray-500 text-sm">
                <p>Connecting to camera…</p>
              </div>
            )
          ) : dataMode === 'synthetic' ? (
            <>
              <video
                ref={videoRef}
                src="/Video.mp4"
                autoPlay
                muted
                loop
                className="w-full h-full object-contain"
                onLoadedMetadata={() => {}}
              />
              <canvas
                ref={canvasRef}
                className="absolute inset-0 w-full h-full pointer-events-none"
              />
              {loadingDetections && (
                <div className="absolute inset-0 flex items-center justify-center bg-black/50">
                  <p className="text-gray-300 text-sm">Loading YOLO detections…</p>
                </div>
              )}
              {detectionError && (
                <div className="absolute top-2 left-2 bg-amber-900/70 text-amber-300 text-xs px-3 py-1 rounded-lg">
                  Detections unavailable
                </div>
              )}
            </>
          ) : cameraIp ? (
            <img
              src={`/api/camera/${pedestalId}/stream`}
              alt="Live camera stream"
              className="w-full h-full object-contain"
            />
          ) : (
            <div className="flex items-center justify-center h-full text-gray-500 text-sm">
              <div className="text-center">
                <p className="text-4xl mb-3">📷</p>
                <p>No camera IP configured.</p>
                <p className="text-xs mt-1">Enter the camera IP in Settings.</p>
              </div>
            </div>
          )}
        </div>

        {/* Footer info */}
        <div className="px-5 py-3 bg-gray-900 border-t border-gray-800 flex items-center gap-4 text-xs text-gray-500">
          {hasLiveStream ? (
            <span>Live snapshot · refreshes every 2s</span>
          ) : dataMode === 'synthetic' ? (
            <>
              <span>YOLOv8n · COCO class: boat</span>
              <span>·</span>
              <span>Confidence threshold: 70%</span>
              {currentDetections && (
                <>
                  <span>·</span>
                  <span>t={currentDetections.time_s.toFixed(1)}s</span>
                  <span>·</span>
                  <span className={shipDetected ? 'text-green-400' : 'text-gray-500'}>
                    {currentDetections.detections.length} detection(s)
                  </span>
                </>
              )}
            </>
          ) : (
            <span>Real-time MJPEG stream from IP camera</span>
          )}
        </div>
      </div>
    </div>
  )
}
