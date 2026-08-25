const LEGACY_CATEGORY_LABEL_METRIC_NAMES = new Set([
  'yes',
  'no',
  'true',
  'false',
  'same',
  'different',
])

export type MetricScoreEntry = {
  value?: unknown
  type?: string
  metric_name?: string
  parent_metric_id?: string | null
  rationale?: string | null
  skipped?: unknown
}

export function isLegacyCategoryLabelMetric(metric: {
  type?: string | null
  metric_name?: string | null
}): boolean {
  if ((metric.type || '').toLowerCase() !== 'boolean') return false
  const name = (metric.metric_name || '').trim().toLowerCase()
  return LEGACY_CATEGORY_LABEL_METRIC_NAMES.has(name)
}

export function buildChildMetricIds(
  metrics: Array<{ id?: string; parent_metric_id?: string | null; children?: any[] }>,
): Set<string> {
  const ids = new Set<string>()
  const visit = (metric: { id?: string; parent_metric_id?: string | null; children?: any[] }) => {
    if (metric.parent_metric_id && metric.id) ids.add(metric.id)
    for (const child of metric.children || []) {
      if (child?.id) ids.add(child.id)
      visit(child)
    }
  }
  for (const metric of metrics) visit(metric)
  return ids
}

/** Hide per-label child booleans; keep parent category + standalone metrics. */
export function shouldHideMetricScore(
  metricId: string,
  metric: MetricScoreEntry,
  childMetricIds: Set<string>,
): boolean {
  return Boolean(
    metric.parent_metric_id ||
      childMetricIds.has(metricId) ||
      isLegacyCategoryLabelMetric(metric),
  )
}

export function filterVisibleMetricScores(
  metricScores: Record<string, MetricScoreEntry>,
  childMetricIds: Set<string>,
): Array<[string, MetricScoreEntry]> {
  return Object.entries(metricScores).filter(([metricId, metric]) => {
    if (shouldHideMetricScore(metricId, metric, childMetricIds)) return false
    const val = metric.skipped ?? metric.value
    if (val === null || val === undefined) return false
    if (val === '') return false
    if (typeof val === 'string' && val.toLowerCase() === 'n/a') return false
    if (typeof val === 'string' && val.trim() === '') return false
    return true
  })
}
