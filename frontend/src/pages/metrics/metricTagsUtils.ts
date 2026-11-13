/** Parse comma-separated metric tags (trim, drop blanks, preserve order). */
export function parseTagsCsv(csv: string): string[] {
  return csv
    .split(',')
    .map((tag) => tag.trim())
    .filter(Boolean)
}

/** Create payload: omit tags when empty (matches single-metric behavior). */
export function tagsForMetricCreate(csv: string): string[] | undefined {
  const tags = parseTagsCsv(csv)
  return tags.length > 0 ? tags : undefined
}

/** Update payload: always send list so clearing the field removes stored tags. */
export function tagsForMetricUpdate(csv: string): string[] {
  return parseTagsCsv(csv)
}

export function tagsCsvFromList(tags: string[] | null | undefined): string {
  if (!tags?.length) return ''
  return tags.join(', ')
}
