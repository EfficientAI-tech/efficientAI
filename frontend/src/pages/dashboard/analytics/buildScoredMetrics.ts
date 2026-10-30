import type {
  CallImportMetricAggregate,
  EvaluatorResultsAggregateResponse,
  MetricFailurePolicy,
} from '../../../types/api'
import {
  delta,
  formatHeadline,
  isReliable,
  polarity,
  primaryScore,
  sentiment,
} from './metricMath'
import type { ScoredMetric } from './types'

export function buildScoredMetrics(
  current: EvaluatorResultsAggregateResponse | undefined,
  previous: EvaluatorResultsAggregateResponse | undefined,
  policies: Record<string, MetricFailurePolicy> | undefined,
  previousLabel: string,
): ScoredMetric[] {
  const previousById = new Map(
    (previous?.metrics ?? []).map((metric) => [metric.metric_id, metric]),
  )
  return (current?.metrics ?? []).map((agg) =>
    scoreAggregate(agg, previousById.get(agg.metric_id), policies?.[agg.metric_id], previousLabel),
  )
}

export function scoreAggregate(
  agg: CallImportMetricAggregate,
  previousAgg: CallImportMetricAggregate | undefined,
  policy: MetricFailurePolicy | undefined,
  previousLabel: string,
): ScoredMetric {
  const score = primaryScore(agg, policy)
  const previousScore = previousAgg ? primaryScore(previousAgg, policy) : null
  const scorePolarity = polarity(agg, policy)
  const scoreDelta = delta(score.value, previousScore?.value ?? null, score.kind)
  const scoreSentiment = sentiment(scoreDelta, scorePolarity)
  const reliable = isReliable(score.count)
  return {
    agg,
    policy,
    score,
    previousScore,
    delta: scoreDelta,
    polarity: scorePolarity,
    sentiment: scoreSentiment,
    reliable,
    headline: formatHeadline({
      name: agg.metric_name,
      score,
      delta: scoreDelta,
      sentiment: scoreSentiment,
      previousLabel,
      reliable,
    }),
  }
}
