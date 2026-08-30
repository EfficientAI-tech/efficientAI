import { useEffect, useMemo, useRef, useState } from 'react'
import { Calendar } from 'lucide-react'
import { formatResultsDateRange, rangeForDays, toDateInput } from './resultsDateRange'
import { formatUsageTimezoneLabel, getUsageTimezone } from '../../usage/usageTimezone'

type Mode = 'relative' | 'absolute'

type ResultsDateRangePickerProps = {
  start: string | null
  end: string | null
  onApply: (start: string | null, end: string | null) => void
}

const QUICK_RANGES = [
  { label: '1d', days: 1 },
  { label: '7d', days: 7 },
  { label: '30d', days: 30 },
  { label: '90d', days: 90 },
] as const

export default function ResultsDateRangePicker({ start, end, onApply }: ResultsDateRangePickerProps) {
  const [open, setOpen] = useState(false)
  const [mode, setMode] = useState<Mode>('absolute')
  const [draftStart, setDraftStart] = useState(start ?? '')
  const [draftEnd, setDraftEnd] = useState(end ?? '')
  const rootRef = useRef<HTMLDivElement>(null)

  const hasRange = Boolean(start && end)
  const activeQuick = useMemo(() => {
    if (!start || !end) return null
    for (const q of QUICK_RANGES) {
      const r = rangeForDays(q.days)
      if (r.start === start && r.end === end) return q.label
    }
    return null
  }, [start, end])

  useEffect(() => {
    if (open) {
      setDraftStart(start ?? toDateInput(new Date()))
      setDraftEnd(end ?? toDateInput(new Date()))
    }
  }, [open, start, end])

  useEffect(() => {
    const onDoc = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [])

  const pillClass = (active: boolean) =>
    `rounded-md px-2.5 py-1 text-xs font-medium transition-colors border ${
      active
        ? 'border-primary-300 bg-primary-50 text-primary-800'
        : 'border-gray-200 bg-white text-gray-600 hover:bg-gray-50'
    }`

  const applyAbsolute = () => {
    if (!draftStart || !draftEnd || draftEnd < draftStart) return
    onApply(draftStart, draftEnd)
    setOpen(false)
  }

  return (
    <div ref={rootRef} className="relative flex flex-wrap items-center gap-2 min-w-0">
      <div className="flex items-center gap-0.5 rounded-lg border border-gray-200 bg-white p-0.5">
        <button type="button" onClick={() => onApply(null, null)} className={pillClass(!hasRange)}>
          All time
        </button>
        {QUICK_RANGES.map((q) => (
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
        <button type="button" onClick={() => setOpen((value) => !value)} className={pillClass(open || (hasRange && !activeQuick))}>
          <Calendar className="h-3.5 w-3.5 inline mr-1" />
          Custom
        </button>
      </div>

      {hasRange ? (
        <span className="text-xs text-gray-500 truncate hidden md:inline">
          {formatResultsDateRange(start!, end!)}
          <span className="text-gray-400"> · {formatUsageTimezoneLabel(getUsageTimezone())}</span>
        </span>
      ) : (
        <span className="text-xs text-gray-500 hidden md:inline">Showing all runs by call time</span>
      )}

      {open ? (
        <div className="absolute top-full left-0 z-50 mt-1 min-w-[20rem] max-w-lg rounded-xl border border-gray-200 bg-white p-4 shadow-xl">
          <div className="flex gap-2 mb-4">
            <button type="button" onClick={() => setMode('absolute')} className={pillClass(mode === 'absolute')}>
              Absolute
            </button>
            <button type="button" onClick={() => setMode('relative')} className={pillClass(mode === 'relative')}>
              Relative
            </button>
          </div>

          {mode === 'relative' ? (
            <div className="flex flex-wrap gap-2">
              {[1, 7, 14, 30, 60, 90].map((days) => (
                <button
                  key={days}
                  type="button"
                  onClick={() => {
                    const r = rangeForDays(days)
                    onApply(r.start, r.end)
                    setOpen(false)
                  }}
                  className="rounded-lg border border-gray-200 px-3 py-2 text-sm font-medium hover:border-primary-300 hover:bg-primary-50"
                >
                  Last {days}d
                </button>
              ))}
            </div>
          ) : (
            <div className="space-y-3">
              <div className="grid grid-cols-2 gap-3">
                <label className="flex flex-col gap-1">
                  <span className="text-xs font-medium text-gray-500">Start date</span>
                  <input
                    type="date"
                    value={draftStart}
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
                <button type="button" onClick={() => setOpen(false)} className="px-3 py-1.5 text-sm font-medium text-gray-600">
                  Cancel
                </button>
                <button
                  type="button"
                  onClick={applyAbsolute}
                  className="rounded-lg bg-primary-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-primary-700"
                >
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
