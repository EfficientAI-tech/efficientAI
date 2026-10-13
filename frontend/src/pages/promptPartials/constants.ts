export const IMPORTED_AGENT_TAG = '__imported_agent__'
export const METRIC_PARTIAL_TAG = '__metric_partial__'

const SYSTEM_TAG_PREFIXES = [
  '__agent_provider_prompt__:',
  '__call_import__:',
  '__agent_system_prompt__:',
]

export type PartialKind = 'all' | 'partial' | 'imported_agent' | 'metric'

export function isSystemPartialTag(tag: string): boolean {
  if (tag === IMPORTED_AGENT_TAG || tag === METRIC_PARTIAL_TAG) return true
  return SYSTEM_TAG_PREFIXES.some((prefix) => tag.startsWith(prefix))
}

export function isImportedAgent(partial: { tags?: string[] | null }): boolean {
  return Array.isArray(partial.tags) && partial.tags.includes(IMPORTED_AGENT_TAG)
}

export function isMetricPartial(partial: { tags?: string[] | null }): boolean {
  return Array.isArray(partial.tags) && partial.tags.includes(METRIC_PARTIAL_TAG)
}

/** User-visible tags only (hide internal link/metadata tags). */
export function displayTags(tags: string[] | null | undefined): string[] {
  return (tags || []).filter((tag) => !isSystemPartialTag(tag))
}

export function linkedSystemPartialTags(tags: string[] | null | undefined): string[] {
  return (tags || []).filter(
    (tag) =>
      tag.startsWith('__agent_provider_prompt__:') || tag.startsWith('__call_import__:'),
  )
}

const CALL_IMPORT_TAG_PREFIX = '__call_import__:'

/** Platform historical import id when this agent partial was auto-created for that batch. */
export function callImportIdFromPartialTags(tags: string[] | null | undefined): string | null {
  const tag = (tags || []).find((t) => t.startsWith(CALL_IMPORT_TAG_PREFIX))
  if (!tag) return null
  const id = tag.slice(CALL_IMPORT_TAG_PREFIX.length).trim()
  return id || null
}

export function isPlatformImportAgentPartial(partial: { tags?: string[] | null }): boolean {
  return isImportedAgent(partial) && callImportIdFromPartialTags(partial.tags) != null
}

export type VersionOriginBadge = {
  label: string
  title?: string
  className: string
}

/** Short badge for version history (import snapshot vs eval save vs live push). */
export function versionOriginBadge(
  changeSummary: string | null | undefined,
  versionNumber: number,
  isPlatformImport: boolean,
): VersionOriginBadge | null {
  const s = (changeSummary || '').toLowerCase()
  if (
    s.includes('platform import') ||
    s.includes('live provider prompt') ||
    s.includes('imported from platform historical')
  ) {
    return {
      label: 'Provider snapshot',
      title: 'Original live prompt at import — no push needed for this version',
      className: 'bg-sky-50 text-sky-800 border border-sky-200',
    }
  }
  if (isPlatformImport && versionNumber === 1 && !s.includes('saved from evaluation') && !s.includes('pushed')) {
    return {
      label: 'Provider snapshot',
      title: 'Original live prompt at import — no push needed for this version',
      className: 'bg-sky-50 text-sky-800 border border-sky-200',
    }
  }
  if (s.includes('saved from evaluation')) {
    return {
      label: 'Saved from eval',
      title: 'Composed from prompt improvements; not pushed to the provider yet',
      className: 'bg-amber-50 text-amber-900 border border-amber-200',
    }
  }
  if (s.includes('pushed from evaluation') || s.includes('pushed v') || s.includes('to live')) {
    return {
      label: 'Live push',
      className: 'bg-emerald-50 text-emerald-800 border border-emerald-200',
    }
  }
  if (s.includes('reverted')) {
    return { label: 'Restored locally', className: 'bg-gray-100 text-gray-700 border border-gray-200' }
  }
  return null
}

export function ensureImportedAgentTag(tags: string[]): string[] {
  const user = tags.filter((tag) => !isSystemPartialTag(tag))
  return [IMPORTED_AGENT_TAG, ...user]
}

export function tagsForImportedAgentSave(
  existing: string[] | null | undefined,
  userTagsFromInput: string[],
): string[] {
  const user = userTagsFromInput.map((t) => t.trim()).filter(Boolean).filter((tag) => !isSystemPartialTag(tag))
  return ensureImportedAgentTag([...linkedSystemPartialTags(existing), ...user])
}

export function ensureMetricPartialTag(tags: string[]): string[] {
  const without = tags.filter((tag) => !isSystemPartialTag(tag))
  return [METRIC_PARTIAL_TAG, ...without]
}
