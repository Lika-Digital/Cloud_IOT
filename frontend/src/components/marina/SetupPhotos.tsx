import { useCallback, useEffect, useRef, useState } from 'react'
import { deleteReferenceImage, getReferenceImages, uploadReferenceImages } from '../../api/berths'
import { TONE } from './Status'

/**
 * Wizard step 3, one berth: its vessel reference photos (block 4, 2026-10-15).
 *
 * There is no separate "matching on/off" switch, because the system has none: the matcher
 * compares the boat against these photos, so a berth WITH a photo is checked and a berth
 * without one is not. The screen says exactly that rather than offer a checkbox that would
 * store nothing (`vessel_match_configured` is read from the same files, routers/marina.py).
 *
 * A photo is stored the moment it is added; the wizard's Save is for the socket mapping only.
 */
type Load = { kind: 'loading' } | { kind: 'ready'; images: string[] } | { kind: 'error' }

export function SetupPhotos({ berthId, label, socket }: {
  berthId: number
  /** "Berth 3" */
  label: string
  /** "Q3" / "No socket" — the mapping as chosen in step 2, not yet necessarily saved */
  socket: string
}) {
  const [state, setState] = useState<Load>({ kind: 'loading' })
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)
  const input = useRef<HTMLInputElement>(null)

  const load = useCallback(async () => {
    try {
      setState({ kind: 'ready', images: await getReferenceImages(berthId) })
    } catch {
      setState({ kind: 'error' })
    }
  }, [berthId])

  useEffect(() => { load() }, [load])

  const act = async (what: () => Promise<unknown>, failed: string) => {
    setBusy(true)
    setProblem(null)
    try {
      await what()
      await load()
    } catch (e) {
      const err = e as { response?: { data?: { detail?: string } } }
      setProblem(err?.response?.data?.detail ?? failed)
    } finally {
      setBusy(false)
      if (input.current) input.current.value = ''
    }
  }

  const add = (files: FileList | null) => {
    if (!files || files.length === 0) return
    const fd = new FormData()
    Array.from(files).forEach((f) => fd.append('files', f))
    act(() => uploadReferenceImages(berthId, fd), 'The photo could not be stored.')
  }

  const images = state.kind === 'ready' ? state.images : []
  return (
    <li className="py-2" data-testid={`setup-photos-${berthId}`}>
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="text-sm text-gray-100 w-24">{label}</span>
        <span className="text-sm text-gray-300 w-20 font-mono">{socket}</span>
        <span className="text-xs text-gray-400" data-testid="setup-match">
          {state.kind === 'loading' && 'Loading photos…'}
          {state.kind === 'error' && <span className={TONE.noticeText}>Photos could not be loaded.</span>}
          {state.kind === 'ready' && (images.length > 0
            ? `${images.length} photo(s): the boat here is checked against them`
            : 'No photo: the boat here is not checked')}
        </span>
        <label className={`text-xs px-2 py-1 rounded border border-gray-600 text-gray-200 hover:bg-gray-700/60 cursor-pointer ml-auto ${busy ? 'opacity-40 pointer-events-none' : ''}`}>
          {busy ? 'Working…' : 'Add photo'}
          <input ref={input} type="file" accept="image/jpeg,image/png,image/webp" multiple
            className="sr-only" disabled={busy} aria-label={`Add a reference photo for ${label}`}
            onChange={(e) => add(e.target.files)} />
        </label>
      </div>
      {images.length > 0 && (
        <ul className="mt-1 ml-0 sm:ml-24 flex flex-col gap-0.5">
          {images.map((name) => (
            <li key={name} className="flex items-center gap-2 text-xs text-gray-400">
              <span className="font-mono truncate">{name}</span>
              <button type="button" disabled={busy}
                onClick={() => act(() => deleteReferenceImage(berthId, name), 'The photo could not be removed.')}
                className="text-blue-300 hover:underline disabled:opacity-40 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-400">
                Remove
              </button>
            </li>
          ))}
        </ul>
      )}
      {problem && <p className={`text-xs mt-1 ${TONE.noticeText}`} role="alert">{problem}</p>}
    </li>
  )
}
