/**
 * Shared QR grid + cell (v3.7).
 *
 * Used by:
 *   - PedestalControlCenter → collapsible "QR Codes" section
 *   - PedestalCard dashboard modal → quick-access from the fleet grid
 *
 * Each cell fetches the PNG + encoded URL from the v3.6 endpoint
 * `GET /api/mobile/socket/{pedestal_id}/{socket_name}/qr`. Bump
 * `reloadNonce` (prop) to force a refetch after Regenerate.
 */
import { useEffect, useRef, useState } from 'react'
import { getSocketQrBlob } from '../../api'


export const QR_SOCKETS = ['Q1', 'Q2', 'Q3', 'Q4'] as const


export function SocketQrGrid({
  cabinetId,
  pedestalId,
  reloadNonce,
  onCopied,
  onCopyFailed,
}: {
  cabinetId: string
  pedestalId: number
  reloadNonce: number
  onCopied?: (socketName: string) => void
  onCopyFailed?: (socketName: string) => void
}) {
  return (
    <div className="grid grid-cols-2 gap-2">
      {QR_SOCKETS.map((sid) => (
        <SocketQrCell
          key={sid}
          cabinetId={cabinetId}
          pedestalId={pedestalId}
          socketName={sid}
          reloadNonce={reloadNonce}
          onCopied={onCopied}
          onCopyFailed={onCopyFailed}
        />
      ))}
    </div>
  )
}


function SocketQrCell({
  cabinetId,
  pedestalId,
  socketName,
  reloadNonce,
  onCopied,
  onCopyFailed,
}: {
  cabinetId: string
  pedestalId: number
  socketName: string
  reloadNonce: number
  onCopied?: (socketName: string) => void
  onCopyFailed?: (socketName: string) => void
}) {
  const [blobUrl, setBlobUrl] = useState<string | null>(null)
  const [qrUrl, setQrUrl] = useState<string>('')
  const [err, setErr] = useState<string | null>(null)
  const objectUrlRef = useRef<string | null>(null)

  useEffect(() => {
    let cancelled = false
    getSocketQrBlob(pedestalId, socketName)
      .then(({ blob, url }) => {
        if (cancelled) return
        const u = URL.createObjectURL(blob)
        objectUrlRef.current = u
        setBlobUrl(u)
        setQrUrl(url)
      })
      .catch(() => setErr('Failed'))
    return () => {
      cancelled = true
      if (objectUrlRef.current) {
        URL.revokeObjectURL(objectUrlRef.current)
        objectUrlRef.current = null
      }
    }
  }, [pedestalId, socketName, reloadNonce])

  const handleDownload = () => {
    if (!blobUrl) return
    const a = document.createElement('a')
    a.href = blobUrl
    a.download = `${cabinetId}_${socketName}.png`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
  }

  const handleCopy = async () => {
    if (!qrUrl) return
    try {
      await navigator.clipboard.writeText(qrUrl)
      onCopied?.(socketName)
    } catch {
      onCopyFailed?.(socketName)
    }
  }

  return (
    <div className="rounded border border-gray-700 bg-gray-900/50 p-2 flex flex-col items-center gap-1.5">
      <div className="bg-white rounded w-full aspect-square flex items-center justify-center overflow-hidden">
        {err ? (
          <span className="text-xs text-red-500">{err}</span>
        ) : blobUrl ? (
          <img src={blobUrl} alt={`QR for ${socketName}`} className="max-w-full max-h-full" />
        ) : (
          <span className="text-xs text-gray-500">Loading…</span>
        )}
      </div>
      <span className="text-xs font-mono text-gray-300">{socketName}</span>
      <div className="flex gap-1 w-full">
        <button
          type="button"
          onClick={handleDownload}
          disabled={!blobUrl}
          className="flex-1 text-[10px] py-1 rounded border border-gray-600 text-gray-300 hover:bg-gray-700/60 disabled:opacity-40"
        >
          Download
        </button>
        <button
          type="button"
          onClick={handleCopy}
          disabled={!qrUrl}
          className="flex-1 text-[10px] py-1 rounded border border-gray-600 text-gray-300 hover:bg-gray-700/60 disabled:opacity-40"
        >
          Copy URL
        </button>
      </div>
    </div>
  )
}
