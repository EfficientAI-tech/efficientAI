/**
 * Helpers for evaluator metric selection and display.
 * Categorization metrics (selection_mode + children) are treated as one
 * selectable unit — only the parent ID is stored/shown.
 */

export interface MetricRow {
  id: string
  name: string
  description?: string | null
  enabled?: boolean
  parent_metric_id?: string | null
  selection_mode?: 'single_choice' | 'multi_label' | null
  metric_type?: string
  metric_origin?: string
  custom_data_type?: string | null
  children?: MetricRow[]
}

export function isCategorizationParent(metric: MetricRow): boolean {
  return Boolean(metric.selection_mode && !metric.parent_metric_id)
}

export function getTopLevelMetrics(metrics: MetricRow[]): MetricRow[] {
  return metrics.filter((m) => m.enabled !== false && !m.parent_metric_id)
}

export function getEnabledChildren(metric: MetricRow): MetricRow[] {
  if (!Array.isArray(metric.children)) return []
  return metric.children.filter((c) => c.enabled !== false)
}

/** Collapse child label IDs to parent for categorization metrics. */
export function normalizeSelectedMetricIds(
  selectedIds: string[],
  metrics: MetricRow[],
): string[] {
  const flat = flattenMetrics(metrics)
  const byId = new Map(flat.map((m) => [m.id, m]))
  const normalized = new Set<string>()

  for (const id of selectedIds) {
    const metric = byId.get(id)
    if (!metric) {
      normalized.add(id)
      continue
    }
    if (metric.parent_metric_id) {
      const parent = byId.get(metric.parent_metric_id)
      if (parent && isCategorizationParent(parent)) {
        normalized.add(parent.id)
      } else {
        normalized.add(id)
      }
    } else {
      normalized.add(id)
    }
  }
  return Array.from(normalized)
}

export function flattenMetrics(metrics: MetricRow[]): MetricRow[] {
  const out: MetricRow[] = []
  for (const m of metrics) {
    out.push(m)
    if (Array.isArray(m.children)) {
      out.push(...m.children)
    }
  }
  return out
}

export interface DisplayMetric {
  id: string
  name: string
  description?: string | null
  isCategory: boolean
  selectionMode?: 'single_choice' | 'multi_label' | null
  subLabelCount?: number
  subLabels?: string[]
  metricType?: string
}

function toDisplayMetric(id: string, metrics: MetricRow[]): DisplayMetric | null {
  const topLevel = getTopLevelMetrics(metrics)
  const byId = new Map(topLevel.map((m) => [m.id, m]))
  const metric = byId.get(id)

  if (!metric) {
    const flat = flattenMetrics(metrics).find((m) => m.id === id)
    if (!flat) return null
    return {
      id: flat.id,
      name: flat.name,
      description: flat.description,
      isCategory: false,
      metricType: flat.metric_type,
    }
  }

  if (isCategorizationParent(metric)) {
    const children = getEnabledChildren(metric)
    return {
      id: metric.id,
      name: metric.name,
      description: metric.description,
      isCategory: true,
      selectionMode: metric.selection_mode,
      subLabelCount: children.length,
      subLabels: children.map((c) => c.name),
      metricType: 'category',
    }
  }

  return {
    id: metric.id,
    name: metric.name,
    description: metric.description,
    isCategory: false,
    metricType: metric.metric_type,
  }
}

/** Build display rows from stored metric IDs (parent-only for categories). */
export function buildDisplayMetrics(
  selectedIds: string[] | null | undefined,
  metrics: MetricRow[],
): DisplayMetric[] | null {
  if (!selectedIds?.length) return null

  const normalized = normalizeSelectedMetricIds(selectedIds, metrics)
  const result: DisplayMetric[] = []

  for (const id of normalized) {
    const displayMetric = toDisplayMetric(id, metrics)
    if (displayMetric) {
      result.push(displayMetric)
    }
  }

  return result
}

export function countDisplayMetrics(
  selectedIds: string[] | null | undefined,
  metrics: MetricRow[],
): number | null {
  if (!selectedIds?.length) return null
  return normalizeSelectedMetricIds(selectedIds, metrics).length
}

export function isParentSelected(parent: MetricRow, selectedIds: string[]): boolean {
  const normalized = normalizeSelectedMetricIds(selectedIds, metricsFromParent(parent))
  return normalized.includes(parent.id)
}

function metricsFromParent(parent: MetricRow): MetricRow[] {
  return [parent, ...getEnabledChildren(parent)]
}

/** Toggle parent-only for categorization; standalone for others. */
export function toggleMetricSelection(
  metric: MetricRow,
  selectedIds: string[],
  allMetrics: MetricRow[],
): string[] {
  const normalized = normalizeSelectedMetricIds(selectedIds, allMetrics)

  if (isCategorizationParent(metric)) {
    if (normalized.includes(metric.id)) {
      return normalized.filter((id) => id !== metric.id)
    }
    return [...normalized, metric.id]
  }

  if (normalized.includes(metric.id)) {
    return normalized.filter((id) => id !== metric.id)
  }
  return [...normalized, metric.id]
}

export function getMetricTypeBadge(metric: DisplayMetric): { label: string; className: string } {
  if (metric.isCategory) {
    return {
      label: metric.selectionMode === 'single_choice' ? 'Single-choice' : 'Multi-label',
      className: 'bg-purple-100 text-purple-800 border-purple-200',
    }
  }
  const t = (metric.metricType || '').toLowerCase()
  if (t === 'rating' || t === 'number') {
    return { label: 'Quantitative', className: 'bg-blue-100 text-blue-800 border-blue-200' }
  }
  if (t === 'boolean') {
    return { label: 'Boolean', className: 'bg-emerald-100 text-emerald-800 border-emerald-200' }
  }
  if (t === 'text') {
    return { label: 'Text', className: 'bg-slate-100 text-slate-700 border-slate-200' }
  }
  return { label: 'Qualitative', className: 'bg-amber-100 text-amber-800 border-amber-200' }
}
