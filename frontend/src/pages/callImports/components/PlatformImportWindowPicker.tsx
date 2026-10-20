import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Calendar, Clock } from 'lucide-react'
import { usageTheme } from '../../usage/usageTheme'
import { formatUsageTimezoneLabel, getUsageTimezone } from '../../usage/usageTimezone'
import InlineMonthCalendar, {
  parseDateInput,
  type DateRangeValue,
} from '../../../components/date/InlineMonthCalendar'

export type WindowPreset = { id: string; label: string; days: number }

type Mode = 'relative' | 'absolute'

type Props = {
  windowStart: string
  windowEnd: string
  activePreset: string
  presets: readonly WindowPreset[]
  onPreset: (presetId: string, days: number) => void
  onRangeChange: (start: string, end: string) => void
  formatRangeLabel: (start: string, end: string) => string
}

export function toDatetimeLocalValue(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function splitDatetimeLocal(value: string): { date: string; time: string } {
  if (!value) return { date: '', time: '00:00' }
  const [date, time] = value.split('T')
  return { date: date || '', time: (time || '00:00').slice(0, 5) }
}

function joinDatetimeLocal(date: string, time: string): string {
  if (!date) return ''
  return `${date}T${time || '00:00'}`
}

const RELATIVE_DAY_OPTIONS = [1, 7, 14, 30, 60, 90] as const
const RELATIVE_MONTH_OPTIONS = [
  { id: '6m', label: '6 months', months: 6 },
  { id: '9m', label: '9 months', months: 9 },
  { id: '1y', label: '1 year', months: 12 },
] as const

export default function PlatformImportWindowPicker({
  windowStart,
  windowEnd,
  activePreset,
  presets,
  onPreset,
  onRangeChange,
  formatRangeLabel,
}: Props) {
  const [open, setOpen] = useState(false)
  const [mode, setMode] = useState<Mode>('absolute')
  const [popoverPos, setPopoverPos] = useState({
    top: 0,
    left: 0,
    width: 300,
    maxHeight: 360,
  })
  const rootRef = useRef<HTMLDivElement>(null)
  const popoverRef = useRef<HTMLDivElement>(null)
  const startParts = splitDatetimeLocal(windowStart)
  const endParts = splitDatetimeLocal(windowEnd)
  const [dateRange, setDateRange] = useState<DateRangeValue>({
    start: startParts.date,
    end: endParts.date,
  })
  const [calendarMonth, setCalendarMonth] = useState(() => {
    const d = parseDateInput(startParts.date)
    return d ?? new Date()
  })

  const maxEndDate = useMemo(() => {
    const end = new Date()
    end.setMinutes(end.getMinutes() - 15)
    return end
  }, [])

  const customActive = Boolean(windowStart && windowEnd && !activePreset)

  useEffect(() => {
    if (open) {
      const s = splitDatetimeLocal(windowStart)
      const e = splitDatetimeLocal(windowEnd)
      setDateRange({ start: s.date, end: e.date })
      const d = parseDateInput(s.date)
      if (d) setCalendarMonth(d)
    }
  }, [open, windowStart, windowEnd])

  const updatePopoverPosition = () => {
    if (!open || !rootRef.current) return
    const margin = 12
    const rect = rootRef.current.getBoundingClientRect()
    const width = Math.min(360, window.innerWidth - margin * 2)
    let left = rect.left
    if (left + width > window.innerWidth - margin) {
      left = window.innerWidth - width - margin
    }
    left = Math.max(margin, left)

    const viewportMax = window.innerHeight - margin * 2
    let maxHeight = Math.min(460, viewportMax)
    const popoverHeight = popoverRef.current?.offsetHeight ?? 440
    const spaceBelow = window.innerHeight - rect.bottom - margin
    const spaceAbove = rect.top - margin

    let top = rect.bottom + 8
    if (popoverHeight > spaceBelow && spaceAbove > spaceBelow) {
      top = rect.top - Math.min(popoverHeight, maxHeight) - 8
    }
    top = Math.max(margin, top)
    maxHeight = Math.min(maxHeight, window.innerHeight - top - margin)

    setPopoverPos({ top, left, width, maxHeight })
  }

  useLayoutEffect(() => {
    if (!open) return
    updatePopoverPosition()
    const id = requestAnimationFrame(() => updatePopoverPosition())
    window.addEventListener('resize', updatePopoverPosition)
    window.addEventListener('scroll', updatePopoverPosition, true)
    return () => {
      cancelAnimationFrame(id)
      window.removeEventListener('resize', updatePopoverPosition)
      window.removeEventListener('scroll', updatePopoverPosition, true)
    }
  }, [open, mode, dateRange.start, dateRange.end])

  useEffect(() => {
    const onDoc = (event: MouseEvent) => {
      const target = event.target as Node
      if (rootRef.current?.contains(target)) return
      const pop = document.getElementById('platform-import-window-popover')
      if (pop?.contains(target)) return
      setOpen(false)
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [])

  const pillClass = (active: boolean) =>
    `cursor-pointer rounded-md px-2.5 py-1 text-xs font-medium transition-colors border ${
      active ? usageTheme.pillActive : usageTheme.pillInactive
    }`

  const draftStart = joinDatetimeLocal(dateRange.start, '00:00')
  const draftEnd = joinDatetimeLocal(dateRange.end, '23:59')
  const canApply = Boolean(dateRange.start && dateRange.end) && draftEnd > draftStart

  const applyAbsolute = () => {
    if (!canApply) return
    onRangeChange(draftStart, draftEnd)
    setOpen(false)
  }

  const applyRelativeDays = (days: number) => {
    const end = new Date()
    end.setMinutes(end.getMinutes() - 15)
    const start = new Date(end)
    start.setDate(start.getDate() - days)
    onRangeChange(toDatetimeLocalValue(start), toDatetimeLocalValue(end))
    setOpen(false)
  }

  const applyRelativeMonths = (months: number) => {
    const end = new Date()
    end.setMinutes(end.getMinutes() - 15)
    const start = new Date(end)
    start.setMonth(start.getMonth() - months)
    onRangeChange(toDatetimeLocalValue(start), toDatetimeLocalValue(end))
    setOpen(false)
  }

  return (
    <div ref={rootRef} className="relative">
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex items-center gap-0.5 rounded-lg border border-[#fde047]/50 bg-white/80 p-0.5">
          {presets.map((r) => (
            <button
              key={r.id}
              type="button"
              onClick={() => onPreset(r.id, r.days)}
              className={pillClass(activePreset === r.id)}
            >
              {r.label.replace('Last ', '')}
            </button>
          ))}
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            className={pillClass(open || customActive)}
          >
            <Calendar className="h-3.5 w-3.5 inline mr-1" />
            Custom
          </button>
        </div>
        {windowStart && windowEnd ? (
          <span className="text-xs text-gray-500 truncate hidden sm:inline">
            {formatRangeLabel(windowStart, windowEnd)}
            <span className="text-gray-400"> · {formatUsageTimezoneLabel(getUsageTimezone())}</span>
          </span>
        ) : null}
      </div>

      {windowStart && windowEnd ? (
        <p className="text-xs text-gray-500 mt-2 flex flex-wrap items-center gap-1.5 sm:hidden">
          <Clock className="h-3.5 w-3.5 text-gray-400 shrink-0" />
          <span className="font-medium text-gray-800">{formatRangeLabel(windowStart, windowEnd)}</span>
        </p>
      ) : null}

      {open && typeof document !== 'undefined'
        ? createPortal(
        <div
          ref={popoverRef}
          id="platform-import-window-popover"
          style={{
            top: popoverPos.top,
            left: popoverPos.left,
            width: popoverPos.width,
          }}
          className="fixed z-[10060] rounded-xl border border-[#fde047]/60 bg-white p-3 shadow-xl ring-1 ring-[#fef9c3]"
        >
          <div className="flex gap-1.5 mb-2">
            <button
              type="button"
              onClick={() => setMode('absolute')}
              className={`cursor-pointer rounded-full px-3 py-1 text-xs font-medium border ${
                mode === 'absolute' ? usageTheme.pillActive : usageTheme.pillMuted
              }`}
            >
              Absolute
            </button>
            <button
              type="button"
              onClick={() => setMode('relative')}
              className={`cursor-pointer rounded-full px-3 py-1 text-xs font-medium border ${
                mode === 'relative' ? usageTheme.pillActive : usageTheme.pillMuted
              }`}
            >
              Relative
            </button>
          </div>

          {mode === 'relative' ? (
            <div className="space-y-2">
              <div className="flex flex-wrap gap-1.5">
                {RELATIVE_DAY_OPTIONS.map((days) => (
                  <button
                    key={days}
                    type="button"
                    onClick={() => applyRelativeDays(days)}
                    className="cursor-pointer rounded-md border border-gray-200 px-2.5 py-1.5 text-xs font-medium hover:border-[#facc15] hover:bg-[#fefce8]"
                  >
                    Last {days}d
                  </button>
                ))}
                {RELATIVE_MONTH_OPTIONS.map((option) => (
                  <button
                    key={option.id}
                    type="button"
                    onClick={() => applyRelativeMonths(option.months)}
                    className="cursor-pointer rounded-md border border-gray-200 px-2.5 py-1.5 text-xs font-medium hover:border-[#facc15] hover:bg-[#fefce8]"
                  >
                    {option.label}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <div className="space-y-2.5">
              <InlineMonthCalendar
                month={calendarMonth}
                onMonthChange={setCalendarMonth}
                range={dateRange}
                onRangeChange={setDateRange}
                maxDate={maxEndDate}
              />
              <p className="text-[11px] text-gray-500">
                Each selected day runs midnight–end of day ({formatUsageTimezoneLabel(getUsageTimezone())}).
              </p>
              {!canApply && dateRange.start && dateRange.end ? (
                <p className="text-[11px] text-amber-700">End date must be on or after start date.</p>
              ) : null}
              <div className="flex justify-end gap-2 pt-2 border-t border-gray-100">
                <button
                  type="button"
                  onClick={() => setOpen(false)}
                  className="cursor-pointer px-3 py-1.5 text-sm font-medium text-gray-600"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  disabled={!canApply}
                  onClick={applyAbsolute}
                  className={`${usageTheme.applyBtn} cursor-pointer disabled:cursor-not-allowed`}
                >
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
