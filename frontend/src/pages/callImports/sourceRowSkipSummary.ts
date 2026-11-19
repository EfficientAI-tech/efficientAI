import type { CallImportSourceRowSkip } from '../../types/api'

const REASON_LABELS: Record<string, string> = {
  missing_conversation_id: 'missing conversation ID',
  missing_recording_url: 'missing recording URL',
  missing_transcript: 'missing required transcript',
  missing_recording_date: 'missing recording date',
  missing_required_parameter: 'missing required field',
  invalid_recording_url: 'invalid recording URL',
}

/** Short aggregate line for the import skip banner (e.g. "18 missing required transcript, 5 missing conversation ID"). */
export function summarizeSourceRowSkipReasons(
  skips: CallImportSourceRowSkip[],
): string {
  if (skips.length === 0) return 'missing or invalid required values'

  const counts = new Map<string, number>()
  for (const skip of skips) {
    const key = skip.reason || 'unknown'
    counts.set(key, (counts.get(key) ?? 0) + 1)
  }

  const parts = [...counts.entries()]
    .sort((a, b) => b[1] - a[1])
    .map(([reason, count]) => {
      const label = REASON_LABELS[reason] ?? reason.replace(/_/g, ' ')
      return count === 1 ? `1 row ${label}` : `${count} rows ${label}`
    })

  if (parts.length === 1) return parts[0]
  return parts.join('; ')
}