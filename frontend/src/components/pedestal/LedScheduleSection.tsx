import { useEffect, useMemo, useState } from 'react'
import {
  getLedSchedule,
  upsertLedSchedule,
  deleteLedSchedule,
  testLedSchedule,
  type LedColor,
  type LedSchedule,
} from '../../api/ledSchedule'

// v3.10 — Per-pedestal daily LED on/off schedule UI.
// Sits between LED Control and the Reset section in the Control Center.
// Visible to admin only (the parent passes isAdmin=false to short-circuit).

interface Props {
  pedestalId: number
  isAdmin: boolean
  onFeedback: (key: string, type: 'success' | 'error', text: string) => void
}

const COLORS: Array<{ value: LedColor; label: string; swatch: string }> = [
  { value: 'green',  label: 'Green',  swatch: 'bg-green-500'  },
  { value: 'blue',   label: 'Blue',   swatch: 'bg-blue-500'   },
  { value: 'red',    label: 'Red',    swatch: 'bg-red-500'    },
  { value: 'yellow', label: 'Yellow', swatch: 'bg-yellow-400' },
]

const DAY_LABELS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

const HHMM_RE = /^([01]\d|2[0-3]):[0-5]\d$/

function parseDays(s: string | null | undefined): Set<number> {
  if (!s) return new Set([0, 1, 2, 3, 4, 5, 6])
  return new Set(
    s.split(',')
      .map((t) => Number(t.trim()))
      .filter((n) => Number.isInteger(n) && n >= 0 && n <= 6),
  )
}

function daysToString(days: Set<number>): string {
  return Array.from(days).sort((a, b) => a - b).join(',')
}

function nextFire(timeStr: string, days: Set<number>, now: Date): Date | null {
  if (!HHMM_RE.test(timeStr) || days.size === 0) return null
  const [h, m] = timeStr.split(':').map(Number)
  // Search up to 7 days ahead.
  for (let offset = 0; offset < 8; offset++) {
    const candidate = new Date(now)
    candidate.setDate(candidate.getDate() + offset)
    candidate.setHours(h, m, 0, 0)
    // Convert JS Sunday=0..Saturday=6 → Mon=0..Sun=6 to match backend.
    const jsDow = candidate.getDay()
    const backendDow = (jsDow + 6) % 7
    if (!days.has(backendDow)) continue
    if (candidate.getTime() > now.getTime()) return candidate
  }
  return null
}

function fmtNext(d: Date | null): string {
  if (!d) return '—'
  const now = new Date()
  const sameDay =
    d.getFullYear() === now.getFullYear() &&
    d.getMonth() === now.getMonth() &&
    d.getDate() === now.getDate()
  const time = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  if (sameDay) return `today at ${time}`
  const tomorrow = new Date(now)
  tomorrow.setDate(tomorrow.getDate() + 1)
  if (
    d.getFullYear() === tomorrow.getFullYear() &&
    d.getMonth() === tomorrow.getMonth() &&
    d.getDate() === tomorrow.getDate()
  ) {
    return `tomorrow at ${time}`
  }
  return `${d.toLocaleDateString()} at ${time}`
}

export default function LedScheduleSection({ pedestalId, isAdmin, onFeedback }: Props) {
  const [enabled, setEnabled] = useState(false)
  const [onTime, setOnTime] = useState('20:00')
  const [offTime, setOffTime] = useState('23:00')
  const [color, setColor] = useState<LedColor>('green')
  const [days, setDays] = useState<Set<number>>(new Set([0, 1, 2, 3, 4, 5, 6]))
  const [exists, setExists] = useState(false)
  const [busy, setBusy] = useState<string | null>(null)
  const [tick, setTick] = useState(0)   // forces re-render every minute for previews

  // Load current schedule on mount / pedestal change.
  useEffect(() => {
    let cancelled = false
    getLedSchedule(pedestalId)
      .then((s: LedSchedule) => {
        if (cancelled) return
        const hasSchedule = !!s.on_time && !!s.off_time
        setExists(hasSchedule)
        setEnabled(s.enabled)
        setOnTime(s.on_time ?? '20:00')
        setOffTime(s.off_time ?? '23:00')
        setColor((s.color as LedColor) ?? 'green')
        setDays(parseDays(s.days_of_week))
      })
      .catch(() => { /* fine — defaults stay */ })
    return () => { cancelled = true }
  }, [pedestalId])

  // D11 — re-render the Next On / Next Off preview every minute.
  useEffect(() => {
    const id = setInterval(() => setTick((n) => n + 1), 60_000)
    return () => clearInterval(id)
  }, [])

  const now = useMemo(() => { void tick; return new Date() }, [tick])
  const nextOn = useMemo(() => nextFire(onTime, days, now), [onTime, days, now])
  const nextOff = useMemo(() => nextFire(offTime, days, now), [offTime, days, now])

  const toggleDay = (n: number) => {
    setDays((prev) => {
      const next = new Set(prev)
      if (next.has(n)) next.delete(n); else next.add(n)
      return next
    })
  }

  const handleSave = async () => {
    if (!HHMM_RE.test(onTime)) { onFeedback('led-sched-on', 'error', 'On time must be HH:MM'); return }
    if (!HHMM_RE.test(offTime)) { onFeedback('led-sched-off', 'error', 'Off time must be HH:MM'); return }
    if (days.size === 0) { onFeedback('led-sched-days', 'error', 'Pick at least one day'); return }
    setBusy('save')
    try {
      await upsertLedSchedule(pedestalId, {
        enabled,
        on_time: onTime,
        off_time: offTime,
        color,
        days_of_week: daysToString(days),
      })
      setExists(true)
      onFeedback('led-sched-save', 'success', 'LED schedule saved')
    } catch (err) {
      const e = err as { response?: { data?: { detail?: string } } }
      onFeedback('led-sched-save', 'error', e?.response?.data?.detail ?? 'Failed to save schedule')
    } finally {
      setBusy(null)
    }
  }

  const handleTest = async () => {
    setBusy('test')
    try {
      await testLedSchedule(pedestalId)
      onFeedback('led-sched-test', 'success', 'LED test command sent')
    } catch (err) {
      const e = err as { response?: { status?: number; data?: { detail?: string } } }
      if (e?.response?.status === 404) {
        onFeedback('led-sched-test', 'error', 'Save the schedule first, then test')
      } else {
        onFeedback('led-sched-test', 'error', e?.response?.data?.detail ?? 'LED test failed')
      }
    } finally {
      setBusy(null)
    }
  }

  const handleDelete = async () => {
    if (!exists) return
    setBusy('delete')
    try {
      await deleteLedSchedule(pedestalId)
      setExists(false)
      setEnabled(false)
      onFeedback('led-sched-del', 'success', 'LED schedule removed')
    } catch (err) {
      const e = err as { response?: { data?: { detail?: string } } }
      onFeedback('led-sched-del', 'error', e?.response?.data?.detail ?? 'Failed to delete schedule')
    } finally {
      setBusy(null)
    }
  }

  if (!isAdmin) return null

  return (
    <div className="rounded-lg border border-gray-700 bg-gray-800/40 p-3 space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-base">⏰</span>
          <span className="text-sm font-medium text-white">LED Schedule</span>
        </div>
        <label className="flex items-center gap-2 text-xs text-gray-300 select-none cursor-pointer">
          <span>Auto LED Schedule</span>
          <input
            type="checkbox"
            checked={enabled}
            onChange={(e) => setEnabled(e.target.checked)}
            className="h-3 w-3 accent-green-500 cursor-pointer"
            aria-label="Enable LED schedule"
          />
        </label>
      </div>

      {/* Times */}
      <div className="grid grid-cols-2 gap-2">
        <label className="text-xs text-gray-400 space-y-1">
          On time
          <input
            type="time"
            value={onTime}
            onChange={(e) => setOnTime(e.target.value)}
            className="w-full bg-gray-900/60 border border-gray-700 rounded px-2 py-1 text-sm text-white font-mono"
          />
        </label>
        <label className="text-xs text-gray-400 space-y-1">
          Off time
          <input
            type="time"
            value={offTime}
            onChange={(e) => setOffTime(e.target.value)}
            className="w-full bg-gray-900/60 border border-gray-700 rounded px-2 py-1 text-sm text-white font-mono"
          />
        </label>
      </div>

      {/* Color picker */}
      <div className="space-y-1">
        <p className="text-xs text-gray-400">Color</p>
        <div className="flex gap-2 flex-wrap">
          {COLORS.map((c) => (
            <button
              key={c.value}
              type="button"
              onClick={() => setColor(c.value)}
              className={`flex items-center gap-1.5 px-2 py-1 rounded border text-xs ${
                color === c.value
                  ? 'border-white text-white bg-gray-900/80'
                  : 'border-gray-700 text-gray-400 hover:border-gray-500'
              }`}
              aria-pressed={color === c.value}
            >
              <span className={`w-2.5 h-2.5 rounded-full ${c.swatch}`} />
              {c.label}
            </button>
          ))}
        </div>
      </div>

      {/* Days of week */}
      <div className="space-y-1">
        <p className="text-xs text-gray-400">Days</p>
        <div className="flex gap-1 flex-wrap">
          {DAY_LABELS.map((label, idx) => {
            const checked = days.has(idx)
            return (
              <label
                key={label}
                className={`flex items-center gap-1 px-2 py-1 rounded border text-xs cursor-pointer ${
                  checked
                    ? 'border-green-500/60 bg-green-900/30 text-green-300'
                    : 'border-gray-700 text-gray-400 hover:border-gray-500'
                }`}
              >
                <input
                  type="checkbox"
                  checked={checked}
                  onChange={() => toggleDay(idx)}
                  className="h-3 w-3 accent-green-500 cursor-pointer"
                  aria-label={label}
                />
                {label}
              </label>
            )
          })}
        </div>
      </div>

      {/* Next fire preview */}
      <div className="text-[11px] text-gray-500 space-y-0.5 pt-1 border-t border-gray-700/50">
        <p>Next On: <span className="text-gray-300 font-mono">{enabled ? fmtNext(nextOn) : 'disabled'}</span></p>
        <p>Next Off: <span className="text-gray-300 font-mono">{enabled ? fmtNext(nextOff) : 'disabled'}</span></p>
      </div>

      {/* Buttons */}
      <div className="flex gap-1.5 pt-1">
        <button
          type="button"
          onClick={handleSave}
          disabled={busy !== null}
          className="flex-1 py-1 rounded text-xs font-medium border bg-green-800/60 hover:bg-green-700/60 text-green-200 border-green-700/50 disabled:opacity-40"
        >
          {busy === 'save' ? 'Saving…' : 'Save'}
        </button>
        <button
          type="button"
          onClick={handleTest}
          disabled={busy !== null}
          className="flex-1 py-1 rounded text-xs font-medium border bg-blue-900/40 hover:bg-blue-800/50 text-blue-200 border-blue-700/50 disabled:opacity-40"
        >
          {busy === 'test' ? 'Sending…' : 'Test LED'}
        </button>
        {exists && (
          <button
            type="button"
            onClick={handleDelete}
            disabled={busy !== null}
            className="flex-1 py-1 rounded text-xs font-medium border bg-red-900/40 hover:bg-red-800/50 text-red-200 border-red-700/50 disabled:opacity-40"
          >
            {busy === 'delete' ? 'Removing…' : 'Delete Schedule'}
          </button>
        )}
      </div>
    </div>
  )
}
