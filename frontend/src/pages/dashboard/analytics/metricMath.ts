import type { CallImportMetricAggregate, MetricFailurePolicy } from '../../../types/api'

export const MIN_SAMPLE_SIZE = 5
export const WORSENING_POINTS_THRESHOLD = 5
export const WORSENING_RELATIVE_THRESHOLD = 0.1
export const FAILING_RATE_THRESHOLD = 0.2

export type Polarity = 'higher_is_better' | 'lower_is_better' | 'neutral'
export type ScoreKind = 'mean' | 'pass_rate' | 'failure_share' | 'top_label_share'
export type Sentiment = 'improving' | 'worsening' | 'flat'

export interface PrimaryScore {
  value: number | null
  kind: ScoreKind
  display: string
  count: number
  topLabel?: string
  failureRate: number | null
}

export interface ScoreDelta {
  absolute: number
  relative: number | null
  direction: 'up' | 'down' | 'flat'
  display: string
  points: number
}

export function isReliable(count: number, min = MIN_SAMPLE_SIZE): boolean {
  return count >= min
}

export function isQualityMetric(agg: CallImportMetricAggregate): boolean {
  return (agg.metric_category ?? 'quality') !== 'user_insight'
}

export function isInsightMetric(agg: CallImportMetricAggregate): boolean {
  return (agg.metric_category ?? 'quality') === 'user_insight'
}

function valueCountTotal(agg: CallImportMetricAggregate): number {
  return agg.value_counts.reduce((sum, item) => sum + item.count, 0)
}

function labelsMatch(label: string, candidates: string[]): boolean {
  const needle = label.trim().toLowerCase()
  return candidates.some((candidate) => candidate.trim().toLowerCase() === needle)
}

function failureLabels(policy?: MetricFailurePolicy | null): string[] {
  return [...(policy?.failure_values ?? []), ...(policy?.failure_child_names ?? [])]
}

function looksNumeric(agg: CallImportMetricAggregate): boolean {
  const type = (agg.metric_type ?? '').toLowerCase()
  if (type === 'number' || type === 'rating') return true
  return agg.mean != null && agg.value_counts.length === 0
}

function looksBoolean(agg: CallImportMetricAggregate): boolean {
  const type = (agg.metric_type ?? '').toLowerCase()
  if (type === 'boolean') return true
  if (agg.value_counts.length === 0) return false
  return agg.value_counts.every((item) =>
    ['true', 'false', 'yes', 'no'].includes(item.label.trim().toLowerCase()),
  )
}

function failureCount(agg: CallImportMetricAggregate, policy?: MetricFailurePolicy | null): number {
  const labels = failureLabels(policy)
  const fallback = looksBoolean(agg) ? ['false', 'no'] : []
  const failSet = labels.length > 0 ? labels : fallback
  if (failSet.length === 0) return 0
  return agg.value_counts
    .filter((item) => labelsMatch(item.label, failSet))
    .reduce((sum, item) => sum + item.count, 0)
}

function formatUnitInterval(value: number): string {
  if (value > 1) return Number.isInteger(value) ? String(value) : value.toFixed(1)
  return value.toFixed(2)
}

function formatPercent(value: number): string {
  return `${Math.round(value * 100)}%`
}

export function primaryScore(
  agg: CallImportMetricAggregate,
  policy?: MetricFailurePolicy | null,
): PrimaryScore {
  const count = agg.count
  if (looksNumeric(agg) && agg.mean != null) {
    let failureRate: number | null = null
    if (policy?.numeric_rule) {
      const { op, threshold } = policy.numeric_rule
      const failed = (() => {
        switch (op) {
          case 'lt':
            return agg.mean < threshold
          case 'lte':
            return agg.mean <= threshold
          case 'gt':
            return agg.mean > threshold
          case 'gte':
            return agg.mean >= threshold
          default:
            return false
        }
      })()
      failureRate = failed ? 1 : 0
    }
    return {
      value: agg.mean,
      kind: 'mean',
      display: formatUnitInterval(agg.mean),
      count,
      failureRate,
    }
  }

  const total = valueCountTotal(agg)
  if (looksBoolean(agg) && total > 0) {
    const fails = failureCount(agg, policy)
    const passRate = 1 - fails / total
    return {
      value: passRate,
      kind: 'pass_rate',
      display: formatPercent(passRate),
      count,
      failureRate: fails / total,
    }
  }

  if (total > 0) {
    const labels = failureLabels(policy)
    if (labels.length > 0) {
      const fails = failureCount(agg, policy)
      const share = fails / total
      return {
        value: share,
        kind: 'failure_share',
        display: formatPercent(share),
        count,
        failureRate: share,
      }
    }
    const top = [...agg.value_counts].sort((a, b) => b.count - a.count)[0]
    const share = top.count / total
    return {
      value: share,
      kind: 'top_label_share',
      display: `${top.label} · ${formatPercent(share)}`,
      count,
      topLabel: top.label,
      failureRate: null,
    }
  }

  return {
    value: null,
    kind: looksNumeric(agg) ? 'mean' : looksBoolean(agg) ? 'pass_rate' : 'top_label_share',
    display: '—',
    count,
    failureRate: null,
  }
}

export function polarity(
  agg: CallImportMetricAggregate,
  policy?: MetricFailurePolicy | null,
): Polarity {
  const score = primaryScore(agg, policy)
  if (score.kind === 'pass_rate') return 'higher_is_better'
  if (score.kind === 'failure_share') return 'lower_is_better'
  if (score.kind === 'top_label_share') return 'neutral'
  const rule = policy?.numeric_rule
  if (rule?.op === 'gt' || rule?.op === 'gte') return 'lower_is_better'
  return 'higher_is_better'
}

export function delta(
  current: number | null,
  previous: number | null,
  kind: ScoreKind,
): ScoreDelta | null {
  if (current == null || previous == null) return null
  const absolute = current - previous
  const points = Math.round(Math.abs(absolute) * 100)
  const relative = previous === 0 ? null : absolute / Math.abs(previous)
  const direction: ScoreDelta['direction'] =
    points < 1 ? 'flat' : absolute > 0 ? 'up' : 'down'
  const unit = kind === 'mean' && Math.abs(current) <= 1 && Math.abs(previous) <= 1
    ? 'pts'
    : kind === 'mean'
      ? ''
      : 'pts'
  const display =
    direction === 'flat'
      ? 'unchanged'
      : unit
        ? `${points} ${unit}`
        : formatUnitInterval(Math.abs(absolute))
  return { absolute, relative, direction, display, points }
}

export function sentiment(scoreDelta: ScoreDelta | null, scorePolarity: Polarity): Sentiment {
  if (!scoreDelta || scoreDelta.direction === 'flat' || scorePolarity === 'neutral') {
    return 'flat'
  }
  const rose = scoreDelta.direction === 'up'
  if (scorePolarity === 'higher_is_better') return rose ? 'improving' : 'worsening'
  return rose ? 'worsening' : 'improving'
}

export function isWorsening(
  scoreDelta: ScoreDelta | null,
  scorePolarity: Polarity,
): boolean {
  if (sentiment(scoreDelta, scorePolarity) !== 'worsening' || !scoreDelta) return false
  if (scoreDelta.points >= WORSENING_POINTS_THRESHOLD) return true
  return scoreDelta.relative != null && Math.abs(scoreDelta.relative) >= WORSENING_RELATIVE_THRESHOLD
}

export function formatHeadline(args: {
  name: string
  score: PrimaryScore
  delta: ScoreDelta | null
  sentiment: Sentiment
  previousLabel: string
  reliable: boolean
}): string {
  if (!args.reliable) {
    return `${args.name} — not enough runs (n=${args.score.count})`
  }
  if (!args.delta || args.delta.direction === 'flat') {
    return `${args.name} ${args.score.display}`
  }
  const verb = args.delta.direction === 'down' ? 'down' : 'up'
  return `${args.name} ${args.score.display}, ${verb} ${args.delta.display} vs ${args.previousLabel}`
}

export function sentimentClasses(value: Sentiment): {
  text: string
  bg: string
  border: string
} {
  if (value === 'improving') {
    return { text: 'text-emerald-700', bg: 'bg-emerald-50', border: 'border-emerald-200' }
  }
  if (value === 'worsening') {
    return { text: 'text-rose-700', bg: 'bg-rose-50', border: 'border-rose-200' }
  }
  return { text: 'text-gray-600', bg: 'bg-gray-50', border: 'border-gray-200' }
}
