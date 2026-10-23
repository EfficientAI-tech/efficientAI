import type { MetricSuccessCriterion, SimulationSuccessCriteriaKind } from '../../types/api'
import {
  flattenMetrics,
  getEnabledChildren,
  isCategorizationParent,
  type MetricRow,
} from '../evaluators/components/metricSelectionUtils'

export function inferCriterionKind(metric: MetricRow): SimulationSuccessCriteriaKind {
  if (metric.custom_data_type === 'classification') return 'classification'
  if (isCategorizationParent(metric)) {
    return metric.selection_mode === 'multi_label' ? 'category_multi' : 'category_single'
  }
  if (metric.custom_data_type === 'enum') return 'enum'
  const t = (metric.metric_type || '').toLowerCase()
  if (t === 'boolean' || t === 'rating' || t === 'number' || t === 'text') return t
  return 'text'
}

export function numberRange(metric: MetricRow): { min: number; max: number } | null {
  const cfg = metric.custom_config as { min?: number; max?: number } | null | undefined
  if (cfg?.min == null || cfg?.max == null || cfg.max <= cfg.min) return null
  return { min: Number(cfg.min), max: Number(cfg.max) }
}

function classificationBlockEnabled(metric: MetricRow, key: 'noul' | 'choice' | 'score'): boolean {
  const cfg = metric.custom_config as Record<string, { enabled?: boolean }> | null | undefined
  const block = cfg?.[key]
  return Boolean(block && typeof block === 'object' && block.enabled)
}

export function defaultCriterionForMetric(metric: MetricRow): MetricSuccessCriterion {
  const kind = inferCriterionKind(metric)
  const base: MetricSuccessCriterion = { metric_id: metric.id, kind }

  if (kind === 'boolean') return { ...base, success_when: 'yes' }
  if (kind === 'rating') return { ...base, op: 'gte', threshold: 0.7 }
  if (kind === 'number') {
    const range = numberRange(metric)
    const threshold = range ? range.min + (range.max - range.min) * 0.7 : 0
    return { ...base, op: 'gte', threshold }
  }
  if (kind === 'enum') return { ...base, success_values: [] }
  if (kind === 'category_single') return { ...base, success_values: [] }
  if (kind === 'category_multi') return { ...base, label_rules: [] }
  if (kind === 'classification') {
    const questions: MetricSuccessCriterion['questions'] = {}
    if (classificationBlockEnabled(metric, 'noul')) {
      questions.noul = { success_when: 'yes' }
    }
    if (classificationBlockEnabled(metric, 'choice')) {
      questions.choice = { success_values: [] }
    }
    if (classificationBlockEnabled(metric, 'score')) {
      questions.score = { success_values: [] }
    }
    return { ...base, questions }
  }
  return base
}

export function syncCriteriaWithMetrics(
  metrics: MetricRow[],
  selectedIds: string[],
  existing: MetricSuccessCriterion[],
): MetricSuccessCriterion[] {
  const flat = flattenMetrics(metrics)
  const byId = new Map(flat.map((m) => [m.id, m]))
  const existingById = new Map(existing.map((c) => [c.metric_id, c]))
  return selectedIds.map((id) => {
    const prev = existingById.get(id)
    const metric = byId.get(id)
    if (!metric) return prev ?? { metric_id: id, kind: 'text' }
    if (prev && prev.kind === inferCriterionKind(metric)) return prev
    return defaultCriterionForMetric(metric)
  })
}

export function isCriterionValid(criterion: MetricSuccessCriterion, metric: MetricRow): boolean {
  const kind = criterion.kind
  if (kind === 'text') return true
  if (kind === 'boolean') return criterion.success_when === 'yes' || criterion.success_when === 'no'
  if (kind === 'rating') {
    return (
      (criterion.op === 'gte' ||
        criterion.op === 'lte' ||
        criterion.op === 'gt' ||
        criterion.op === 'lt') &&
      criterion.threshold != null &&
      criterion.threshold >= 0 &&
      criterion.threshold <= 1
    )
  }
  if (kind === 'number') {
    return (
      (criterion.op === 'gte' ||
        criterion.op === 'lte' ||
        criterion.op === 'gt' ||
        criterion.op === 'lt') &&
      criterion.threshold != null &&
      !Number.isNaN(criterion.threshold)
    )
  }
  if (kind === 'enum' || kind === 'category_single') {
    return (criterion.success_values?.length ?? 0) > 0
  }
  if (kind === 'category_multi') {
    return (criterion.label_rules?.length ?? 0) > 0
  }
  if (kind === 'classification') {
    const q = criterion.questions
    if (!q) return false
    let used = 0
    if (q.noul && classificationBlockEnabled(metric, 'noul')) {
      used += 1
      if (q.noul.success_when !== 'yes' && q.noul.success_when !== 'no') return false
    }
    if (q.choice && classificationBlockEnabled(metric, 'choice')) {
      used += 1
      if ((q.choice.success_values?.length ?? 0) === 0) return false
    }
    if (q.score && classificationBlockEnabled(metric, 'score')) {
      used += 1
      if ((q.score.success_values?.length ?? 0) === 0) return false
    }
    return used > 0
  }
  return false
}

export function criteriaStepValid(
  criteria: MetricSuccessCriterion[],
  metrics: MetricRow[],
): boolean {
  const flat = flattenMetrics(metrics)
  const byId = new Map(flat.map((m) => [m.id, m]))
  let hasGating = false
  for (const c of criteria) {
    const metric = byId.get(c.metric_id)
    if (!metric) return false
    if (!isCriterionValid(c, metric)) return false
    if (c.kind !== 'text') hasGating = true
  }
  return hasGating
}

const OP_LABEL: Record<string, string> = {
  gte: '≥',
  lte: '≤',
  gt: '>',
  lt: '<',
}

export function formatCriterionSummary(criterion: MetricSuccessCriterion, metric: MetricRow): string {
  switch (criterion.kind) {
    case 'boolean':
      return criterion.success_when === 'no' ? 'Pass when No' : 'Pass when Yes'
    case 'rating':
    case 'number':
      return `Pass when score ${OP_LABEL[criterion.op || 'gte'] ?? '≥'} ${criterion.threshold ?? '—'}`
    case 'enum':
    case 'category_single':
      return `Pass when: ${(criterion.success_values || []).map(successValueLabel).join(', ') || '—'}`
    case 'category_multi': {
      const children = getEnabledChildren(metric)
      const byId = new Map(children.map((c) => [c.id, successValueLabel(c.name)]))
      const parts = (criterion.label_rules || []).map(
        (r) => `${byId.get(r.child_id) || r.child_id} must be ${r.expect === 'no' ? 'No' : 'Yes'}`,
      )
      return parts.join('; ') || '—'
    }
    case 'classification': {
      const bits: string[] = []
      if (criterion.questions?.noul) {
        bits.push(`Yes/No: pass on ${criterion.questions.noul.success_when === 'no' ? 'No' : 'Yes'}`)
      }
      if (criterion.questions?.choice) {
        bits.push(`Choice: ${criterion.questions.choice.success_values.join(', ')}`)
      }
      if (criterion.questions?.score) {
        bits.push(`Level: ${criterion.questions.score.success_values.join(', ')}`)
      }
      return bits.join(' · ') || '—'
    }
    case 'text':
      return 'Informational only (does not affect pass/fail)'
    default:
      return '—'
  }
}

/** Coerce API/LLM enum options (string or { value, description }) to display labels. */
export function enumLabelsFromMetric(metric: MetricRow): string[] {
  const raw = (metric.custom_config as { options?: unknown } | null)?.options
  if (!Array.isArray(raw)) return []
  const labels: string[] = []
  for (const opt of raw) {
    if (typeof opt === 'string' && opt.trim()) {
      labels.push(opt.trim())
      continue
    }
    if (opt && typeof opt === 'object' && !Array.isArray(opt)) {
      const o = opt as Record<string, unknown>
      const label =
        typeof o.value === 'string'
          ? o.value
          : typeof o.label === 'string'
            ? o.label
            : typeof o.name === 'string'
              ? o.name
              : ''
      if (label.trim()) labels.push(label.trim())
    }
  }
  return labels
}

export function displayMetricText(value: unknown): string | null {
  if (value == null || value === '') return null
  if (typeof value === 'string') return value
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  if (typeof value === 'object') {
    const o = value as Record<string, unknown>
    if (typeof o.value === 'string') return o.value
    if (typeof o.description === 'string') return o.description
  }
  return null
}

export function successValueLabel(value: unknown): string {
  if (typeof value === 'string') return value
  if (value && typeof value === 'object') {
    const o = value as Record<string, unknown>
    if (typeof o.value === 'string') return o.value
    if (typeof o.label === 'string') return o.label
    if (typeof o.description === 'string') return o.description
  }
  return String(value)
}

export function classificationChoiceOptions(metric: MetricRow): string[] {
  const cfg = metric.custom_config as { choice?: { criteria?: Record<string, string> } } | null
  return Object.keys(cfg?.choice?.criteria || {})
}

export function classificationScoreLevels(metric: MetricRow): string[] {
  const cfg = metric.custom_config as { score?: { criteria?: unknown } } | null
  const levels = cfg?.score?.criteria
  if (!Array.isArray(levels)) return []
  return levels.map((level) => successValueLabel(level)).filter(Boolean)
}
