export function formatDashboardHeadline(value: number | null, suffix = ''): string {
  if (value == null || Number.isNaN(value)) return '—'
  return `${value.toLocaleString(undefined, { maximumFractionDigits: 1 })}${suffix}`
}