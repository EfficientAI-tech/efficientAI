import { Suspense, lazy, useMemo } from 'react'
import { Loader } from 'lucide-react'
import type { DashboardDrillCall } from './resultsDashboardSample'
import type { InsightDetailState, InsightDrillBaseProps } from './resultsDashboardInsightDrill'
import type {
  CallImportMetricAggregate,
  DashboardOpsScoreDay,
  EvaluatorResultRow,
  EvaluatorResultsAgentSummary,
  EvaluatorResultsDashboardOpsResponse,
} from '../../../types/api'
import type { MetricRow } from '../../simulations/simulationMetricScope'

const lazyUsage = lazy(() => import('./resultsDashboardDrilldowns').then((m) => ({ default: m.UsageWidgetDetail })))
const lazyTools = lazy(() => import('./resultsDashboardDrilldowns').then((m) => ({ default: m.ToolsMergedDetail })))
const lazyMetric = lazy(() => import('./resultsDashboardDrilldowns').then((m) => ({ default: m.MetricUsageDrill })))
const lazyTotalCalls = lazy(() => import('./resultsDashboardDrilldowns').then((m) => ({ default: m.TotalCallsDrill })))

function DrillFallback() {
  return (
    <div className="flex items-center justify-center py-12 text-sm text-gray-500">
      <Loader className="mr-2 h-4 w-4 animate-spin" />
      Loading insight…
    </div>
  )
}

export type InsightDrillHostProps = InsightDrillBaseProps & {
  detail: NonNullable<InsightDetailState>
  ops: EvaluatorResultsDashboardOpsResponse | undefined
  calls: DashboardDrillCall[]
  agents: EvaluatorResultsAgentSummary[]
  metrics: CallImportMetricAggregate[]
  catalog: MetricRow[]
  scoreDays: DashboardOpsScoreDay[] | undefined
  dateRange: { start: string; end: string } | null
  allTime?: boolean
  results: EvaluatorResultRow[]
  agentRows: Array<{ id: string; name: string; total: number }>
  callDays: Array<{ day: string; calls: number }>
  aggregateTotal: number
  onMetricNavigate: (next: { agentId?: string; metricId?: string; scenarioId?: string }) => void
  onTotalCallsNavigate: (agentId?: string) => void
}

export function InsightDrillHost({
  detail,
  runListBase,
  onBack,
  onOpenResult,
  ops,
  calls,
  agents,
  metrics,
  catalog,
  scoreDays,
  dateRange,
  allTime,
  results,
  agentRows,
  callDays,
  aggregateTotal,
  onMetricNavigate,
  onTotalCallsNavigate,
}: InsightDrillHostProps) {
  const body = useMemo(() => {
    if (detail.kind === 'usage') {
      const UsageDrill = lazyUsage
      return (
        <UsageDrill
          ops={ops}
          calls={calls}
          runListBase={runListBase}
          dateRange={dateRange}
          allTime={allTime}
          onBack={onBack}
          onOpenResult={onOpenResult}
        />
      )
    }
    if (detail.kind === 'tools') {
      const ToolsDrill = lazyTools
      return (
        <ToolsDrill
          ops={ops}
          calls={calls}
          runListBase={runListBase}
          dateRange={dateRange}
          allTime={allTime}
          onBack={onBack}
          onOpenResult={onOpenResult}
        />
      )
    }
    if (detail.kind === 'metric_flow') {
      const MetricDrill = lazyMetric
      return (
        <MetricDrill
          agents={agents}
          metrics={metrics}
          catalog={catalog}
          scoreDays={scoreDays}
          dateRange={dateRange}
          allTime={allTime}
          results={results}
          runListBase={runListBase}
          agentId={detail.agentId}
          metricId={detail.metricId}
          scenarioId={detail.scenarioId}
          onBack={onBack}
          onNavigate={onMetricNavigate}
          onOpenResult={onOpenResult}
        />
      )
    }
    if (detail.kind === 'total_calls_flow') {
      const TotalCallsDrill = lazyTotalCalls
      return (
        <TotalCallsDrill
          agentRows={agentRows}
          callDays={callDays}
          runListBase={runListBase}
          aggregateTotal={aggregateTotal}
          dateRange={dateRange}
          allTime={allTime}
          agentId={detail.agentId}
          onBack={onBack}
          onNavigate={onTotalCallsNavigate}
          onOpenResult={onOpenResult}
        />
      )
    }
    return null
  }, [
    detail,
    runListBase,
    onBack,
    onOpenResult,
    ops,
    calls,
    agents,
    metrics,
    catalog,
    scoreDays,
    dateRange,
    allTime,
    results,
    agentRows,
    callDays,
    aggregateTotal,
    onMetricNavigate,
    onTotalCallsNavigate,
  ])

  if (!body) return null
  return <Suspense fallback={<DrillFallback />}>{body}</Suspense>
}
