export type StudioMetricScoreEntry = {
  value?: unknown
  type?: string
  metric_name?: string
  rationale?: string | null
  skipped?: unknown
  error?: string
}

export function compactStudioScoreLabel(score: StudioMetricScoreEntry | undefined): string {
  if (!score) return '—'
  if (score.error) return 'Err'
  const value = score.value
  if (value === undefined || value === null || value === '') return '—'
  const scoreType = score.type?.toLowerCase()
  if (scoreType === 'boolean') {
    const yes = value === true || value === 1 || value === '1' || value === 'true'
    return yes ? 'Yes' : 'No'
  }
  if (scoreType === 'rating' && typeof value === 'number') {
    return `${Math.round(Math.max(0, Math.min(1, value)) * 100)}%`
  }
  const text = String(value)
  if (text.length > 24) return `${text.slice(0, 22)}…`
  return text
}

export function studioMetricRationale(
  score: StudioMetricScoreEntry | undefined,
): string | undefined {
  if (!score || typeof score.rationale !== 'string') return undefined
  const trimmed = score.rationale.trim()
  return trimmed || undefined
}