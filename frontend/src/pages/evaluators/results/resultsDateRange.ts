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

function maxIso(a: string, b: string): string {
  return a > b ? a : b
}

function minIso(a: string, b: string): string {
  return a < b ? a : b
}

/** Keep a day-sized window inside an outer hub filter (both ISO UTC). */
export function intersectSinceUntil(
  inner: { since: string; until: string },
  outer?: { since?: string; until?: string },
): { since: string; until: string } {
  let { since, until } = inner
  if (outer?.since) since = maxIso(since, outer.since)
  if (outer?.until) until = minIso(until, outer.until)
  return { since, until }
}

type WallParts = { y: number; mo: number; d: number; hh: number; mm: number; ss: number }

function zonedWallParts(utcMs: number, timeZone: string): WallParts {
  const fmt = new Intl.DateTimeFormat('en-US', {
    timeZone,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  })
  const parts = Object.fromEntries(fmt.formatToParts(new Date(utcMs)).map((p) => [p.type, p.value]))
  return {
    y: Number(parts.year),
    mo: Number(parts.month),
    d: Number(parts.day),
    hh: Number(parts.hour),
    mm: Number(parts.minute),
    ss: Number(parts.second),
  }
}

function cmpWall(target: WallParts, actual: WallParts): number {
  if (target.y !== actual.y) return target.y - actual.y
  if (target.mo !== actual.mo) return target.mo - actual.mo
  if (target.d !== actual.d) return target.d - actual.d
  if (target.hh !== actual.hh) return target.hh - actual.hh
  if (target.mm !== actual.mm) return target.mm - actual.mm
  return target.ss - actual.ss
}

/** UTC instant when wall clock `hms` occurs on `dayKey` in `timeZone`. */
function wallClockInZoneToUtcMs(dayKey: string, hms: string, timeZone: string): number {
  const [y, mo, d] = dayKey.split('-').map(Number)
  const [hh, mm, rest] = hms.split(':')
  const [ss] = rest.split('.')
  const target: WallParts = {
    y,
    mo,
    d,
    hh: Number(hh),
    mm: Number(mm),
    ss: Number(ss),
  }
  let lo = Date.UTC(y, mo - 1, d - 1, 0, 0, 0, 0)
  let hi = Date.UTC(y, mo - 1, d + 2, 0, 0, 0, 0)
  while (hi - lo > 1000) {
    const mid = Math.floor((lo + hi) / 2)
    const diff = cmpWall(target, zonedWallParts(mid, timeZone))
    if (diff === 0) return mid
    if (diff > 0) lo = mid
    else hi = mid
  }
  return Math.floor((lo + hi) / 2)
}

/**
 * UTC ISO bounds for a calendar day in the dashboard ops timezone (matches server chart days).
 */
export function calendarDayToSinceUntil(
  dayKey: string,
  timeZone: string,
): { since: string; until: string } {
  const sinceMs = wallClockInZoneToUtcMs(dayKey, '00:00:00', timeZone)
  const endSec = wallClockInZoneToUtcMs(dayKey, '23:59:59', timeZone)
  return {
    since: new Date(sinceMs).toISOString(),
    until: new Date(endSec + 999).toISOString(),
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