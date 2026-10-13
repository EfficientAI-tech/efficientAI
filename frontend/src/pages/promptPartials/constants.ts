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
      title: 'This snapshot was sent to the connected agent on the voice platform',
      className: 'bg-emerald-50 text-emerald-800 border border-emerald-200',
    }
  }
  if (s.includes('reverted')) {
    return {
      label: 'Restored locally',
      title: 'Working copy in the app was set to this snapshot; the voice platform was not changed',
      className: 'bg-gray-100 text-gray-700 border border-gray-200',
    }
  }
  return null
}

/** Plain-language line under each version row in the history drawer. */
export function versionRowExplanation(
  changeSummary: string | null | undefined,
  versionNumber: number,
  isPlatformImport: boolean,
  opts: {
    isCurrent: boolean
    isLiveOnProvider: boolean
  },
): string {
  const origin = versionOriginBadge(changeSummary, versionNumber, isPlatformImport)
  if (opts.isCurrent && opts.isLiveOnProvider) {
    return 'This is your working copy here and matches what is live on the voice platform.'
  }
  if (opts.isCurrent) {
    if (origin?.label === 'Saved from eval') {
      return 'This is your working copy here. Not on the voice platform yet — use Push live when ready.'
    }
    return 'This is your working copy in EfficientAI (preview and evaluations use this text).'
  }
  if (opts.isLiveOnProvider) {
    return 'This snapshot is what is currently live on your connected voice agent.'
  }
  if (origin?.title) return origin.title
  if (origin?.label === 'Live push') {
    return 'Was pushed to the voice platform from this partial.'
  }
  const summary = (changeSummary || '').trim()
  if (summary && summary.length < 200) return summary
  return 'Older snapshot. Compare to see changes, or Restore to make it your working copy (local only).'
}

export function latestLivePromptVersion(
  pushes: { prompt_version: number; status: string }[] | null | undefined,
): number | null {
  const live = (pushes || []).filter((p) => p.status === 'pushed')
  if (!live.length) return null
  return Math.max(...live.map((p) => p.prompt_version))
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
  const links = linkedSystemPartialTags(existing)
  const merged: string[] = []
  const seen = new Set<string>()
  for (const tag of [IMPORTED_AGENT_TAG, ...links, ...user]) {
    if (seen.has(tag)) continue
    seen.add(tag)
    merged.push(tag)
  }
  return merged
}

export function ensureMetricPartialTag(tags: string[]): string[] {
  const without = tags.filter((tag) => !isSystemPartialTag(tag))
  return [METRIC_PARTIAL_TAG, ...without]
}
