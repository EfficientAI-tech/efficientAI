import { describe, expect, it } from 'vitest'
import { verdictForMetric } from './metricVerdict'

describe('verdictForMetric', () => {
  it('asks for more data when n is below the reliability floor', () => {
    const verdict = verdictForMetric({
      values: [0.8, 0.81, 0.79],
      perAgentMeans: { a: { name: 'A', mean: 0.8, count: 3 } },
    })
    expect(verdict.kind).toBe('needs_data')
  })

  it('flags a metric that never moves as redundant', () => {
    const values = Array.from({ length: 12 }, () => 1)
    const verdict = verdictForMetric({
      values,
      perAgentMeans: {
        a: { name: 'Support-EU', mean: 1, count: 6 },
        b: { name: 'Sales', mean: 1, count: 6 },
      },
    })
    expect(verdict.kind).toBe('redundant')
    expect(verdict.reasons[0]).toMatch(/constant/i)
  })

  it('names a twin metric when per-call agreement is at least 0.9', () => {
    const values = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8]
    const verdict = verdictForMetric({
      values,
      perAgentMeans: {
        a: { name: 'A', mean: 0.2, count: 4 },
        b: { name: 'B', mean: 0.6, count: 4 },
      },
      otherMetrics: [{ id: 'twin', name: 'Empathy', values: values.map((value) => value + 0.01) }],
    })
    expect(verdict.kind).toBe('redundant')
    expect(verdict.twinName).toBe('Empathy')
  })

  it('marks a discriminating metric as relevant', () => {
    const verdict = verdictForMetric({
      values: [0.2, 0.25, 0.3, 0.7, 0.75, 0.8, 0.22, 0.78],
      perAgentMeans: {
        a: { name: 'Support-EU', mean: 0.24, count: 4 },
        b: { name: 'Sales', mean: 0.76, count: 4 },
      },
    })
    expect(verdict.kind).toBe('relevant')
    expect(verdict.reasons.join(' ')).toMatch(/Support-EU/)
  })

  it('treats the higher mean as weakest when lower is better', () => {
    const verdict = verdictForMetric({
      values: [2.1, 2.0, 2.2, 0.8, 0.9, 0.85, 2.0, 0.9],
      polarity: 'lower_is_better',
      perAgentMeans: {
        a: { name: 'Support-EU', mean: 2.1, count: 4 },
        b: { name: 'Sales', mean: 0.85, count: 4 },
      },
    })
    expect(verdict.kind).toBe('relevant')
    expect(verdict.reasons.join(' ')).toMatch(/Support-EU is weakest/)
  })
})
