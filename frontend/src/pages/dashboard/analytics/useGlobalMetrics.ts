import { useMemo } from 'react'
import { aggregateCalls, isCountMetric } from './callMetrics'
import {
  STRIP_METRIC_IDS,
  formatGlobalValue,
  globalMetricById,
  type GlobalMetricDef,
  type GlobalMetricId,
} from './globalMetrics'
import { delta, isReliable, sentiment, type ScoreDelta, type Sentiment } from './metricMath'
import type { MockCall } from './mockCalls'
import { type DashboardRange, type DashboardSource } from './timeBuckets'
import { useDashboardCalls } from './useDashboardCalls'
import type { AggregatedMetric } from './callMetrics'

export interface ScoredGlobalMetric {
  def: GlobalMetricDef
  current: AggregatedMetric
  previous: AggregatedMetric
  value: number | null
  display: string
  delta: ScoreDelta | null
  sentiment: Sentiment
  reliable: boolean
  points: Array<number | null>
  subLabel?: string
}

function headlineValue(id: GlobalMetricId, agg: AggregatedMetric): number | null {
  if (id === 'total_calls') return agg.count || agg.sum
  if (isCountMetric(id)) return agg.avg
  return agg.avg
}

export function scoreGlobal(
  def: GlobalMetricDef,
  currentCalls: MockCall[],
  previousCalls: MockCall[],
  bucketCalls: MockCall[][],
): ScoredGlobalMetric {
  const current = aggregateCalls(currentCalls, def.id, def.failRule)
  const previous = aggregateCalls(previousCalls, def.id, def.failRule)
  if (def.id === 'total_calls') {
    current.count = currentCalls.length
    current.avg = currentCalls.length
    current.sum = currentCalls.length
    previous.count = previousCalls.length
    previous.avg = previousCalls.length
    previous.sum = previousCalls.length
  }
  const value = headlineValue(def.id, current)
  const previousValue = headlineValue(def.id, previous)
  const scoreDelta = delta(value, previousValue, 'mean')
  const longest =
    def.id === 'silence_duration'
      ? aggregateCalls(currentCalls, 'longest_pause', globalMetricById('longest_pause')?.failRule)
      : null
  return {
    def,
    current,
    previous,
    value,
    display: formatGlobalValue(def, value),
    delta: scoreDelta,
    sentiment: sentiment(scoreDelta, def.polarity),
    reliable: isReliable(currentCalls.length),
    points: bucketCalls.map((calls) => {
      const agg = aggregateCalls(calls, def.id, def.failRule)
      if (def.id === 'total_calls') return calls.length
      return headlineValue(def.id, agg)
    }),
    subLabel:
      longest?.max != null
        ? `longest ${formatGlobalValue(globalMetricById('longest_pause')!, longest.max)}`
        : undefined,
  }
}

export function useGlobalMetrics(
  range: DashboardRange,
  source: DashboardSource,
  agentId?: string | null,
  extra?: { since?: string | null; until?: string | null; scenarioId?: string | null },
) {
  const calls = useDashboardCalls(range, source, agentId, extra)
  const window = calls.window
  const metrics = useMemo(
    () =>
      STRIP_METRIC_IDS.map((id) => {
        const def = globalMetricById(id)
        if (!def) throw new Error(`Missing global metric ${id}`)
        return scoreGlobal(
          def,
          calls.current,
          calls.previous,
          calls.buckets.map((bucket) => bucket.calls),
        )
      }),
    [calls],
  )
  return { metrics, calls, window, isLoading: calls.isLoading, available: calls.available }
}
