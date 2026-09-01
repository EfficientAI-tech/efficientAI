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
