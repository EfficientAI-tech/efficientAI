export const PLATFORM_SKIP_LABELS: Record<string, string> = {
  duplicate: 'already in this import',
  too_short: 'shorter than the minimum',
  no_audio: 'no recording',
  in_progress: 'still in progress',
  filtered_status: 'status not included',
  provider_redacted: 'redacted by the provider',
}

export function platformSkipLines(counts?: Record<string, number> | null): string[] {
  if (!counts) return []
  return Object.entries(counts)
    .filter(([, count]) => count > 0)
    .map(([key, count]) => {
      const label = PLATFORM_SKIP_LABELS[key] || key.replace(/_/g, ' ')
      return `${count.toLocaleString()} ${label}`
    })
}

export function platformImportLabel(input: {
  original_filename?: string | null
  dataset?: string | null
  provider?: string | null
}): string {
  const raw = (input.original_filename || '').trim()
  if (raw && !raw.startsWith('platform:')) return raw
  const dataset = (input.dataset || '').trim()
  if (dataset) return dataset
  const provider = (input.provider || 'platform').trim()
  const titled = provider ? provider.charAt(0).toUpperCase() + provider.slice(1) : 'Platform'
  return `${titled} import`
}
