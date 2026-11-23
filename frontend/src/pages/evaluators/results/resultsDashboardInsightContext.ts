import type { CallImportMetricAggregate, EvaluatorResultsDashboardOpsResponse } from '../../../types/api'
import type { UsageDisplayCurrency } from '../../../lib/usageCurrency'
import type { ResultsWidget } from './resultsDashboardLayout'

export type InsightDayPoint = {
  day: string
  sortKey: string
  completed: number
  failed: number
}

export type InsightPanelContext = {
  widget: ResultsWidget
  ops: EvaluatorResultsDashboardOpsResponse | undefined
  days: InsightDayPoint[]
  duration: { average: number | null; points: Array<{ day: string; value: number }> }
  scenarioMatrix: Array<{ agentName: string; scenarioName: string; count: number }>
  scoreSeries: Map<string, Array<{ day: string; value: number }>>
  categorySeries: Map<string, { labels: string[]; data: Array<Record<string, string | number>> }>
  lowest: Array<{ name: string; value: number }>
  agentRows: Array<{ id: string; name: string; total: number; completed: number; failed: number; rate: number }>
  scenarioRows: Array<{ name: string; count: number }>
  primaryMetric: CallImportMetricAggregate | null
  trendMetric: CallImportMetricAggregate | null
  aggregateTotal: number
  aggregateCompleted: number
  usageCurrency?: UsageDisplayCurrency
  usageInrRate?: number
}