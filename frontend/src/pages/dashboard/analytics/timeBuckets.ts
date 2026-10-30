export type DashboardRange = '7d' | '30d' | '90d'
export type DashboardSource = 'simulation' | 'live'
export type DashboardView = 'metric' | 'agent'

export interface TimeWindow {
  start: Date
  end: Date
  since: string
  until: string
}

export interface TimeBucket extends TimeWindow {
  label: string
}

export const RANGE_DAYS: Record<DashboardRange, number> = {
  '7d': 7,
  '30d': 30,
  '90d': 90,
}

export const RANGE_LABELS: Record<DashboardRange, string> = {
  '7d': '7 days',
  '30d': '30 days',
  '90d': '90 days',
}

function startOfDay(date: Date): Date {
  const next = new Date(date)
  next.setHours(0, 0, 0, 0)
  return next
}

function endOfDay(date: Date): Date {
  const next = new Date(date)
  next.setHours(23, 59, 59, 999)
  return next
}

function addDays(date: Date, days: number): Date {
  const next = new Date(date)
  next.setDate(next.getDate() + days)
  return next
}

function toWindow(start: Date, end: Date): TimeWindow {
  const startDay = startOfDay(start)
  const endDay = endOfDay(end)
  return {
    start: startDay,
    end: endDay,
    since: startDay.toISOString(),
    until: endDay.toISOString(),
  }
}

function formatBucketLabel(start: Date, end: Date, daily: boolean): string {
  const opts: Intl.DateTimeFormatOptions = { month: 'short', day: 'numeric' }
  if (daily || start.toDateString() === end.toDateString()) {
    return start.toLocaleDateString(undefined, opts)
  }
  return `${start.toLocaleDateString(undefined, opts)}–${end.toLocaleDateString(undefined, opts)}`
}

export function bucketsForRange(
  range: DashboardRange,
  now: Date = new Date(),
): {
  buckets: TimeBucket[]
  current: TimeWindow
  previous: TimeWindow
  rangeDays: number
  previousRangeLabel: string
} {
  const rangeDays = RANGE_DAYS[range]
  const currentEnd = endOfDay(now)
  const currentStart = startOfDay(addDays(now, -(rangeDays - 1)))
  const current = toWindow(currentStart, currentEnd)

  const previousEnd = endOfDay(addDays(currentStart, -1))
  const previousStart = startOfDay(addDays(previousEnd, -(rangeDays - 1)))
  const previous = toWindow(previousStart, previousEnd)

  const bucketCount = range === '7d' ? 7 : range === '30d' ? 5 : 13
  const bucketDays = Math.max(1, Math.round(rangeDays / bucketCount))
  const buckets: TimeBucket[] = []

  for (let i = 0; i < bucketCount; i += 1) {
    const start = addDays(currentStart, i * bucketDays)
    const rawEnd = addDays(start, bucketDays - 1)
    const end = rawEnd > currentEnd || i === bucketCount - 1 ? currentEnd : endOfDay(rawEnd)
    if (start > currentEnd) break
    const window = toWindow(start, end)
    buckets.push({
      ...window,
      label: formatBucketLabel(window.start, window.end, bucketDays === 1),
    })
  }

  return {
    buckets,
    current,
    previous,
    rangeDays,
    previousRangeLabel: `previous ${RANGE_LABELS[range]}`,
  }
}

export function parseRange(value: string | null): DashboardRange {
  if (value === '30d' || value === '90d' || value === '7d') return value
  return '7d'
}

export function parseSource(value: string | null): DashboardSource {
  return value === 'live' ? 'live' : 'simulation'
}

export function parseView(value: string | null): DashboardView {
  return value === 'agent' ? 'agent' : 'metric'
}

export function parseIsoDay(value: string | null): string | null {
  if (!value) return null
  const match = /^\d{4}-\d{2}-\d{2}$/.test(value)
  if (!match) return null
  const date = new Date(`${value}T00:00:00`)
  return Number.isNaN(date.getTime()) ? null : value
}

export function toDayStamp(iso: string): string {
  return iso.slice(0, 10)
}

/**
 * Custom `since`/`until` (YYYY-MM-DD) override the 7/30/90 presets.
 * Previous period is the same length immediately before `since`.
 */
export function resolveDashboardWindow(
  range: DashboardRange,
  customSince?: string | null,
  customUntil?: string | null,
  now: Date = new Date(),
): ReturnType<typeof bucketsForRange> {
  const sinceDay = parseIsoDay(customSince ?? null)
  const untilDay = parseIsoDay(customUntil ?? null)
  if (!sinceDay || !untilDay) return bucketsForRange(range, now)

  let start = startOfDay(new Date(`${sinceDay}T00:00:00`))
  let end = endOfDay(new Date(`${untilDay}T00:00:00`))
  if (start > end) {
    const swap = start
    start = startOfDay(end)
    end = endOfDay(swap)
  }
  const rangeDays = Math.max(1, Math.round((end.getTime() - start.getTime()) / 86400000) + 1)
  const current = toWindow(start, end)
  const previousEnd = endOfDay(addDays(start, -1))
  const previousStart = startOfDay(addDays(previousEnd, -(rangeDays - 1)))
  const previous = toWindow(previousStart, previousEnd)

  const bucketCount = rangeDays <= 8 ? rangeDays : rangeDays <= 40 ? 5 : 13
  const bucketDays = Math.max(1, Math.round(rangeDays / bucketCount))
  const buckets: TimeBucket[] = []
  for (let i = 0; i < bucketCount; i += 1) {
    const bucketStart = addDays(start, i * bucketDays)
    const rawEnd = addDays(bucketStart, bucketDays - 1)
    const bucketEnd = rawEnd > end || i === bucketCount - 1 ? end : endOfDay(rawEnd)
    if (bucketStart > end) break
    const window = toWindow(bucketStart, bucketEnd)
    buckets.push({
      ...window,
      label: formatBucketLabel(window.start, window.end, bucketDays === 1),
    })
  }

  return {
    buckets,
    current,
    previous,
    rangeDays,
    previousRangeLabel: 'previous period',
  }
}
