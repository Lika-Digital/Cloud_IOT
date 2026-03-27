import { useState, useRef, useEffect } from 'react'

/**
 * Small "?" icon that shows a tooltip on hover/click.
 * The tooltip auto-positions left or right based on available space.
 */
export default function HelpBubble({ text }: { text: string }) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  // Close on outside click
  useEffect(() => {
    if (!open) return
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  return (
    <div ref={ref} className="relative inline-flex items-center">
      <button
        type="button"
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={() => setOpen(false)}
        onClick={() => setOpen((v) => !v)}
        className="w-4 h-4 rounded-full bg-gray-700 hover:bg-gray-600 text-gray-400 hover:text-white text-[10px] font-bold flex items-center justify-center flex-shrink-0 transition-colors"
        aria-label="Help"
      >
        ?
      </button>

      {open && (
        <div className="absolute z-50 bottom-full left-1/2 -translate-x-1/2 mb-2 w-72 max-w-xs">
          <div className="bg-gray-800 border border-gray-600 text-gray-200 text-xs rounded-lg px-3 py-2.5 shadow-xl leading-relaxed whitespace-pre-wrap">
            {text}
          </div>
          {/* Arrow */}
          <div className="flex justify-center">
            <div className="w-2 h-2 bg-gray-800 border-b border-r border-gray-600 rotate-45 -mt-1" />
          </div>
        </div>
      )}
    </div>
  )
}
