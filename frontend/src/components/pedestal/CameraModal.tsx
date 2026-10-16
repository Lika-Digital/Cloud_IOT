import { useEffect, useRef, useState } from 'react'
import { getPedestalConfig } from '../../api/pedestalConfig'
import { useAuthStore } from '../../store/authStore'

interface CameraModalProps {
  pedestalId: number
  dataMode: 'synthetic' | 'real'
  cameraIp: string | null
  onClose: () => void
}

export default function CameraModal({ pedestalId, dataMode, cameraIp, onClose }: CameraModalProps) {
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
            <h3 className="font-semibold text-gray-100">Live Camera</h3>
            {hasLiveStream ? (
              <span className="text-xs bg-green-900/50 text-green-300 px-2 py-0.5 rounded-full">
                {streamUrl}
              </span>
            ) : !configLoading && (
              <>
                {dataMode === 'synthetic' && (
                  <span className="text-xs bg-blue-900/50 text-blue-300 px-2 py-0.5 rounded-full">Synthetic · demo video</span>
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
            <button onClick={onClose} className="text-gray-400 hover:text-gray-100 text-xl leading-none">✕</button>
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
            <video
              src="/Video.mp4"
              autoPlay
              muted
              loop
              className="w-full h-full object-contain"
            />
          ) : cameraIp ? (
            // 2026-10-16 (§16.3c): this was an <img> on /api/camera/{id}/stream, which cannot send
            // a login — and the route now demands one. The live view is the snapshot poll above.
            <div className="flex items-center justify-center h-full text-gray-500 text-sm">
              <p>No live stream available.</p>
            </div>
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
            // D15 (2026-10-14): this used to overlay boxes from GET /api/camera/{id}/detections,
            // a route that never existed — it sat on "Loading YOLO detections…" for ever. No
            // detection runs on this demo video; person detection is the guard's.
            <span>Demo video · no detection runs in synthetic mode</span>
          ) : (
            <span>Real-time MJPEG stream from IP camera</span>
          )}
        </div>
      </div>
    </div>
  )
}
