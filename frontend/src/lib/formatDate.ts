import { format, isValid } from 'date-fns'

export function parseDateValue(value: string | Date | null | undefined): Date | null {
  if (value == null || value === '') return null
  const d = value instanceof Date ? value : new Date(value)
  return isValid(d) ? d : null
}

export function formatDateSafe(
  value: string | Date | null | undefined,
  pattern: string,
  fallback = '—',
): string {
  const d = parseDateValue(value)
  if (!d) return fallback
  return format(d, pattern)
}
