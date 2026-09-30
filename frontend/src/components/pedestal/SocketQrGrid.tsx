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


// v3.43 — QR addresses the same SIX outlets as NFC: four electricity sockets and two
// water outlets. This was Q1-Q4, which left a water outlet with no printable code —
// a difference nobody can explain to a customer standing in front of one.
//
// A static list, unlike the NFC provisioning table which reads the cabinet's own
// enumeration. That is deliberate: these are PRINTED codes, and their URLs must stay
// valid whether or not the cabinet has published its hardware config since the last
// restart. A sticker outlives the process that generated it.
//
// The backend refuses to generate a water code while the site is in direct-client mode
// with an app that cannot read one (409), so a premature water tile shows its error
// rather than producing a sticker that misleads on the pontoon.
export const QR_OUTLETS = [
  { name: 'Q1', kind: 'socket' },
  { name: 'Q2', kind: 'socket' },
  { name: 'Q3', kind: 'socket' },
  { name: 'Q4', kind: 'socket' },
  { name: 'V1', kind: 'valve' },
  { name: 'V2', kind: 'valve' },
] as const

/** @deprecated v3.43 — electricity only; use QR_OUTLETS. */
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
    <div className="space-y-2">
      {([
        ['Electricity', QR_OUTLETS.filter((o) => o.kind === 'socket')],
        ['Water', QR_OUTLETS.filter((o) => o.kind === 'valve')],
      ] as const).map(([label, group]) => (
        <div key={label}>
          <p className="text-[10px] uppercase tracking-wide text-gray-500 mb-1">{label}</p>
          <div className="grid grid-cols-2 gap-2">
            {group.map((o) => (
              <SocketQrCell
                key={o.name}
                cabinetId={cabinetId}
                pedestalId={pedestalId}
                socketName={o.name}
                reloadNonce={reloadNonce}
                onCopied={onCopied}
                onCopyFailed={onCopyFailed}
              />
            ))}
          </div>
        </div>
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
  const [errDetail, setErrDetail] = useState<string | null>(null)
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
      .catch((e: any) => {
        if (cancelled) return
        // A 409 is the app-version gate, not a broken endpoint: this site runs without an
        // ERP and its app cannot yet read a water outlet, so generating a printable code
        // would put a misleading sticker on the pontoon. Said plainly, because 'Failed'
        // on two tiles out of six reads as an outage.
        setErr(e?.response?.status === 409 ? 'Not yet' : 'Failed')
        setErrDetail(e?.response?.data?.detail ?? null)
      })
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
          <span
            className={`text-xs px-1 text-center ${err === 'Not yet' ? 'text-yellow-600' : 'text-red-500'}`}
            title={errDetail ?? undefined}
          >
            {err}
          </span>
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
