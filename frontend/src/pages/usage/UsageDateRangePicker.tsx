import { useEffect, useMemo, useRef, useState } from 'react'
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
  const rootRef = useRef<HTMLDivElement>(null)

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
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [])

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

      {open ? (
        <div className="absolute top-full left-0 z-50 mt-1 min-w-[20rem] max-w-lg rounded-xl border border-[#fde047]/60 bg-white p-4 shadow-xl ring-1 ring-[#fef9c3]">
          <div className="flex gap-2 mb-4">
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
            <div className="space-y-3">
              <p className="text-xs text-gray-500">
                Dates use your local timezone ({formatUsageTimezoneLabel(getUsageTimezone())}).
                Usage is stored by UTC day; filters include activity that happened on each
                selected local day.
              </p>
              <div>
                <p className="text-xs font-medium text-gray-500 mb-2">Days</p>
                <div className="flex flex-wrap gap-2">
                  {RELATIVE_DAYS.map((d) => (
                    <button
                      key={d}
                      type="button"
                      onClick={() => applyRelativeDays(d)}
                      className="min-w-[2.5rem] rounded-lg border border-gray-200 px-3 py-2 text-sm font-medium hover:border-[#facc15] hover:bg-[#fefce8]"
                    >
                      {d}
                    </button>
                  ))}
                </div>
              </div>
              <div>
                <p className="text-xs font-medium text-gray-500 mb-2">Weeks</p>
                <div className="flex flex-wrap gap-2">
                  {RELATIVE_WEEKS.map((w) => (
                    <button
                      key={w}
                      type="button"
                      onClick={() => applyRelativeDays(w * 7)}
                      className="min-w-[2.5rem] rounded-lg border border-gray-200 px-3 py-2 text-sm font-medium hover:border-[#facc15] hover:bg-[#fefce8]"
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
        </div>
      ) : null}
    </div>
  )
}

export function defaultUsageDateRange(): { start: string; end: string } {
  const today = toDateInput(new Date())
  return { start: today, end: today }
}
