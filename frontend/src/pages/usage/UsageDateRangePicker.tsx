import { useEffect, useLayoutEffect, useMemo, useRef, useState, type CSSProperties } from 'react'
import { createPortal } from 'react-dom'
import { Calendar } from 'lucide-react'
import { usageTheme } from './usageTheme'
import { getUsageTimezone, formatUsageTimezoneLabel } from './usageTimezone'

type Mode = 'relative' | 'absolute'

type UsageDateRangePickerProps = {
  start: string
  end: string
  onApply: (start: string, end: string) => void
  maxHistoryDays?: number | null
}

function toDateInput(d: Date): string {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

function formatDisplay(start: string, end: string): string {
  if (start === end) return start
  return `${start} → ${end}`
}

export function rangeForDays(days: number): { start: string; end: string } {
  const end = new Date()
  const start = new Date()
  start.setDate(start.getDate() - (days - 1))
  return { start: toDateInput(start), end: toDateInput(end) }
}

export function isRangeWithinMaxDays(start: string, end: string, maxDays: number): boolean {
  const r = rangeForDays(maxDays)
  return start >= r.start && end <= r.end
}

const QUICK_RANGES = [
  { label: '1d', days: 1 },
  { label: '7d', days: 7 },
  { label: '30d', days: 30 },
  { label: '90d', days: 90 },
] as const

const RELATIVE_DAYS = [1, 2, 3, 4, 5, 6]
const RELATIVE_WEEKS = [1, 2, 3, 4]

export default function UsageDateRangePicker({
  start,
  end,
  onApply,
  maxHistoryDays = null,
}: UsageDateRangePickerProps) {
  const [open, setOpen] = useState(false)
  const [mode, setMode] = useState<Mode>('relative')
  const [draftStart, setDraftStart] = useState(start)
  const [draftEnd, setDraftEnd] = useState(end)
  const [relDays, setRelDays] = useState(1)
  const [panelStyle, setPanelStyle] = useState<CSSProperties | null>(null)
  const rootRef = useRef<HTMLDivElement>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const panelRef = useRef<HTMLDivElement>(null)

  const quickRanges = useMemo(() => {
    if (!maxHistoryDays) return QUICK_RANGES
    return QUICK_RANGES.filter((q) => q.days <= maxHistoryDays)
  }, [maxHistoryDays])

  const minStartDate = useMemo(() => {
    if (!maxHistoryDays) return null
    return rangeForDays(maxHistoryDays).start
  }, [maxHistoryDays])

  const maxRelDays = maxHistoryDays ?? 365

  const activeQuick = useMemo(() => {
    for (const q of quickRanges) {
      const r = rangeForDays(q.days)
      if (r.start === start && r.end === end) return q.label
    }
    return null
  }, [start, end, quickRanges])

  useEffect(() => {
    if (open) {
      setDraftStart(start)
      setDraftEnd(end)
    }
  }, [open, start, end])

  useEffect(() => {
    const onDoc = (e: MouseEvent) => {
      const target = e.target as Node
      if (rootRef.current?.contains(target) || panelRef.current?.contains(target)) return
      setOpen(false)
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onDoc)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDoc)
      document.removeEventListener('keydown', onKey)
    }
  }, [])

  useLayoutEffect(() => {
    if (!open) {
      setPanelStyle(null)
      return
    }

    let frame = 0
    const place = () => {
      cancelAnimationFrame(frame)
      frame = requestAnimationFrame(() => placeNow())
    }
    const placeNow = () => {
      const anchor = triggerRef.current
      const panel = panelRef.current
      if (!anchor || !panel) return
      const rect = anchor.getBoundingClientRect()
      const margin = 8
      const width = Math.min(panel.offsetWidth || 352, window.innerWidth - margin * 2)
      const height = panel.scrollHeight || panel.offsetHeight
      const spaceBelow = window.innerHeight - rect.bottom - margin
      const spaceAbove = rect.top - margin
      const openUp = spaceBelow < height + 4 && spaceAbove > spaceBelow
      const available = Math.max(160, openUp ? spaceAbove - 4 : spaceBelow - 4)
      const maxHeight = Math.min(height, available)
      let left = rect.left
      if (left + width > window.innerWidth - margin) {
        left = window.innerWidth - margin - width
      }
      left = Math.max(margin, left)
      const top = openUp
        ? Math.max(margin, rect.top - maxHeight - 4)
        : Math.min(rect.bottom + 4, window.innerHeight - margin - maxHeight)
      setPanelStyle({
        position: 'fixed',
        top,
        left,
        width,
        maxHeight,
        zIndex: 80,
        overflowY: height > maxHeight ? 'auto' : 'visible',
      })
    }

    place()
    window.addEventListener('resize', place)
    window.addEventListener('scroll', place, true)
    return () => {
      cancelAnimationFrame(frame)
      window.removeEventListener('resize', place)
      window.removeEventListener('scroll', place, true)
    }
  }, [open, mode])

  const applyRelativeDays = (days: number) => {
    const r = rangeForDays(days)
    onApply(r.start, r.end)
    setOpen(false)
  }

  const applyAbsolute = () => {
    if (!draftStart || !draftEnd) return
    if (draftEnd < draftStart) return
    onApply(draftStart, draftEnd)
    setOpen(false)
  }

  const pillClass = (active: boolean) =>
    `rounded-md px-2.5 py-1 text-xs font-medium transition-colors border ${
      active ? usageTheme.pillActive : usageTheme.pillInactive
    }`

  return (
    <div ref={rootRef} className="relative flex flex-wrap items-center gap-2 flex-1 min-w-0">
      <div className="flex items-center gap-0.5 rounded-lg border border-[#fde047]/50 bg-white/80 p-0.5">
        {quickRanges.map((q) => (
          <button
            key={q.label}
            type="button"
            onClick={() => {
              const r = rangeForDays(q.days)
              onApply(r.start, r.end)
            }}
            className={pillClass(activeQuick === q.label)}
          >
            {q.label}
          </button>
        ))}
        <button
          ref={triggerRef}
          type="button"
          onClick={() => setOpen((v) => !v)}
          className={pillClass(open || !activeQuick)}
        >
          <Calendar className="h-3.5 w-3.5 inline mr-1" />
          Custom
        </button>
      </div>

      <span className="text-xs text-gray-500 truncate hidden md:inline">
        {formatDisplay(start, end)}
        <span className="text-gray-400">
          {' '}
          · {formatUsageTimezoneLabel(getUsageTimezone())}
        </span>
      </span>

      {open && typeof document !== 'undefined'
        ? createPortal(
        <div
          ref={panelRef}
          style={
            panelStyle ?? {
              position: 'fixed',
              top: 0,
              left: 0,
              width: 352,
              visibility: 'hidden',
            }
          }
          className="w-[22rem] max-w-[calc(100vw-1rem)] rounded-xl border border-[#fde047]/60 bg-white p-3.5 shadow-xl ring-1 ring-[#fef9c3]"
        >
          <div className="flex gap-2 mb-3">
            <button
              type="button"
              onClick={() => setMode('absolute')}
              className={`rounded-full px-4 py-1.5 text-sm font-medium border ${
                mode === 'absolute' ? usageTheme.pillActive : usageTheme.pillMuted
              }`}
            >
              Absolute
            </button>
            <button
              type="button"
              onClick={() => setMode('relative')}
              className={`rounded-full px-4 py-1.5 text-sm font-medium border ${
                mode === 'relative' ? usageTheme.pillActive : usageTheme.pillMuted
              }`}
            >
              Relative
            </button>
          </div>

          {mode === 'relative' ? (
            <div className="space-y-2.5">
              <p className="text-xs text-gray-500">
                Local timezone ({formatUsageTimezoneLabel(getUsageTimezone())}). Each day includes
                usage stored on that UTC day.
              </p>
              <div>
                <p className="text-xs font-medium text-gray-500 mb-1.5">Days</p>
                <div className="flex flex-wrap gap-1.5">
                  {RELATIVE_DAYS.map((d) => (
                    <button
                      key={d}
                      type="button"
                      onClick={() => applyRelativeDays(d)}
                      className="min-w-[2.25rem] rounded-lg border border-gray-200 px-2.5 py-1.5 text-sm font-medium hover:border-[#facc15] hover:bg-[#fefce8]"
                    >
                      {d}
                    </button>
                  ))}
                </div>
              </div>
              <div>
                <p className="text-xs font-medium text-gray-500 mb-1.5">Weeks</p>
                <div className="flex flex-wrap gap-1.5">
                  {RELATIVE_WEEKS.map((w) => (
                    <button
                      key={w}
                      type="button"
                      onClick={() => applyRelativeDays(w * 7)}
                      className="min-w-[2.25rem] rounded-lg border border-gray-200 px-2.5 py-1.5 text-sm font-medium hover:border-[#facc15] hover:bg-[#fefce8]"
                    >
                      {w}
                    </button>
                  ))}
                </div>
              </div>
              <div className="flex items-end gap-3 pt-2 border-t border-gray-100">
                <label className="flex flex-col gap-1">
                  <span className="text-xs font-medium text-gray-500">Custom days</span>
                  <input
                    type="number"
                    min={1}
                    max={maxRelDays}
                    value={relDays}
                    onChange={(e) =>
                      setRelDays(Math.min(maxRelDays, Math.max(1, Number(e.target.value) || 1)))
                    }
                    className="w-24 rounded-lg border border-gray-200 px-3 py-2 text-sm"
                  />
                </label>
                <button type="button" onClick={() => applyRelativeDays(relDays)} className={usageTheme.applyBtn}>
                  Apply
                </button>
              </div>
            </div>
          ) : (
            <div className="space-y-3">
              <div className="grid grid-cols-2 gap-3">
                <label className="flex flex-col gap-1">
                  <span className="text-xs font-medium text-gray-500">Start date</span>
                  <input
                    type="date"
                    value={draftStart}
                    min={minStartDate ?? undefined}
                    onChange={(e) => setDraftStart(e.target.value)}
                    className="rounded-lg border border-gray-200 px-3 py-2 text-sm"
                  />
                </label>
                <label className="flex flex-col gap-1">
                  <span className="text-xs font-medium text-gray-500">End date</span>
                  <input
                    type="date"
                    value={draftEnd}
                    onChange={(e) => setDraftEnd(e.target.value)}
                    className="rounded-lg border border-gray-200 px-3 py-2 text-sm"
                  />
                </label>
              </div>
              <div className="flex justify-end gap-2 pt-2 border-t border-gray-100">
                <button
                  type="button"
                  onClick={() => setOpen(false)}
                  className="px-3 py-1.5 text-sm font-medium text-gray-600"
                >
                  Cancel
                </button>
                <button type="button" onClick={applyAbsolute} className={usageTheme.applyBtn}>
                  Apply
                </button>
              </div>
            </div>
          )}
        </div>,
            document.body,
          )
        : null}
    </div>
  )
}

export function defaultUsageDateRange(): { start: string; end: string } {
  return rangeForDays(7)
}
