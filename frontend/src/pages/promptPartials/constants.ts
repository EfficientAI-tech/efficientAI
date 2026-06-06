export const IMPORTED_AGENT_TAG = '__imported_agent__'

export type PartialKind = 'all' | 'partial' | 'imported_agent'

export function isImportedAgent(partial: { tags?: string[] | null }): boolean {
  return Array.isArray(partial.tags) && partial.tags.includes(IMPORTED_AGENT_TAG)
}

export function displayTags(tags: string[] | null | undefined): string[] {
  return (tags || []).filter((tag) => tag !== IMPORTED_AGENT_TAG)
}

export function ensureImportedAgentTag(tags: string[]): string[] {
  const without = tags.filter((tag) => tag !== IMPORTED_AGENT_TAG)
  return [IMPORTED_AGENT_TAG, ...without]
}
