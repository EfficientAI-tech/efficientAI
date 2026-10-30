import { describe, expect, it } from 'vitest'
import type { CallImportMetricAggregate, MetricFailurePolicy } from '../../../types/api'
import {
  delta,
  formatHeadline,
  isReliable,
  isWorsening,
  polarity,
  primaryScore,
  sentiment,
} from './metricMath'

function agg(partial: Partial<CallImportMetricAggregate>): CallImportMetricAggregate {
  return {
    metric_id: 'm1',
    metric_name: 'Empathy',
    metric_type: 'rating',
    metric_category: 'quality',
    count: 12,
    skipped_count: 0,
    error_count: 0,
    mean: null,
    median: null,
    p25: null,
    p75: null,
    p95: null,
    min: null,
    max: null,
    stddev: null,
    histogram_buckets: [],
    value_counts: [],
    ...partial,
  }
}

describe('primaryScore', () => {
  it('uses mean for rating metrics', () => {
    const score = primaryScore(agg({ mean: 0.78 }))
    expect(score.kind).toBe('mean')
    expect(score.value).toBe(0.78)
    expect(score.display).toBe('0.78')
  })

  it('uses pass rate for boolean metrics, treating false as fail by default', () => {
    const score = primaryScore(
      agg({
        metric_type: 'boolean',
        mean: null,
        value_counts: [
          { label: 'true', count: 8 },
          { label: 'false', count: 2 },
        ],
      }),
    )
    expect(score.kind).toBe('pass_rate')
    expect(score.value).toBe(0.8)
    expect(score.display).toBe('80%')
    expect(score.failureRate).toBe(0.2)
  })

  it('uses failure share for category metrics with a policy', () => {
    const policy: MetricFailurePolicy = {
      metric_id: 'm1',
      failure_values: ['angry_hangup'],
    }
    const score = primaryScore(
      agg({
        metric_type: 'category',
        mean: null,
        value_counts: [
          { label: 'resolved', count: 7 },
          { label: 'angry_hangup', count: 3 },
        ],
      }),
      policy,
    )
    expect(score.kind).toBe('failure_share')
    expect(score.value).toBe(0.3)
  })

  it('uses the top label when a category metric has no policy', () => {
    const score = primaryScore(
      agg({
        metric_type: 'category',
        mean: null,
        value_counts: [
          { label: 'billing', count: 6 },
          { label: 'support', count: 4 },
        ],
      }),
    )
    expect(score.kind).toBe('top_label_share')
    expect(score.topLabel).toBe('billing')
    expect(score.display).toContain('billing')
  })
})

describe('polarity, delta, sentiment', () => {
  it('treats pass rate as higher-is-better and failure share as lower-is-better', () => {
    expect(
      polarity(
        agg({
          metric_type: 'boolean',
          mean: null,
          value_counts: [{ label: 'true', count: 1 }],
        }),
      ),
    ).toBe('higher_is_better')
    expect(
      polarity(
        agg({
          metric_type: 'category',
          mean: null,
          value_counts: [{ label: 'bad', count: 1 }],
        }),
        { metric_id: 'm1', failure_values: ['bad'] },
      ),
    ).toBe('lower_is_better')
  })

  it('reports rating drops in points and marks them as worsening', () => {
    const change = delta(0.72, 0.78, 'mean')
    expect(change?.points).toBe(6)
    expect(change?.direction).toBe('down')
    expect(change?.display).toBe('6 pts')
    expect(sentiment(change, 'higher_is_better')).toBe('worsening')
    expect(isWorsening(change, 'higher_is_better')).toBe(true)
  })

  it('treats a lower failure rate as improving', () => {
    const change = delta(0.1, 0.2, 'failure_share')
    expect(sentiment(change, 'lower_is_better')).toBe('improving')
    expect(isWorsening(change, 'lower_is_better')).toBe(false)
  })

  it('requires a minimum sample size', () => {
    expect(isReliable(4)).toBe(false)
    expect(isReliable(5)).toBe(true)
  })
})

describe('formatHeadline', () => {
  it('explains not-enough-runs and deltas in plain language', () => {
    const score = primaryScore(agg({ mean: 0.78, count: 3 }))
    expect(
      formatHeadline({
        name: 'Empathy',
        score,
        delta: null,
        sentiment: 'flat',
        previousLabel: 'previous 7 days',
        reliable: false,
      }),
    ).toBe('Empathy — not enough runs (n=3)')

    const change = delta(0.72, 0.78, 'mean')
    expect(
      formatHeadline({
        name: 'Empathy',
        score: primaryScore(agg({ mean: 0.72 })),
        delta: change,
        sentiment: 'worsening',
        previousLabel: 'previous 7 days',
        reliable: true,
      }),
    ).toBe('Empathy 0.72, down 6 pts vs previous 7 days')
  })
})
