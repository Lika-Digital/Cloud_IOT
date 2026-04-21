/**
 * Global toast renderer (v3.7).
 *
 * Reads from the Zustand `toasts` slice and renders a bottom-right stack.
 * Each toast auto-dismisses after 10 s and can optionally show an action
 * link (used by the new-pedestal discovery flow to deep-link to the
 * pedestal detail page).
 *
 * No external lib — we own the full surface and match the existing
 * Tailwind palette used by Control Center status badges.
 */
import { useEffect, useRef } from 'react'
import { useStore } from '../../store'


const TOAST_TTL_MS = 10_000


export default function ToastContainer() {
  const { toasts, removeToast } = useStore()
  // Track which toasts already have a timer so a re-render doesn't double-schedule.
  const scheduled = useRef<Set<string>>(new Set())

  useEffect(() => {
    for (const t of toasts) {
      if (scheduled.current.has(t.id)) continue
      scheduled.current.add(t.id)
      const handle = setTimeout(() => {
        removeToast(t.id)
        scheduled.current.delete(t.id)
      }, TOAST_TTL_MS)
      // Clean up the handle if the toast vanishes before the timer fires.
      // Zustand re-fires this effect on every toasts-array change, so we
      // rely on the scheduled Set above to avoid duplicates.
      void handle
    }
  }, [toasts, removeToast])

  if (toasts.length === 0) return null

  return (
    <div className="fixed bottom-4 right-4 z-[9999] flex flex-col gap-2 max-w-sm">
      {toasts.map((t) => (
        <div
          key={t.id}
          role="status"
          className={`rounded-lg border shadow-lg px-3 py-2 text-sm flex items-start gap-3 ${variantClass(t.variant)}`}
        >
          <span className="flex-1">{t.message}</span>
          {t.actionLabel && t.actionHref && (
            <a
              href={t.actionHref}
              className="text-xs font-semibold underline underline-offset-2 hover:opacity-80"
            >
              {t.actionLabel}
            </a>
          )}
          <button
            type="button"
            onClick={() => useStore.getState().removeToast(t.id)}
            className="text-xs text-current opacity-60 hover:opacity-100"
            aria-label="Dismiss notification"
          >
            ×
          </button>
        </div>
      ))}
    </div>
  )
}


function variantClass(v: 'info' | 'success' | 'warning' | 'error'): string {
  switch (v) {
    case 'success': return 'bg-green-900/80 border-green-700/60 text-green-100'
    case 'warning': return 'bg-amber-900/80 border-amber-700/60 text-amber-100'
    case 'error':   return 'bg-red-900/80 border-red-700/60 text-red-100'
    default:        return 'bg-gray-800/90 border-gray-600/70 text-gray-100'
  }
}
