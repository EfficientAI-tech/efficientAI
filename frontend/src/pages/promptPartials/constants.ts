export const IMPORTED_AGENT_TAG = '__imported_agent__'
export const METRIC_PARTIAL_TAG = '__metric_partial__'

export type PartialKind = 'all' | 'partial' | 'imported_agent' | 'metric'

export function isImportedAgent(partial: { tags?: string[] | null }): boolean {
  return Array.isArray(partial.tags) && partial.tags.includes(IMPORTED_AGENT_TAG)
}

export function isMetricPartial(partial: { tags?: string[] | null }): boolean {
  return Array.isArray(partial.tags) && partial.tags.includes(METRIC_PARTIAL_TAG)
}

export function displayTags(tags: string[] | null | undefined): string[] {
  return (tags || []).filter(
    (tag) => tag !== IMPORTED_AGENT_TAG && tag !== METRIC_PARTIAL_TAG,
  )
}

export function ensureImportedAgentTag(tags: string[]): string[] {
  const without = tags.filter(
    (tag) => tag !== IMPORTED_AGENT_TAG && tag !== METRIC_PARTIAL_TAG,
  )
  return [IMPORTED_AGENT_TAG, ...without]
}

export function ensureMetricPartialTag(tags: string[]): string[] {
  const without = tags.filter(
    (tag) => tag !== IMPORTED_AGENT_TAG && tag !== METRIC_PARTIAL_TAG,
  )
  return [METRIC_PARTIAL_TAG, ...without]
}
