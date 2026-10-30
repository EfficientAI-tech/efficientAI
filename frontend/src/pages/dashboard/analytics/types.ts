import type { CallImportMetricAggregate, MetricFailurePolicy } from '../../../types/api'
import type { PrimaryScore, ScoreDelta, Sentiment, Polarity } from './metricMath'
import type { DashboardRange, DashboardSource, DashboardView, TimeBucket, TimeWindow } from './timeBuckets'

export interface ScoredMetric {
  agg: CallImportMetricAggregate
  policy?: MetricFailurePolicy | null
  score: PrimaryScore
  previousScore: PrimaryScore | null
  delta: ScoreDelta | null
  polarity: Polarity
  sentiment: Sentiment
  reliable: boolean
  headline: string
}

export interface AgentMetricSeries {
  agentId: string
  current: TimeWindow
  previous: TimeWindow
  buckets: TimeBucket[]
  metrics: ScoredMetric[]
  totalRows: number
  completedRows: number
  failedRows: number
  pointsByMetric: Record<string, Array<{ label: string; value: number | null; count: number }>>
}

export interface LiveMetricPoint {
  metricId: string
  label: string
  value: number | null
  count: number
}

export interface LiveMetricSeries {
  agentId: string
  pointsByMetric: Record<string, LiveMetricPoint[]>
  available: boolean
}

export type { DashboardRange, DashboardSource, DashboardView }
