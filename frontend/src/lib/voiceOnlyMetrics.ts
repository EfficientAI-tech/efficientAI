/** Metrics that require audio / voice signal — not applicable to chat evals. */
const ACOUSTIC_METRIC_NAMES = new Set(['Pitch Variance', 'Jitter', 'Shimmer', 'HNR'])

const AI_VOICE_METRIC_NAMES = new Set([
  'MOS Score',
  'Emotion Category',
  'Emotion Confidence',
  'Valence',
  'Arousal',
  'Speaker Consistency',
  'Prosody Score',
])

export const VOICE_ONLY_METRIC_NAMES = new Set([...ACOUSTIC_METRIC_NAMES, ...AI_VOICE_METRIC_NAMES])

export function isVoiceOnlyMetricName(name: string): boolean {
  return VOICE_ONLY_METRIC_NAMES.has(name)
}

export function isVoiceOnlyMetric(metric: { name: string; tags?: string[] | null }): boolean {
  if (isVoiceOnlyMetricName(metric.name)) return true
  const tags = metric.tags ?? []
  return tags.includes('voice_only') || tags.includes('audio')
}
