import {
  addMonths,
  eachDayOfInterval,
  endOfMonth,
  endOfWeek,
  format,
  isSameDay,
  isSameMonth,
  isWithinInterval,
  startOfMonth,
  startOfWeek,
  subMonths,
} from 'date-fns'
import { ChevronLeft, ChevronRight } from 'lucide-react'

export type DateRangeValue = { start: string; end: string }

type Props = {
  month: Date
  onMonthChange: (month: Date) => void
  range: DateRangeValue
  onRangeChange: (range: DateRangeValue) => void
  maxDate?: Date
  minDate?: Date
}

function toDateInput(d: Date): string {
  return format(d, 'yyyy-MM-dd')
}

function parseDateInput(value: string): Date | null {
  if (!value) return null
  const [y, m, day] = value.split('-').map(Number)
  if (!y || !m || !day) return null
  return new Date(y, m - 1, day)
}

export function applyDateToRange(
  range: DateRangeValue,
  dateStr: string,
): DateRangeValue {
  const clicked = parseDateInput(dateStr)
  if (!clicked) return range
  const start = parseDateInput(range.start)
  const end = parseDateInput(range.end)
  if (!start || !end || (range.start && range.end && range.start !== range.end)) {
    return { start: dateStr, end: dateStr }
  }
  if (isSameDay(clicked, start)) return range
  if (clicked < start) return { start: dateStr, end: range.end }
  return { start: range.start, end: dateStr }
}

export default function InlineMonthCalendar({
  month,
  onMonthChange,
  range,
  onRangeChange,
  maxDate,
  minDate,
}: Props) {
  const monthStart = startOfMonth(month)
  const gridStart = startOfWeek(monthStart, { weekStartsOn: 0 })
  const gridEnd = endOfWeek(endOfMonth(month), { weekStartsOn: 0 })
  const days = eachDayOfInterval({ start: gridStart, end: gridEnd })

  const rangeStart = parseDateInput(range.start)
  const rangeEnd = parseDateInput(range.end)

  const isDisabled = (day: Date) => {
    if (minDate && day < minDate && !isSameDay(day, minDate)) return true
    if (maxDate && day > maxDate && !isSameDay(day, maxDate)) return true
    return false
  }

  const isInRange = (day: Date) => {
    if (!rangeStart || !rangeEnd) return false
    const start = rangeStart <= rangeEnd ? rangeStart : rangeEnd
    const end = rangeStart <= rangeEnd ? rangeEnd : rangeStart
    return isWithinInterval(day, { start, end })
  }

  const isRangeEdge = (day: Date) => {
    if (!rangeStart || !rangeEnd) return rangeStart && isSameDay(day, rangeStart)
    return isSameDay(day, rangeStart) || isSameDay(day, rangeEnd)
  }

  return (
    <div className="select-none">
      <div className="flex items-center justify-between mb-2">
        <button
          type="button"
          onClick={() => onMonthChange(subMonths(month, 1))}
          className="p-1.5 rounded-md text-gray-500 hover:bg-gray-100"
          aria-label="Previous month"
        >
          <ChevronLeft className="h-4 w-4" />
        </button>
        <span className="text-sm font-semibold text-gray-900">{format(month, 'MMMM yyyy')}</span>
        <button
          type="button"
          onClick={() => onMonthChange(addMonths(month, 1))}
          className="p-1.5 rounded-md text-gray-500 hover:bg-gray-100"
          aria-label="Next month"
        >
          <ChevronRight className="h-4 w-4" />
        </button>
      </div>
      <div className="grid grid-cols-7 gap-0.5 text-center text-[10px] font-medium text-gray-400 mb-1">
        {['Su', 'Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa'].map((d) => (
          <span key={d}>{d}</span>
        ))}
      </div>
      <div className="grid grid-cols-7 gap-0.5">
        {days.map((day) => {
          const inMonth = isSameMonth(day, month)
          const disabled = isDisabled(day)
          const inRange = isInRange(day)
          const edge = isRangeEdge(day)
          return (
            <button
              key={day.toISOString()}
              type="button"
              disabled={disabled || !inMonth}
              onClick={() => {
                if (disabled || !inMonth) return
                onRangeChange(applyDateToRange(range, toDateInput(day)))
              }}
              className={`h-7 w-full rounded-md text-[11px] font-medium transition-colors ${
                !inMonth
                  ? 'invisible'
                  : disabled
                    ? 'text-gray-300 cursor-not-allowed'
                    : edge
                      ? 'bg-[#facc15] text-[#713f12] shadow-sm'
                      : inRange
                        ? 'bg-[#fef9c3] text-[#854d0e]'
                        : 'text-gray-700 hover:bg-[#fefce8]'
              }`}
            >
              {format(day, 'd')}
            </button>
          )
        })}
      </div>
    </div>
  )
}

export { toDateInput, parseDateInput }
