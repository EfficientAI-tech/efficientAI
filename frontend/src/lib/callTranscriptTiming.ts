const MAX_PLAUSIBLE_CALL_OFFSET_SEC = 6 * 60 * 60

export function sanitizeCallOffsetSeconds(value?: number | null): number | undefined {
  if (value == null || Number.isNaN(value)) return undefined
  let sec = value
  if (sec > 1e12) sec = sec / 1000
  if (sec > 1e9) return undefined
  if (sec < 0 || sec > MAX_PLAUSIBLE_CALL_OFFSET_SEC) return undefined
  return sec
}

export function formatCallOffsetSeconds(seconds: number): string {
  const mins = Math.floor(seconds / 60)
  const secs = seconds % 60
  if (mins > 0) {
    const secPart =
      secs % 1 === 0 ? String(Math.floor(secs)).padStart(2, '0') : secs.toFixed(1).padStart(4, '0')
    return `${mins}:${secPart}`
  }
  return `${secs.toFixed(1)}s`
}

/** When the message started in the call (seconds from call start). One value only. */
export function formatMessageTiming(
  startSec?: number | null,
  _endSec?: number | null,
): string | null {
  const start = sanitizeCallOffsetSeconds(startSec)
  if (start == null) return null
  return formatCallOffsetSeconds(start)
}

/** @deprecated Prefer formatMessageTiming */
export function formatTimingRange(
  startSec?: number | null,
  endSec?: number | null,
  durationSec?: number | null,
): string | null {
  const start = sanitizeCallOffsetSeconds(startSec)
  const duration = sanitizeCallOffsetSeconds(durationSec)
  const end =
    sanitizeCallOffsetSeconds(endSec) ??
    (start != null && duration != null && duration > 0 ? start + duration : null)
  return formatMessageTiming(start, end)
}

export function normalizeEpochSeconds(value: unknown): number | undefined {
  if (typeof value !== 'number' || Number.isNaN(value)) return undefined
  if (value > 1e10) return value / 1000
  return sanitizeCallOffsetSeconds(value)
}

export function offsetSecondsFromCallStart(messageMs: number, callStartMs: number): number {
  return (messageMs - callStartMs) / 1000
}
