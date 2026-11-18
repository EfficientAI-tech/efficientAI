/** Local calendar date (YYYY-MM-DD) helpers for evaluator result filters. */

export function toDateInput(d: Date): string {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

export function rangeForDays(days: number): { start: string; end: string } {
  const end = new Date()
  const start = new Date()
  start.setDate(start.getDate() - (days - 1))
  return { start: toDateInput(start), end: toDateInput(end) }
}

/** Chart axis label for a calendar day key (YYYY-MM-DD). */
export function formatChartDayLabel(sortKey: string, includeYear = false): string {
  const [year, month, date] = sortKey.split('-').map(Number)
  const local = new Date(year, (month || 1) - 1, date || 1)
  return local.toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
    ...(includeYear ? { year: 'numeric' } : {}),
  })
}

/** Local calendar day for an ISO timestamp (matches hub date filters). */
export function resultLocalDayKey(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso.slice(0, 10)
  return toDateInput(d)
}

export function isoToDateInput(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso.slice(0, 10)
  return toDateInput(d)
}

export function dateRangeToSinceUntil(start: string, end: string): { since: string; until: string } {
  const sinceDate = new Date(`${start}T00:00:00`)
  const untilDate = new Date(`${end}T23:59:59.999`)
  return {
    since: sinceDate.toISOString(),
    until: untilDate.toISOString(),
  }
}

export function formatResultsDateRange(start: string, end: string): string {
  if (start === end) return start
  return `${start} → ${end}`
}

export function dayCountInRange(start: string, end: string): number {
  const a = new Date(`${start}T12:00:00`)
  const b = new Date(`${end}T12:00:00`)
  if (Number.isNaN(a.getTime()) || Number.isNaN(b.getTime())) return 1
  return Math.max(1, Math.round((b.getTime() - a.getTime()) / 86_400_000) + 1)
}

/** Shown on grid cards and drill headers — matches Hub date filter (default last 7 days). */
export function formatDashboardWindowLabel(
  range: { start: string; end: string } | null,
  allTime?: boolean,
): string {
  if (allTime || !range) return 'All time'
  const days = dayCountInRange(range.start, range.end)
  const span = formatResultsDateRange(range.start, range.end)
  return days === 1 ? span : `${span} · ${days} days`
}
