import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { itemsOf } from '../../../lib/safeData'
import { callFailed } from './callFailed'
import { aggregateCalls, isCountMetric } from './callMetrics'
import DistributionChart from './charts/DistributionChart'
import DonutChart from './charts/DonutChart'
import InteractiveTimeChart, { type ChartAnnotation, type TimeChartPoint } from './charts/InteractiveTimeChart'
import StackedShareChart from './charts/StackedShareChart'
import { dashboardApi, useDataSourceKey } from './dashboardApi'
import { experimentMarkers } from './experimentMarkers'
import FailurePatterns from './FailurePatterns'
import { clustersForMetric } from './dashboardClusters'
import { defaultChartType, type ChartType } from './dashboardLayout'
import DrilldownBreadcrumb from './DrilldownBreadcrumb'
import {
  formatGlobalValue,
  globalMetricById,
  isGlobalMetricId,
  type GlobalMetricId,
} from './globalMetrics'
import { delta, sentiment } from './metricMath'
import MetricAgentsTable, { type MetricAgentRow } from './MetricAgentsTable'
import MetricInsightsPanel, { type MetricImprovement } from './MetricInsightsPanel'
import { MOCK_AGENTS, MOCK_METRICS } from './mockCatalog'
import type { MockCall } from './mockCalls'
import { verdictForMetric } from './metricVerdict'
import PointDetailPopover from './PointDetailPopover'
import ScenarioBreakdown from './ScenarioBreakdown'
import { RANGE_LABELS, toDayStamp, type DashboardRange, type DashboardSource } from './timeBuckets'
import type { AgentMetricSeries, ScoredMetric } from './types'
import { useDashboardCalls } from './useDashboardCalls'
import { useDashboardFilters } from './useDashboardFilters'
import { scoreGlobal } from './useGlobalMetrics'

function numericScore(call: MockCall, metricId: string): number | null {
  const score = call.metric_scores[metricId]
  if (!score) return null
  if (typeof score.value === 'number') return score.value
  if (typeof score.value === 'boolean') return score.value ? 1 : 0
  if (score.failed) return 0
  return 1
}

function matchesLabel(call: MockCall, metricId: string, label: string | null): boolean {
  if (!label) return true
  return String(call.metric_scores[metricId]?.value) === label
}

function bucketValue(calls: MockCall[], metricId: string, globalId?: GlobalMetricId): number | null {
  if (calls.length === 0) return null
  if (globalId) {
    const def = globalMetricById(globalId)
    if (!def) return null
    const agg = aggregateCalls(calls, globalId, def.failRule)
    if (globalId === 'total_calls') return calls.length
    if (isCountMetric(globalId)) return agg.avg
    return agg.avg
  }
  const values = calls
    .map((call) => numericScore(call, metricId))
    .filter((value): value is number => value != null)
  return values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : null
}

export default function MetricPage({
  metricId,
  agentId,
  range,
  source,
  series,
  onBack,
  onOpenAgent,
}: {
  metricId: string
  agentId: string | null
  range: DashboardRange
  source: DashboardSource
  series: AgentMetricSeries | null
  onBack: () => void
  onOpenAgent: (agentId: string) => void
}) {
  const filters = useDashboardFilters()
  const [chartType, setChartType] = useState<ChartType>('line')
  const extra = {
    since: filters.since,
    until: filters.until,
    scenarioId: filters.scenarioId,
  }
  const global = globalMetricById(metricId)
  const local = series?.metrics.find((metric) => metric.agg.metric_id === metricId)
  const localDef = MOCK_METRICS.find((metric) => metric.id === metricId)
  const name = global?.name ?? local?.agg.metric_name ?? localDef?.name ?? 'Metric'
  const calls = useDashboardCalls(range, source, agentId, extra)
  const overlay = useDashboardCalls(range, source === 'live' ? 'simulation' : 'live', agentId, extra)
  const dataSource = useDataSourceKey()
  const { data: clusters } = useQuery({
    queryKey: ['dashboard-clusters', dataSource, agentId ?? 'support', metricId],
    queryFn: () =>
      dashboardApi.getClusters({
        agentId: agentId ?? 'mock-agent-support-eu',
        since: calls.window.current.since,
        until: calls.window.current.until,
      }),
    enabled: !global,
    staleTime: 5 * 60 * 1000,
    retry: false,
  })
  const { data: optRuns } = useQuery({
    queryKey: ['optimization-runs', dataSource, agentId ?? 'all'],
    queryFn: () => dashboardApi.listOptimizationRuns(agentId ?? undefined),
    staleTime: 5 * 60 * 1000,
  })

  const currentCalls = calls.current
  const previousCalls = calls.previous
  const callBuckets = calls.buckets
  const overlayBuckets = overlay.buckets
  const scopedCurrent = useMemo(
    () => currentCalls.filter((call) => matchesLabel(call, metricId, filters.label)),
    [currentCalls, filters.label, metricId],
  )
  const scopedPrevious = useMemo(
    () => previousCalls.filter((call) => matchesLabel(call, metricId, filters.label)),
    [filters.label, metricId, previousCalls],
  )

  const headline = useMemo(() => {
    if (global) {
      return scoreGlobal(
        global,
        scopedCurrent,
        scopedPrevious,
        callBuckets.map((bucket) => bucket.calls.filter((call) => matchesLabel(call, metricId, filters.label))),
      )
    }
    return null
  }, [callBuckets, filters.label, global, metricId, scopedCurrent, scopedPrevious])

  const agentRows = useMemo<MetricAgentRow[]>(() => {
    const agents = agentId ? MOCK_AGENTS.filter((agent) => agent.id === agentId) : MOCK_AGENTS
    return agents
      .map((agent) => {
        const current = scopedCurrent.filter((call) => call.agentId === agent.id)
        const previous = scopedPrevious.filter((call) => call.agentId === agent.id)
        const bucketCalls = callBuckets.map((bucket) =>
          bucket.calls.filter((call) => call.agentId === agent.id && matchesLabel(call, metricId, filters.label)),
        )
        if (global) {
          const scored = scoreGlobal(global, current, previous, bucketCalls)
          if (current.length === 0) return null
          return {
            agentId: agent.id,
            agentName: agent.name,
            runs: current.length,
            display: scored.display,
            failingCount: scored.current.failingCount,
            failingRate: current.length ? scored.current.failingCount / current.length : null,
            delta: scored.delta,
            sentiment: scored.sentiment,
            points: scored.points,
          } satisfies MetricAgentRow
        }
        const currentScores = current
          .map((call) => call.metric_scores[metricId])
          .filter((score): score is NonNullable<typeof score> => Boolean(score))
        if (currentScores.length === 0) return null
        const values = current
          .map((call) => numericScore(call, metricId))
          .filter((value): value is number => value != null)
        const prevValues = previous
          .map((call) => numericScore(call, metricId))
          .filter((value): value is number => value != null)
        const avg = values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : null
        const prevAvg = prevValues.length ? prevValues.reduce((sum, value) => sum + value, 0) / prevValues.length : null
        const scoreDelta = delta(avg, prevAvg, 'mean')
        const failingCount = currentScores.filter((score) => score.failed).length
        return {
          agentId: agent.id,
          agentName: agent.name,
          runs: currentScores.length,
          display: avg == null ? '—' : avg <= 1 ? avg.toFixed(2) : String(Math.round(avg)),
          failingCount,
          failingRate: currentScores.length ? failingCount / currentScores.length : null,
          delta: scoreDelta,
          sentiment: sentiment(scoreDelta, local?.polarity ?? 'higher_is_better'),
          points: bucketCalls.map((bucket) => {
            const nums = bucket
              .map((call) => numericScore(call, metricId))
              .filter((value): value is number => value != null)
            return nums.length ? nums.reduce((sum, value) => sum + value, 0) / nums.length : null
          }),
        } satisfies MetricAgentRow
      })
      .filter((row): row is MetricAgentRow => Boolean(row))
      .sort((a, b) => b.failingCount - a.failingCount)
  }, [agentId, callBuckets, filters.label, global, local?.polarity, metricId, scopedCurrent, scopedPrevious])

  const chartPoints = useMemo<TimeChartPoint[]>(() => {
    const previousValue = headline?.previous.avg ?? local?.previousScore?.value ?? null
    return callBuckets.map((bucket, index) => {
      const scoped = bucket.calls.filter((call) => matchesLabel(call, metricId, filters.label))
      const overlayScoped = (overlayBuckets[index]?.calls ?? []).filter((call) =>
        matchesLabel(call, metricId, filters.label),
      )
      const agg = global ? aggregateCalls(scoped, global.id as GlobalMetricId, global.failRule) : null
      return {
        label: bucket.label,
        value: bucketValue(scoped, metricId, global?.id),
        min: agg?.min ?? null,
        max: agg?.max ?? null,
        previous: previousValue,
        live: bucketValue(overlayScoped, metricId, global?.id),
        since: toDayStamp(bucket.since),
        until: toDayStamp(bucket.until),
      }
    })
  }, [callBuckets, filters.label, global, headline?.previous.avg, local?.previousScore?.value, metricId, overlayBuckets])

  const selectedPoint = useMemo(
    () => chartPoints.find((point) => point.since === filters.point || point.label === filters.point) ?? null,
    [chartPoints, filters.point],
  )
  const selectedPointCalls = useMemo(() => {
    if (!selectedPoint?.since) return []
    return scopedCurrent.filter((call) => {
      const day = call.startedAt.slice(0, 10)
      return day >= (selectedPoint.since ?? '') && day <= (selectedPoint.until ?? selectedPoint.since ?? '')
    })
  }, [scopedCurrent, selectedPoint])

  const verdictInput = useMemo(() => {
    const values = global
      ? scopedCurrent.map((call) => {
          const agg = aggregateCalls([call], global.id, global.failRule)
          return agg.avg ?? 0
        })
      : scopedCurrent
          .map((call) => numericScore(call, metricId))
          .filter((value): value is number => value != null)
    const perAgentMeans = Object.fromEntries(
      agentRows.map((row) => [
        row.agentId,
        {
          name: row.agentName,
          mean: Number.parseFloat(row.display) || 0,
          count: row.runs,
        },
      ]),
    )
    const perScenarioMeans: Record<string, { name: string; mean: number; count: number }> = {}
    for (const call of scopedCurrent) {
      if (!call.scenarioId) continue
      const value = global
        ? (aggregateCalls([call], global.id, global.failRule).avg ?? 0)
        : numericScore(call, metricId)
      if (value == null) continue
      const prev = perScenarioMeans[call.scenarioId]
      if (!prev) perScenarioMeans[call.scenarioId] = { name: call.scenarioName ?? call.scenarioId, mean: value, count: 1 }
      else {
        prev.mean = (prev.mean * prev.count + value) / (prev.count + 1)
        prev.count += 1
      }
    }
    const otherMetrics = global
      ? []
      : (series?.metrics ?? [])
          .filter((metric) => metric.agg.metric_id !== metricId)
          .map((metric) => ({
            id: metric.agg.metric_id,
            name: metric.agg.metric_name,
            values: scopedCurrent
              .map((call) => numericScore(call, metric.agg.metric_id))
              .filter((value): value is number => value != null),
          }))
    return {
      values,
      perAgentMeans,
      perScenarioMeans,
      otherMetrics,
      polarity: global?.polarity ?? local?.polarity ?? 'higher_is_better',
    }
  }, [agentRows, global, local, metricId, scopedCurrent, series?.metrics])

  const verdict = verdictForMetric(verdictInput)
  const patterns = useMemo(
    () => clustersForMetric(metricId, name, scopedCurrent, clusters),
    [clusters, metricId, name, scopedCurrent],
  )
  const annotations = useMemo<ChartAnnotation[]>(() => {
    const markers = experimentMarkers(
      itemsOf<{ created_at: string; agent_id: string }>(optRuns),
      agentId,
    )
    if (metricId === 'silence_duration' || metricId === 'closing_quality') {
      markers.push({
        date: toDayStamp(new Date(Date.now() - 4 * 86400000).toISOString()),
        label: metricId === 'silence_duration' ? 'Silence break' : 'Closing break',
        kind: 'break',
      })
    }
    return markers
  }, [agentId, metricId, optRuns])
  const improvements = improvementsFor(metricId, local, clusters, agentId, calls.window.current.since, calls.window.current.until)
  const summary = buildSummary({
    name,
    range,
    source,
    agentCount: agentRows.length,
    runs: scopedCurrent.length,
    headline: headline?.display ?? local?.score.display ?? '—',
    sentiment: headline?.sentiment ?? local?.sentiment ?? 'flat',
    worst: agentRows[0],
    best: [...agentRows].sort((a, b) => a.failingCount - b.failingCount).at(-1),
  })

  const extremes = global && (global.id === 'avg_duration' || global.id === 'silence_duration')
    ? {
        min: formatGlobalValue(global, headline?.current.min ?? null),
        max: formatGlobalValue(global, headline?.current.max ?? null),
        avg: headline?.display ?? '—',
      }
    : null

  const kind = global?.kind ?? localDef?.kind
  const resolvedChart = chartType === 'line' || chartType === 'area' || chartType === 'bar' ? chartType : defaultChartType(kind)

  const categorySegments = useMemo(() => {
    if (localDef?.kind !== 'category' && localDef?.kind !== 'boolean') return []
    const counts = new Map<string, number>()
    for (const call of scopedCurrent) {
      const value = call.metric_scores[metricId]?.value
      if (value == null) continue
      const key = String(value)
      counts.set(key, (counts.get(key) ?? 0) + 1)
    }
    return [...counts.entries()].map(([label, count]) => ({ label, count }))
  }, [localDef?.kind, metricId, scopedCurrent])

  const booleanSegments = useMemo(() => {
    if (localDef?.kind !== 'boolean' && !global) return []
    const failing = scopedCurrent.filter((call) => callFailed(call, metricId)).length
    const passing = Math.max(0, scopedCurrent.length - failing)
    return [
      { label: 'Pass', count: passing },
      { label: 'Fail', count: failing },
    ]
  }, [global, localDef?.kind, metricId, scopedCurrent])

  return (
    <div className="space-y-5">
      <DrilldownBreadcrumb
        items={[
          { label: 'Metrics', onClick: onBack },
          { label: name },
        ]}
      />
      <div>
        <p className="text-xs uppercase tracking-wide text-gray-500">
          {global ? 'Global metric' : 'Local metric'}
          {filters.label ? ` · ${filters.label}` : ''}
        </p>
        <h1 className="text-2xl font-semibold text-gray-900">{name}</h1>
        <p className="mt-1 text-sm text-gray-600">{global?.description ?? local?.headline}</p>
        {extremes && (
          <p className="mt-1 text-sm text-gray-500">
            Avg {extremes.avg} · shortest {extremes.min} · longest {extremes.max}
          </p>
        )}
      </div>
      <InteractiveTimeChart
        points={chartPoints}
        source={source}
        chartType={resolvedChart === 'stacked' || resolvedChart === 'donut' || resolvedChart === 'distribution' ? 'bar' : resolvedChart}
        unitInterval={!global && (local?.score.value ?? 0) <= 1}
        title={`${name} over ${filters.since && filters.until ? `${filters.since} – ${filters.until}` : RANGE_LABELS[range]}`}
        onBrush={(nextSince, nextUntil) => filters.setParams({ since: nextSince, until: nextUntil, point: null })}
        onPointClick={(point) => filters.setParams({ point: point.since ?? point.label })}
        onChartTypeChange={setChartType}
        annotations={annotations}
      />
      {selectedPoint && (
        <PointDetailPopover
          point={selectedPoint}
          calls={selectedPointCalls}
          metricId={metricId}
          onClose={() => filters.setParams({ point: null })}
          onViewCalls={() => {
            const worst = agentRows[0]?.agentId
            filters.setParams({
              since: selectedPoint.since ?? null,
              until: selectedPoint.until ?? selectedPoint.since ?? null,
              point: null,
              failing: true,
              ...(agentId ? {} : worst ? { agent: worst } : {}),
            })
          }}
        />
      )}
      {chartType === 'distribution' || global?.kind === 'duration' ? (
        <DistributionChart
          title="Distribution"
          buckets={(headline?.current.distribution ?? []).map((bucket) => ({
            x0: bucket.x0,
            x1: bucket.x1,
            count: bucket.count,
          }))}
        />
      ) : null}
      {localDef?.kind === 'category' && categorySegments.length > 0 && (
        chartType === 'donut' ? (
          <DonutChart
            title="Label mix"
            segments={categorySegments}
            onSelect={(label) => filters.setParams({ label })}
          />
        ) : (
          <StackedShareChart
            title="Label mix"
            segments={categorySegments}
            onSelect={(label) => filters.setParams({ label })}
          />
        )
      )}
      {(localDef?.kind === 'boolean' || (global && global.id !== 'total_calls' && global.id !== 'avg_duration')) &&
        booleanSegments.some((item) => item.count > 0) && (
          <StackedShareChart title="Pass / fail" segments={booleanSegments} />
        )}
      <ScenarioBreakdown
        calls={calls.unfilteredCurrent.filter((call) => matchesLabel(call, metricId, filters.label))}
        metricId={metricId}
        selectedScenarioId={filters.scenarioId}
        onSelectScenario={(scenario) => filters.setParams({ scenario })}
      />
      <FailurePatterns clusters={patterns} agentId={agentId} metricId={metricId} />
      <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,1fr)_320px] gap-6">
        <div className="space-y-3 min-w-0">
          <h2 className="text-sm font-semibold text-gray-900">Agents</h2>
          <MetricAgentsTable rows={agentRows} source={source} onOpenAgent={onOpenAgent} />
        </div>
        <MetricInsightsPanel summary={summary} improvements={improvements} verdict={verdict} />
      </div>
    </div>
  )
}

function buildSummary(args: {
  name: string
  range: DashboardRange
  source: DashboardSource
  agentCount: number
  runs: number
  headline: string
  sentiment: string
  worst?: MetricAgentRow
  best?: MetricAgentRow
}): string {
  const trend =
    args.sentiment === 'worsening'
      ? 'worsening'
      : args.sentiment === 'improving'
        ? 'improving'
        : 'flat'
  const ends = args.worst && args.best && args.worst.agentId !== args.best.agentId
    ? ` ${args.worst.agentName} is the weakest; ${args.best.agentName} is the strongest.`
    : ''
  return `${args.name} is ${args.headline} across ${args.runs} ${args.source} calls and ${args.agentCount} agents in the last ${RANGE_LABELS[args.range]}. Trend is ${trend}.${ends}`
}

function improvementsFor(
  metricId: string,
  local: ScoredMetric | undefined,
  clusters: Awaited<ReturnType<typeof dashboardApi.getClusters>> | undefined,
  agentId: string | null,
  since: string,
  until: string,
): MetricImprovement[] {
  if (isGlobalMetricId(metricId)) {
    return (globalMetricById(metricId)?.improvementHints ?? []).map((body, index) => ({
      title: index === 0 ? 'What to try' : 'Also consider',
      body,
    }))
  }
  const group = clusters?.groups?.find((item) => item.metric_id === metricId)
  const cluster = group?.clusters[0]
  const items: MetricImprovement[] = []
  if (cluster) {
    items.push({
      title: cluster.label,
      body: cluster.observation ?? `${cluster.count} similar failures.`,
      href: `/results?tab=clusters&cluster_agent=${encodeURIComponent(agentId ?? 'mock-agent-support-eu')}&cluster_start=${since.slice(0, 10)}&cluster_end=${until.slice(0, 10)}`,
      hrefLabel: 'Open failure patterns',
    })
  }
  if (local && local.score.failureRate != null && local.score.failureRate >= 0.2) {
    items.push({
      title: 'Optimize the prompt',
      body: `${local.agg.metric_name} is failing often enough to justify a GEPA run.`,
      href: '/prompts/optimization',
      hrefLabel: 'Open optimization',
    })
  }
  if (items.length === 0) {
    items.push({
      title: 'Keep watching',
      body: 'No concentrated failure pattern yet. Re-run the suite if you change the prompt.',
      href: '/results',
      hrefLabel: 'Open results',
    })
  }
  return items
}
