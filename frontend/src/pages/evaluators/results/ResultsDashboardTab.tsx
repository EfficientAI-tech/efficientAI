import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useQuery } from '@tanstack/react-query'
import { DndContext, PointerSensor, closestCenter, useSensor, useSensors, type DragEndEvent } from '@dnd-kit/core'
import { SortableContext, rectSortingStrategy, useSortable } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { ArrowLeft, GripVertical, Loader, MoreHorizontal } from 'lucide-react'
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { apiClient } from '../../../lib/api'
import { itemsOf } from '../../../lib/safeData'
import type {
  CallImportMetricAggregate,
  DashboardOpsRunDay,
  DashboardOpsScoreDay,
  EvaluatorResultRow,
  EvaluatorResultsAgentSummary,
  EvaluatorResultsDashboardOpsResponse,
} from '../../../types/api'
import {
  dateRangeToSinceUntil,
  formatChartDayLabel,
  formatDashboardWindowLabel,
  rangeForDays,
  resultLocalDayKey,
} from './resultsDateRange'
import {
  CHART_TYPE_LABELS,
  DEFAULT_RESULTS_WIDGETS,
  WIDGET_LABELS,
  copyResultsWidgets,
  readResultsDashboardLayout,
  visibleWidgets,
  writeResultsDashboardLayout,
  type ResultsChartType,
  type ResultsWidget,
  type ResultsWidgetType,
} from './resultsDashboardLayout'
import type { DashboardDrillCall } from './resultsDashboardSample'
import {
  agentCostDetail,
  buildCategorySeries,
  categoryColors,
  formatUsd,
  isCategoricalMetric,
  formatDuration,
  modelCostDetail,
  modelTotals,
  modelsForAgent,
  shareSeries,
  toolAgentTotals,
  toolCallDetail,
  type ChartModel,
} from './resultsDashboardSeries'
import { PaginatedCallRunsTable, PaginatedRunsTable } from './resultsDashboardDrilldowns'
import {
  RunInsightBreakdown,
  RunInsightFilterBar,
  RunInsightRunsSection,
  usesRunInsightLayout,
} from './resultsDashboardRunInsightDrill'
import { InsightDrillHost } from './resultsDashboardInsightDrillHost'
import { buildRegisteredInsightCard } from './resultsDashboardInsights'
import type { MetricRow } from '../../simulations/simulationMetricScope'
import ResultsDashboardSettingsMenu from './ResultsDashboardSettingsMenu'
import { restrictToDashboardContainer } from './resultsDashboardDndModifiers'
import { insightCapabilities, resolveInsightDetail } from './resultsDashboardInsights'
import { RESULTS_DASHBOARD_TOOLBAR_SLOT_ID } from './resultsScopeTheme'
import { UsageDisplayCurrencyPicker, readUsageDisplayCurrency } from './UsageDisplayCurrencyPicker'
import type { UsageDisplayCurrency } from '../../../lib/usageCurrency'

const PRIMARY = '#ca8a04'
const SERIES_MUTED = '#9ca3af'
const FAIL = '#dc2626'
const GRID = '#e5e7eb'
/** Prefetch for breakdowns + cost call join when a detail view is open (paginated table still uses API pages). */
const TRENDS_PAGE_LIMIT = 500
const DETAIL_PREFETCH_LIMIT = 2000

interface ResultsDashboardTabProps {
  agentId: string
  suiteId: string
  scenarioId: string
  startDate: string | null
  endDate: string | null
  allTime?: boolean
  agents: EvaluatorResultsAgentSummary[]
  onSelectAgent: (agentId: string) => void
  onSelectScenario: (suiteId: string, scenarioId: string, agentId: string) => void
  onOpenRuns: () => void
  onOpenResult: (resultId: string) => void
  onDashboardAgents?: (agents: EvaluatorResultsAgentSummary[]) => void
  runSource?: 'simulation' | 'live'
  onRunSourceChange?: (source: 'simulation' | 'live') => void
}

interface DayPoint {
  day: string
  sortKey: string
  completed: number
  failed: number
}

function dayKey(iso: string, includeYear = false): { day: string; sortKey: string } {
  const sortKey = resultLocalDayKey(iso)
  return { day: formatChartDayLabel(sortKey, includeYear), sortKey }
}

function isNumericMetric(metric: CallImportMetricAggregate): boolean {
  return metric.mean != null || metric.metric_type === 'number' || metric.metric_type === 'rating'
}

function formatHeadline(value: number | null, suffix = ''): string {
  if (value == null || Number.isNaN(value)) return '—'
  return `${value.toLocaleString(undefined, { maximumFractionDigits: 1 })}${suffix}`
}

function narrowAgents(
  source: EvaluatorResultsAgentSummary[],
  agentId: string,
  suiteId: string,
  scenarioId: string,
): EvaluatorResultsAgentSummary[] {
  return source
    .filter((agent) => !agentId || agent.agent_id === agentId)
    .map((agent) => ({
      ...agent,
      suites: (agent.suites ?? [])
        .filter((suite) => !suiteId || suite.suite_id === suiteId)
        .map((suite) => ({
          ...suite,
          scenarios: (suite.scenarios ?? []).filter((scenario) => !scenarioId || scenario.scenario_id === scenarioId),
        })),
    }))
    .filter((agent) => !suiteId || (agent.suites ?? []).length > 0)
}

function withUnusedMetrics(
  scored: CallImportMetricAggregate[],
  catalog: Array<{ id?: string; name?: string; parent_metric_id?: string | null; metric_type?: string | null }>,
): CallImportMetricAggregate[] {
  const seen = new Set(scored.map((metric) => metric.metric_id))
  const unused = catalog.flatMap((metric) => {
    if (!metric.id || !metric.name || metric.parent_metric_id || seen.has(metric.id)) return []
    return [{
      metric_id: metric.id,
      metric_name: metric.name,
      metric_type: metric.metric_type ?? 'number',
      count: 0,
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
    }]
  })
  return [...scored, ...unused]
}

export default function ResultsDashboardTab({
  agentId,
  suiteId,
  scenarioId,
  startDate,
  endDate,
  allTime = false,
  agents,
  onSelectAgent,
  onSelectScenario,
  onOpenRuns,
  onOpenResult,
  onDashboardAgents,
  runSource: runSourceProp,
  onRunSourceChange,
}: ResultsDashboardTabProps) {
  const [widgets, setWidgets] = useState<ResultsWidget[]>(readResultsDashboardLayout)
  const [addOpen, setAddOpen] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [toolbarSlot, setToolbarSlot] = useState<HTMLElement | null>(null)
  const [localSource, setLocalSource] = useState<'simulation' | 'live'>('simulation')
  const source = runSourceProp ?? localSource
  const setSource = onRunSourceChange ?? setLocalSource
  const [usageDisplayCurrency, setUsageDisplayCurrency] = useState<UsageDisplayCurrency>(readUsageDisplayCurrency)
  const playground = source === 'live'
  const { data: usageFxRate } = useQuery({
    queryKey: ['org-usage', 'fx-rate', 'results-dashboard'],
    queryFn: () => apiClient.getOrgUsageFxRate(),
    staleTime: 60 * 60 * 1000,
  })
  const usageInrRate = usageFxRate?.rate ?? 95
  const [detail, setDetail] = useState<
    | { kind: 'usage'; widgetId: string }
    | { kind: 'tools'; widgetId: string }
    | { kind: 'metric_flow'; widgetId: string; agentId?: string; metricId?: string; scenarioId?: string }
    | { kind: 'total_calls_flow'; widgetId: string; agentId?: string }
    | { kind: 'widget'; widgetId: string }
    | { kind: 'metric'; metricId: string }
    | { kind: 'agent'; agentId: string }
    | null
  >(null)
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 6 } }))

  useEffect(() => {
    writeResultsDashboardLayout(widgets)
  }, [widgets])

  useLayoutEffect(() => {
    const attach = () => {
      const el = document.getElementById(RESULTS_DASHBOARD_TOOLBAR_SLOT_ID)
      setToolbarSlot((prev) => (prev === el ? prev : el))
    }
    attach()
    const frame = requestAnimationFrame(attach)
    return () => {
      cancelAnimationFrame(frame)
      setToolbarSlot(null)
    }
  }, [])

  const effectiveDateRange = useMemo(() => {
    if (allTime) return null
    if (startDate && endDate) return { start: startDate, end: endDate }
    return rangeForDays(7)
  }, [allTime, startDate, endDate])

  const dateBounds = useMemo(
    () => (
      effectiveDateRange
        ? dateRangeToSinceUntil(effectiveDateRange.start, effectiveDateRange.end)
        : { since: undefined, until: undefined }
    ),
    [effectiveDateRange],
  )

  const listParams = useMemo(
    () => ({
      agentId: agentId || undefined,
      suiteId: suiteId || undefined,
      scenarioId: scenarioId || undefined,
      since: dateBounds.since,
      until: dateBounds.until,
      playground,
      limit: detail !== null ? DETAIL_PREFETCH_LIMIT : TRENDS_PAGE_LIMIT,
    }),
    [agentId, suiteId, scenarioId, dateBounds, playground, detail],
  )

  const dashboardQueryOptions = { staleTime: 60_000 }
  const { data: listResponse } = useQuery({
    queryKey: ['evaluator-results-dashboard', listParams],
    queryFn: () => apiClient.listEvaluatorResults(listParams),
    enabled: detail !== null,
    staleTime: 60_000,
  })

  const { data: liveOps, isLoading: loadingOps } = useQuery({
    queryKey: ['evaluator-results-dashboard-ops', listParams],
    queryFn: () =>
      apiClient.getEvaluatorResultsDashboardOps({
        agentId: agentId || undefined,
        suiteId: suiteId || undefined,
        scenarioId: scenarioId || undefined,
        since: dateBounds.since,
        until: dateBounds.until,
        playground,
      }),
    ...dashboardQueryOptions,
  })

  const insightDrillAgentId = useMemo(() => {
    if (!detail) return undefined
    if (detail.kind === 'metric_flow' || detail.kind === 'total_calls_flow') {
      return detail.agentId
    }
    return undefined
  }, [detail])

  const insightScopeParams = useMemo(
    () => ({
      agentId: insightDrillAgentId || agentId || undefined,
      suiteId: suiteId || undefined,
      scenarioId: scenarioId || undefined,
      since: dateBounds.since,
      until: dateBounds.until,
      playground,
      limit: DETAIL_PREFETCH_LIMIT,
    }),
    [insightDrillAgentId, agentId, suiteId, scenarioId, dateBounds, playground],
  )

  const fetchInsightAgentScope = Boolean(insightDrillAgentId)

  const { data: insightListResponse } = useQuery({
    queryKey: ['evaluator-results-dashboard', 'insight-agent', insightScopeParams],
    queryFn: () => apiClient.listEvaluatorResults(insightScopeParams),
    enabled: fetchInsightAgentScope,
    staleTime: 60_000,
  })

  const { data: insightOpsData, isLoading: loadingInsightOps } = useQuery({
    queryKey: ['evaluator-results-dashboard-ops', 'insight-agent', insightScopeParams],
    queryFn: () =>
      apiClient.getEvaluatorResultsDashboardOps({
        agentId: insightScopeParams.agentId,
        suiteId: insightScopeParams.suiteId,
        scenarioId: insightScopeParams.scenarioId,
        since: insightScopeParams.since,
        until: insightScopeParams.until,
        playground: insightScopeParams.playground,
      }),
    ...dashboardQueryOptions,
    enabled: fetchInsightAgentScope,
  })

  const { data: metricsCatalog = [] } = useQuery({
    queryKey: ['metrics', 'agent', 'dashboard'],
    queryFn: () => apiClient.listMetrics('agent'),
    staleTime: 5 * 60_000,
  })

  const ops = liveOps
  const results = itemsOf<EvaluatorResultRow>(listResponse)
  const aggregateTotal = liveOps?.total_rows ?? 0
  const aggregateCompleted = liveOps?.completed_rows ?? 0
  const insightOps = fetchInsightAgentScope ? (insightOpsData ?? liveOps) : liveOps
  const insightResults = fetchInsightAgentScope ? itemsOf<EvaluatorResultRow>(insightListResponse) : results
  const opsForInsight = insightDrillAgentId ? insightOps : ops
  const resultsForInsight = insightDrillAgentId ? insightResults : results
  const aggregateTotalForInsight = insightDrillAgentId
    ? (insightOps?.total_rows ?? 0)
    : aggregateTotal
  const metrics = useMemo(
    () => withUnusedMetrics(liveOps?.metrics ?? [], metricsCatalog),
    [liveOps, metricsCatalog],
  )
  const metricsForInsight = useMemo(
    () => withUnusedMetrics(opsForInsight?.metrics ?? [], metricsCatalog),
    [opsForInsight, metricsCatalog],
  )
  const primaryMetric = useMemo(
    () =>
      [...metrics]
        .filter(isNumericMetric)
        .sort((a, b) => b.count - a.count)[0] ?? null,
    [metrics],
  )

  const chartDaySpansYears = useMemo(() => {
    const keys = (liveOps?.run_days ?? []).map((row) => String(row.day).slice(0, 10))
    if (keys.length < 2) return false
    return keys[0].slice(0, 4) !== keys[keys.length - 1].slice(0, 4)
  }, [liveOps])
  const days = useMemo(() => daysFromRunDays(liveOps?.run_days, chartDaySpansYears), [liveOps, chartDaySpansYears])
  const callDays = useMemo(() => callDaysFromRunDays(liveOps?.run_days, chartDaySpansYears), [liveOps, chartDaySpansYears])
  const insightChartDaySpansYears = useMemo(() => {
    const keys = (opsForInsight?.run_days ?? []).map((row) => String(row.day).slice(0, 10))
    if (keys.length < 2) return false
    return keys[0].slice(0, 4) !== keys[keys.length - 1].slice(0, 4)
  }, [opsForInsight])
  const callDaysForInsight = useMemo(
    () => callDaysFromRunDays(opsForInsight?.run_days, insightChartDaySpansYears),
    [opsForInsight, insightChartDaySpansYears],
  )
  const scoreDaysForInsight = opsForInsight?.score_days
  const duration = useMemo(() => durationFromRunDays(liveOps?.run_days, chartDaySpansYears), [liveOps, chartDaySpansYears])
  const scoreSeries = useMemo(() => scoreSeriesFromDays(liveOps?.score_days, chartDaySpansYears), [liveOps, chartDaySpansYears])
  const lowest = useMemo(() => {
    return metrics
      .filter((metric) => isNumericMetric(metric) && metric.mean != null)
      .sort((a, b) => (a.mean ?? 0) - (b.mean ?? 0))
      .slice(0, 6)
      .map((metric) => ({
        name: metric.metric_name.length > 28 ? `${metric.metric_name.slice(0, 26)}…` : metric.metric_name,
        fullName: metric.metric_name,
        metricId: metric.metric_id,
        value: Number(metric.mean?.toFixed(2)),
        count: metric.count,
      }))
  }, [metrics])

  const chartAgents = useMemo(
    () => narrowAgents(liveOps?.agents ?? agents, agentId, suiteId, scenarioId),
    [liveOps, agents, agentId, suiteId, scenarioId],
  )
  const insightAgents = useMemo(
    () =>
      narrowAgents(
        opsForInsight?.agents ?? agents,
        insightDrillAgentId || agentId,
        suiteId,
        scenarioId,
      ),
    [opsForInsight, agents, insightDrillAgentId, agentId, suiteId, scenarioId],
  )
  const insightAgentRows = useMemo(
    () =>
      insightAgents.map((agent) => ({
        id: agent.agent_id,
        name: agent.agent_name,
        total: agent.counts.total,
      })),
    [insightAgents],
  )
  const drillCallsForInsight = useMemo(
    () => drillCallsFromResults(resultsForInsight),
    [resultsForInsight],
  )
  useEffect(() => {
    if (!onDashboardAgents || !liveOps) return
    onDashboardAgents(liveOps.agents ?? [])
  }, [onDashboardAgents, liveOps])
  const scenarioMatrix = useMemo(() => buildScenarioMatrix(chartAgents), [chartAgents])
  const { childIdsByParent, childNamesById } = useMemo(() => {
    const childIdsByParent = new Map<string, string[]>()
    const childNamesById = new Map<string, string>()
    for (const metric of metricsCatalog as Array<{ id?: string; name?: string; parent_metric_id?: string | null }>) {
      if (metric.parent_metric_id && metric.id) {
        childNamesById.set(metric.id, metric.name || metric.id)
        const siblings = childIdsByParent.get(metric.parent_metric_id) ?? []
        siblings.push(metric.id)
        childIdsByParent.set(metric.parent_metric_id, siblings)
      }
    }
    return { childIdsByParent, childNamesById }
  }, [metricsCatalog])
  const categorySeries = useMemo(
    () => buildCategorySeries(results, metrics, childIdsByParent, childNamesById),
    [results, metrics, childIdsByParent, childNamesById],
  )

  const scenarioRows = useMemo(
    () => collectScenarios(chartAgents, agentId, suiteId),
    [chartAgents, agentId, suiteId],
  )
  const agentRows = useMemo(() => {
    const source = agentId ? chartAgents.filter((agent) => agent.agent_id === agentId) : chartAgents
    return [...source]
      .map((agent) => ({
        id: agent.agent_id,
        name: agent.agent_name,
        total: agent.counts.total,
        completed: agent.counts.completed,
        failed: agent.counts.failed,
        rate: agent.counts.total
          ? Math.round((agent.counts.completed / agent.counts.total) * 100)
          : 0,
      }))
      .sort((a, b) => b.total - a.total)
  }, [chartAgents, agentId])

  const shown = visibleWidgets(widgets)
  const loading = loadingOps && !liveOps

  const update = (next: ResultsWidget[]) => setWidgets(next)

  const setDisplay = (id: string, display: ResultsChartType) => {
    update(widgets.map((widget) => (widget.id === id ? { ...widget, display } : widget)))
  }

  const hideWidget = (id: string) => {
    update(widgets.map((widget) => (widget.id === id ? { ...widget, hidden: true } : widget)))
  }

  const moveWidget = (id: string, direction: -1 | 1) => {
    const visible = widgets.filter((widget) => !widget.hidden)
    const visibleIndex = visible.findIndex((widget) => widget.id === id)
    const neighbor = visible[visibleIndex + direction]
    if (!neighbor) return
    reorderWidgets(id, neighbor.id)
  }

  const reorderWidgets = (activeId: string, overId: string) => {
    if (activeId === overId) return
    const next = widgets.slice()
    const from = next.findIndex((widget) => widget.id === activeId)
    const to = next.findIndex((widget) => widget.id === overId)
    if (from < 0 || to < 0) return
    const [item] = next.splice(from, 1)
    next.splice(to, 0, item)
    update(next)
  }

  const onDragEnd = (event: DragEndEvent) => {
    const overId = event.over ? String(event.over.id) : null
    if (!overId) return
    reorderWidgets(String(event.active.id), overId)
  }

  const addWidget = (type: ResultsWidgetType, metricId?: string) => {
    if (type === 'metric_trend') {
      const nextMetric = metrics.find((metric) => metric.metric_id === metricId) ?? metrics.find((metric) => (
        !widgets.some((widget) => widget.type === 'metric_trend' && widget.metricId === metric.metric_id && !widget.hidden)
      ))
      if (!nextMetric) return
      const existing = widgets.find((widget) => widget.type === 'metric_trend' && widget.metricId === nextMetric.metric_id)
      if (existing) {
        update(widgets.map((widget) => (widget.id === existing.id ? { ...widget, hidden: false } : widget)))
      } else {
        update([
          ...widgets,
          { id: `metric_trend:${nextMetric.metric_id}`, type, display: 'line', metricId: nextMetric.metric_id },
        ])
      }
      setAddOpen(false)
      return
    }
    const existing = widgets.find((widget) => widget.type === type)
    if (existing) {
      update(widgets.map((widget) => (widget.id === existing.id ? { ...widget, hidden: false } : widget)))
    } else {
      const lineTypes: ResultsWidgetType[] = ['completion', 'avg_score', 'avg_duration', 'metric_usage', 'model_cost', 'tool_calls', 'tools', 'usage']
      update([
        ...widgets,
        {
          id: type,
          type,
          display: lineTypes.includes(type) ? (type === 'model_cost' ? 'area' : 'line') : 'bar',
        },
      ])
    }
    setAddOpen(false)
  }

  const setMetric = (id: string, metricId: string) => {
    update(widgets.map((widget) => (widget.id === id ? { ...widget, metricId } : widget)))
  }

  const metricCatalogRows = useMemo(
    () => (metricsCatalog as MetricRow[]).map((row) => ({
      id: row.id,
      name: row.name,
      agent_ids: row.agent_ids,
      scenario_ids: row.scenario_ids,
      parent_metric_id: row.parent_metric_id,
    })),
    [metricsCatalog],
  )
  const drillCalls = drillCallsFromResults(results)
  const runListBase = {
    agentId: agentId || undefined,
    suiteId: suiteId || undefined,
    scenarioId: scenarioId || undefined,
    since: dateBounds.since,
    until: dateBounds.until,
    playground,
    sampleOn: false,
    sampleRows: [] as EvaluatorResultRow[],
  }
  const openWidgetDetail = (widget: ResultsWidget) => {
    setDetail(resolveInsightDetail(widget) ?? { kind: 'widget', widgetId: widget.id })
  }

  const dashboardSettingsPortal = toolbarSlot
    ? createPortal(
      <ResultsDashboardSettingsMenu
        open={settingsOpen}
        onOpenChange={setSettingsOpen}
        source={source}
        onSourceChange={setSource}
        metrics={metrics}
        widgets={widgets}
        addOpen={addOpen}
        setAddOpen={setAddOpen}
        onAddWidget={addWidget}
        onResetLayout={() => update(copyResultsWidgets(DEFAULT_RESULTS_WIDGETS))}
      />,
      toolbarSlot,
    )
    : null

  if (loading) {
    return (
      <>
        {dashboardSettingsPortal}
        <div className="flex items-center justify-center py-16 text-gray-500">
          <Loader className="mr-2 h-5 w-5 animate-spin" />
          Loading dashboard…
        </div>
      </>
    )
  }

  if (
    detail
    && (detail.kind === 'usage'
      || detail.kind === 'tools'
      || detail.kind === 'metric_flow'
      || detail.kind === 'total_calls_flow')
  ) {
    const insightLoading = fetchInsightAgentScope && loadingInsightOps && !insightOpsData
    if (insightLoading) {
      return (
        <>
          {dashboardSettingsPortal}
          <div className="flex items-center justify-center py-16 text-gray-500">
            <Loader className="mr-2 h-5 w-5 animate-spin" />
            Loading agent summary…
          </div>
        </>
      )
    }
    return (
      <>
        {dashboardSettingsPortal}
        <InsightDrillHost
          detail={detail}
          runListBase={{
            ...runListBase,
            agentId: insightDrillAgentId || runListBase.agentId,
          }}
          onBack={() => setDetail(null)}
          onOpenResult={onOpenResult}
          ops={opsForInsight}
          calls={drillCallsForInsight}
          agents={insightAgents}
          metrics={metricsForInsight}
          catalog={metricCatalogRows}
          scoreDays={scoreDaysForInsight}
          dateRange={effectiveDateRange}
          allTime={allTime}
          results={resultsForInsight}
          agentRows={insightAgentRows}
          callDays={insightDrillAgentId ? callDaysForInsight : callDays}
          aggregateTotal={aggregateTotalForInsight}
          onMetricNavigate={(next) => setDetail({ kind: 'metric_flow', widgetId: detail.widgetId, ...next })}
          onTotalCallsNavigate={(agentId) => setDetail({ kind: 'total_calls_flow', widgetId: detail.widgetId, agentId })}
        />
      </>
    )
  }

  if (detail) {
    return (
      <>
        {dashboardSettingsPortal}
        <ResultsDetailView
          detail={detail}
          widgets={widgets}
          metrics={metrics}
          dateRange={effectiveDateRange}
          allTime={allTime}
          days={days}
          duration={duration}
          scenarioMatrix={scenarioMatrix}
          scoreSeries={scoreSeries}
          categorySeries={categorySeries}
          ops={ops}
          lowest={lowest}
          agentRows={agentRows}
          scenarioRows={scenarioRows}
          primaryMetric={primaryMetric}
          results={results}
          aggregateTotal={aggregateTotal}
          aggregateCompleted={aggregateCompleted}
          onBack={() => setDetail(null)}
          onOpenMetric={(metricId) => setDetail({ kind: 'metric', metricId })}
          onSelectAgent={(id) => {
            onSelectAgent(id)
            setDetail(null)
          }}
          onSelectScenario={(nextSuiteId, nextScenarioId, nextAgentId) => {
            onSelectScenario(nextSuiteId, nextScenarioId, nextAgentId)
            setDetail(null)
          }}
          onOpenRuns={onOpenRuns}
          onOpenResult={onOpenResult}
          runListBase={runListBase}
          drillCalls={drillCalls}
          onMetric={(metricId) => {
            if (detail.kind === 'widget') setMetric(detail.widgetId, metricId)
          }}
        />
      </>
    )
  }

  return (
    <div className="min-w-0 max-w-full space-y-4 overflow-x-clip">
      {dashboardSettingsPortal}

      {shown.length === 0 ? (
        <div className="rounded-xl border border-gray-200 bg-white p-12 text-center">
          <p className="text-sm font-medium text-gray-900">No charts on this dashboard</p>
          <p className="mt-1 text-sm text-gray-500">Add a chart or reset the layout.</p>
        </div>
      ) : (
        <DndContext
          sensors={sensors}
          collisionDetection={closestCenter}
          onDragEnd={onDragEnd}
          modifiers={[restrictToDashboardContainer]}
          autoScroll={{
            layoutShiftCompensation: { x: false, y: true },
            threshold: { x: 0, y: 0.12 },
          }}
        >
          <SortableContext items={shown.map((widget) => widget.id)} strategy={rectSortingStrategy}>
            <div className="grid w-full min-w-0 max-w-full grid-cols-1 gap-4 overflow-x-clip md:grid-cols-2 xl:grid-cols-3">
              {shown.map((widget) => (
                <DashboardPanel
                  key={widget.id}
                  widget={widget}
                  canMoveUp={shown.findIndex((item) => item.id === widget.id) > 0}
                  canMoveDown={shown.findIndex((item) => item.id === widget.id) < shown.length - 1}
                  metrics={metrics}
                  days={days}
                  duration={duration}
                  scenarioMatrix={scenarioMatrix}
                  scoreSeries={scoreSeries}
                  categorySeries={categorySeries}
                  ops={ops}
                  lowest={lowest}
                  agentRows={agentRows}
                  scenarioRows={scenarioRows}
                  primaryMetric={primaryMetric}
                  aggregateTotal={aggregateTotal}
                  aggregateCompleted={aggregateCompleted}
                  onDisplay={(display) => setDisplay(widget.id, display)}
                  onHide={() => hideWidget(widget.id)}
                  onMove={(direction) => moveWidget(widget.id, direction)}
                  onMetric={(metricId) => setMetric(widget.id, metricId)}
                  onOpenDetail={() => openWidgetDetail(widget)}
                  onOpenAgent={(id) => setDetail({ kind: 'agent', agentId: id })}
                  usageDisplayCurrency={usageDisplayCurrency}
                  usageInrRate={usageInrRate}
                  onUsageDisplayCurrencyChange={setUsageDisplayCurrency}
                />
              ))}
            </div>
          </SortableContext>
        </DndContext>
      )}
      <MetricAgentsTable
        agents={chartAgents}
        results={results}
        ops={ops}
        onOpenAgent={(id) => setDetail({ kind: 'agent', agentId: id })}
      />
    </div>
  )
}

function labelDay(iso: string, includeYear = false): { day: string; sortKey: string } {
  const sortKey = iso.slice(0, 10)
  return { day: formatChartDayLabel(sortKey, includeYear), sortKey }
}

function daysFromRunDays(rows: DashboardOpsRunDay[] | undefined, includeYear = false): DayPoint[] {
  return (rows ?? [])
    .map((row) => {
      const labeled = labelDay(row.day, includeYear)
      return { day: labeled.day, sortKey: labeled.sortKey, completed: row.completed, failed: row.failed }
    })
    .sort((a, b) => a.sortKey.localeCompare(b.sortKey))
}

function callDaysFromRunDays(rows: DashboardOpsRunDay[] | undefined, includeYear = false): Array<{ day: string; calls: number }> {
  return daysFromRunDays(rows, includeYear).map((row) => ({ day: row.day, sortKey: row.sortKey, calls: row.completed + row.failed }))
}

function durationFromRunDays(rows: DashboardOpsRunDay[] | undefined, includeYear = false): { average: number | null; points: Array<{ day: string; value: number }> } {
  let sum = 0
  let count = 0
  const points = [...(rows ?? [])]
    .sort((a, b) => a.day.localeCompare(b.day))
    .map((row) => {
      sum += row.duration_seconds
      count += row.duration_count
      return {
        day: labelDay(row.day, includeYear).day,
        sortKey: labelDay(row.day, includeYear).sortKey,
        value: row.duration_count ? Number((row.duration_seconds / row.duration_count).toFixed(1)) : 0,
      }
    })
  return { average: count ? sum / count : null, points }
}

function scoreSeriesFromDays(rows: DashboardOpsScoreDay[] | undefined, includeYear = false) {
  const series = new Map<string, Array<{ day: string; value: number; sortKey: string }>>()
  for (const row of rows ?? []) {
    if (!row.score_count) continue
    const labeled = labelDay(row.day, includeYear)
    const points = series.get(row.metric_id) ?? []
    points.push({
      day: labeled.day,
      sortKey: labeled.sortKey,
      value: Number((row.score_sum / row.score_count).toFixed(2)),
    })
    series.set(row.metric_id, points)
  }
  const out = new Map<string, Array<{ day: string; value: number }>>()
  for (const [metricId, points] of series) {
    points.sort((a, b) => a.sortKey.localeCompare(b.sortKey))
    out.set(metricId, points.map(({ day, value }) => ({ day, value })))
  }
  return out
}

function buildScenarioMatrix(agents: EvaluatorResultsAgentSummary[]): Array<{ agentName: string; scenarioName: string; count: number }> {
  const rows: Array<{ agentName: string; scenarioName: string; count: number }> = []
  for (const agent of agents) {
    for (const suite of agent.suites ?? []) {
      for (const scenario of suite.scenarios ?? []) {
        rows.push({
          agentName: agent.agent_name,
          scenarioName: scenario.scenario_name,
          count: scenario.counts.total,
        })
      }
    }
  }
  return rows
}

function collectScenarios(
  agents: EvaluatorResultsAgentSummary[],
  agentId: string,
  suiteId: string,
) {
  const rows: Array<{
    name: string
    count: number
    completed: number
    failed: number
    suiteId: string
    scenarioId: string
    agentId: string
  }> = []
  for (const agent of agents) {
    if (agentId && agent.agent_id !== agentId) continue
    for (const suite of agent.suites ?? []) {
      if (suiteId && suite.suite_id !== suiteId) continue
      for (const scenario of suite.scenarios ?? []) {
        rows.push({
          name: scenario.scenario_name,
          count: scenario.counts.total,
          completed: scenario.counts.completed,
          failed: scenario.counts.failed,
          suiteId: suite.suite_id,
          scenarioId: scenario.scenario_id,
          agentId: agent.agent_id,
        })
      }
    }
  }
  return rows.sort((a, b) => b.count - a.count).slice(0, 8)
}

function DashboardPanel({
  widget,
  canMoveUp,
  canMoveDown,
  metrics,
  days,
  duration,
  scenarioMatrix,
  scoreSeries,
  categorySeries,
  ops,
  lowest,
  agentRows,
  scenarioRows,
  primaryMetric,
  aggregateTotal,
  aggregateCompleted,
  onDisplay,
  onHide,
  onMove,
  onMetric,
  onOpenDetail,
  onOpenAgent,
  usageDisplayCurrency,
  usageInrRate,
  onUsageDisplayCurrencyChange,
}: {
  widget: ResultsWidget
  canMoveUp: boolean
  canMoveDown: boolean
  metrics: CallImportMetricAggregate[]
  days: DayPoint[]
  duration: { average: number | null; points: Array<{ day: string; value: number }> }
  scenarioMatrix: Array<{ agentName: string; scenarioName: string; count: number }>
  scoreSeries: Map<string, Array<{ day: string; value: number }>>
  categorySeries: Map<string, { labels: string[]; data: Array<Record<string, string | number>> }>
  ops: EvaluatorResultsDashboardOpsResponse | undefined
  lowest: Array<{ name: string; value: number; count?: number; metricId?: string }>
  agentRows: Array<{ id: string; name: string; total: number; completed: number; failed: number; rate: number }>
  scenarioRows: Array<{ name: string; count: number; completed: number; failed: number; suiteId: string; scenarioId: string; agentId: string }>
  primaryMetric: CallImportMetricAggregate | null
  aggregateTotal: number
  aggregateCompleted: number
  onDisplay: (display: ResultsChartType) => void
  onHide: () => void
  onMove: (direction: -1 | 1) => void
  onMetric: (metricId: string) => void
  onOpenDetail: () => void
  onOpenAgent: (agentId: string) => void
  usageDisplayCurrency: UsageDisplayCurrency
  usageInrRate: number
  onUsageDisplayCurrencyChange: (currency: UsageDisplayCurrency) => void
}) {
  const [menuOpen, setMenuOpen] = useState(false)
  const showCurrencyMenu = Boolean(insightCapabilities(widget.type)?.currency)
  const menuRef = useRef<HTMLDivElement>(null)
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id: widget.id })

  useEffect(() => {
    if (!menuOpen) return
    const close = (event: MouseEvent) => {
      if (!menuRef.current?.contains(event.target as Node)) setMenuOpen(false)
    }
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [menuOpen])

  const trendMetric = metrics.find((metric) => metric.metric_id === widget.metricId) ?? primaryMetric
  const model = buildRegisteredInsightCard(widget, {
    widget,
    days,
    duration,
    scenarioMatrix,
    scoreSeries,
    categorySeries,
    ops,
    lowest,
    agentRows,
    scenarioRows,
    primaryMetric,
    trendMetric,
    aggregateTotal,
    aggregateCompleted,
    usageCurrency: usageDisplayCurrency,
    usageInrRate,
  })

  return (
    <section
      ref={setNodeRef}
      style={{ transform: CSS.Transform.toString(transform), transition, opacity: isDragging ? 0.55 : 1 }}
      className={`relative flex min-h-[280px] min-w-0 max-w-full flex-col overflow-hidden rounded-xl border border-gray-200 bg-white p-4 shadow-sm ${isDragging ? 'z-20 touch-none' : ''}`}
    >
      <div className="mb-3 flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-1">
          <button
            type="button"
            className="mt-0.5 cursor-grab rounded p-0.5 text-gray-300 hover:text-gray-600 active:cursor-grabbing"
            aria-label={`Drag ${WIDGET_LABELS[widget.type]}`}
            {...attributes}
            {...listeners}
          >
            <GripVertical className="h-3.5 w-3.5" />
          </button>
          <div className="min-w-0">
            <h3 className="text-sm font-semibold text-gray-900">{WIDGET_LABELS[widget.type]}</h3>
            <p className="mt-1 text-2xl font-semibold tracking-tight text-gray-900">{model.headline}</p>
            {model.caption && <p className="mt-0.5 text-xs text-gray-500">{model.caption}</p>}
          </div>
        </div>
        <div className="relative" ref={menuRef}>
          <button
            type="button"
            aria-label={`${WIDGET_LABELS[widget.type]} options`}
            onClick={() => setMenuOpen((open) => !open)}
            className="rounded-md p-1 text-gray-400 hover:bg-gray-50 hover:text-gray-700"
          >
            <MoreHorizontal className="h-4 w-4" />
          </button>
          {menuOpen && (
            <div
              className="absolute right-0 z-20 mt-1 w-36 rounded-lg border border-gray-200 bg-white py-1 shadow-lg"
              onPointerDown={(event) => event.stopPropagation()}
            >
              {(['line', 'bar', 'area'] as ResultsChartType[]).map((type) => (
                <button
                  key={type}
                  type="button"
                  onClick={() => {
                    onDisplay(type)
                    setMenuOpen(false)
                  }}
                  className={`block w-full px-3 py-1.5 text-left text-xs ${widget.display === type ? 'text-gray-900' : 'text-gray-600 hover:bg-gray-50'
                    }`}
                >
                  {CHART_TYPE_LABELS[type]}
                </button>
              ))}
              {showCurrencyMenu ? (
                <>
                  <div className="my-1 border-t border-gray-100" />
                  <UsageDisplayCurrencyPicker
                    value={usageDisplayCurrency}
                    onChange={onUsageDisplayCurrencyChange}
                  />
                </>
              ) : null}
              <div className="my-1 border-t border-gray-100" />
              <button type="button" disabled={!canMoveUp} onClick={() => onMove(-1)} className="block w-full px-3 py-1.5 text-left text-xs text-gray-600 hover:bg-gray-50 disabled:text-gray-300">
                Move up
              </button>
              <button type="button" disabled={!canMoveDown} onClick={() => onMove(1)} className="block w-full px-3 py-1.5 text-left text-xs text-gray-600 hover:bg-gray-50 disabled:text-gray-300">
                Move down
              </button>
              <button type="button" onClick={onHide} className="block w-full px-3 py-1.5 text-left text-xs text-gray-600 hover:bg-gray-50">
                Hide
              </button>
            </div>
          )}
        </div>
      </div>

      {widget.type === 'metric_trend' && (
        <select
          value={trendMetric?.metric_id ?? ''}
          onChange={(event) => onMetric(event.target.value)}
          className="mb-3 w-full rounded-lg border border-gray-200 bg-white px-2 py-1.5 text-xs text-gray-700"
        >
          {metrics.map((metric) => (
            <option key={metric.metric_id} value={metric.metric_id}>
              {metric.metric_name}
            </option>
          ))}
        </select>
      )}

      {widget.type === 'agents' && widget.display === 'bar' ? (
        <div className="cursor-pointer [&_.recharts-surface]:cursor-pointer" onClick={onOpenDetail}>
          <AgentTable rows={agentRows} onSelect={onOpenAgent} />
          <span className="mt-2 block text-[11px] font-medium text-gray-400">Show details</span>
        </div>
      ) : model.data.length === 0 ? (
        <button type="button" onClick={onOpenDetail} className="flex flex-1 flex-col items-center justify-center gap-2 text-sm text-gray-400">
          <span>No data in this window</span>
          <span className="text-[11px] font-medium">Show details</span>
        </button>
      ) : (
        <div onClick={onOpenDetail} className="relative min-h-[160px] min-w-0 max-w-full flex-1 overflow-hidden cursor-pointer text-left [&_.recharts-surface]:cursor-pointer">
          <PanelChart
            display={widget.display}
            data={model.data}
            series={model.series}
            layout={resolvePanelChartLayout(model, widget.display)}
            onPoint={() => onOpenDetail()}
            onCategory={() => onOpenDetail()}
          />
          <span className="mt-2 block text-[11px] font-medium text-gray-400">Show details</span>
        </div>
      )}
    </section>
  )
}

function resolvePanelChartLayout(
  model: {
    horizontal?: boolean
    series: Array<{ key: string; color: string; stack?: string }>
  },
  display: ResultsChartType,
): 'stacked' | 'vertical' | 'horizontal' {
  const stacked = model.series.some((item) => item.stack)
  if (stacked) return 'stacked'
  if (model.horizontal && display === 'bar') return 'vertical'
  return 'horizontal'
}

function PanelChart({
  display,
  data,
  series,
  layout,
  onPoint,
  onCategory,
  listClassName = 'max-h-[200px]',
}: {
  display: ResultsChartType
  data: Array<Record<string, string | number>>
  series: Array<{ key: string; color: string; stack?: string }>
  layout: 'horizontal' | 'vertical' | 'stacked'
  onPoint: (label: string, sortKey: string, detail: string) => void
  onCategory: (name: string) => void
  listClassName?: string
}) {
  const categoryKey = data[0] && 'name' in data[0] ? 'name' : 'day'
  const handleClick = (state: {
    activeLabel?: string | number
    activePayload?: Array<{ name?: string; value?: number; payload?: Record<string, unknown> }>
  }) => {
    if (state?.activeLabel == null) return
    const label = String(state.activeLabel)
    const detail = (state.activePayload ?? [])
      .map((item) => `${item.name}: ${item.value ?? 0}`)
      .join(' · ')
    if (categoryKey === 'name') {
      onCategory(label)
      return
    }
    const payload = state.activePayload?.[0]?.payload
    const sortKey = payload && payload.sortKey != null ? String(payload.sortKey) : label
    onPoint(label, sortKey, detail || 'No values')
  }

  const grid = <CartesianGrid stroke={GRID} vertical={false} />
  const tooltip = <Tooltip content={<BreakdownTooltip />} cursor={{ fill: '#f9fafb' }} />

  if (layout === 'stacked') {
    const stackId = series[0]?.stack ?? 'stack'
    const barHeight = Math.min(240, Math.max(160, data.length * 36))
    if (display === 'line') {
      return (
        <ResponsiveContainer width="100%" height={barHeight}>
          <LineChart data={data} onClick={handleClick}>
            {grid}
            <XAxis dataKey={categoryKey} tick={{ fontSize: 11, fill: '#6b7280' }} axisLine={false} tickLine={false} />
            <YAxis tick={{ fontSize: 11, fill: '#6b7280' }} axisLine={false} tickLine={false} width={32} />
            {tooltip}
            {series.map((item) => (
              <Line key={item.key} type="monotone" dataKey={item.key} stroke={item.color} strokeWidth={1.75} dot={false} />
            ))}
          </LineChart>
        </ResponsiveContainer>
      )
    }
    if (display === 'area') {
      return (
        <ResponsiveContainer width="100%" height={barHeight}>
          <AreaChart data={data} onClick={handleClick}>
            {grid}
            <XAxis dataKey={categoryKey} tick={{ fontSize: 11, fill: '#6b7280' }} axisLine={false} tickLine={false} />
            <YAxis tick={{ fontSize: 11, fill: '#6b7280' }} axisLine={false} tickLine={false} width={32} />
            {tooltip}
            {series.map((item) => (
              <Area
                key={item.key}
                type="monotone"
                dataKey={item.key}
                stroke={item.color}
                fill={item.color}
                fillOpacity={0.12}
                stackId={stackId}
                strokeWidth={1.75}
              />
            ))}
          </AreaChart>
        </ResponsiveContainer>
      )
    }
    return (
      <ResponsiveContainer width="100%" height={barHeight}>
        <BarChart layout="vertical" data={data} margin={{ top: 4, right: 12, left: 4, bottom: 4 }}>
          <XAxis type="number" hide />
          <YAxis type="category" dataKey="name" width={120} tick={{ fontSize: 11, fill: '#4b5563' }} />
          <Tooltip content={<BreakdownTooltip />} cursor={{ fill: '#f9fafb' }} />
          {series.map((item) => (
            <Bar
              key={item.key}
              dataKey={item.key}
              name={item.key}
              stackId={stackId}
              fill={item.color}
              barSize={18}
              onClick={(state) => {
                const name = (state as { name?: string })?.name
                if (name) onCategory(name)
              }}
            />
          ))}
        </BarChart>
      </ResponsiveContainer>
    )
  }

  if (layout === 'vertical') {
    const valueKey = series[0]?.key ?? 'count'
    const color = series[0]?.color ?? PRIMARY
    const max = Math.max(...data.map((row) => Number(row[valueKey]) || 0), 1)
    const multiSeries = series.length > 1
    if (multiSeries) {
      const barHeight = Math.min(240, Math.max(160, data.length * 36))
      return (
        <ResponsiveContainer width="100%" height={barHeight}>
          <BarChart layout="vertical" data={data} margin={{ top: 4, right: 12, left: 4, bottom: 4 }}>
            <XAxis type="number" hide />
            <YAxis type="category" dataKey="name" width={120} tick={{ fontSize: 11, fill: '#4b5563' }} />
            {tooltip}
            {series.map((item) => (
              <Bar
                key={item.key}
                dataKey={item.key}
                fill={item.color}
                barSize={16}
                radius={[0, 3, 3, 0]}
                onClick={(state) => {
                  const name = (state as { name?: string })?.name
                  if (name) onCategory(name)
                }}
              />
            ))}
          </BarChart>
        </ResponsiveContainer>
      )
    }
    return (
      <ul className={`space-y-2.5 overflow-y-auto pr-1 ${listClassName}`}>
        {data.map((row, index) => {
          const name = String(row.name ?? '')
          const value = Number(row[valueKey]) || 0
          return (
            <li key={`${name}-${index}`}>
              <button
                type="button"
                title={name}
                onClick={(event) => {
                  event.stopPropagation()
                  onCategory(name)
                }}
                className="w-full cursor-pointer text-left"
              >
                <span className="flex items-baseline justify-between gap-3">
                  <span className="min-w-0 truncate text-xs font-medium text-gray-800">{name}</span>
                  <span className="shrink-0 text-xs tabular-nums text-gray-500">{value.toLocaleString()}</span>
                </span>
                <span className="mt-1 block h-1.5 overflow-hidden rounded-full bg-gray-100">
                  <span className="block h-full rounded-full" style={{ width: `${Math.max((value / max) * 100, value > 0 ? 4 : 0)}%`, backgroundColor: color }} />
                </span>
              </button>
            </li>
          )
        })}
      </ul>
    )
  }

  if (display === 'line') {
    return (
      <ResponsiveContainer width="100%" height={180}>
        <LineChart data={data} onClick={handleClick}>
          {grid}
          <XAxis dataKey={categoryKey} tick={{ fontSize: 11, fill: '#6b7280' }} axisLine={false} tickLine={false} />
          <YAxis tick={{ fontSize: 11, fill: '#6b7280' }} axisLine={false} tickLine={false} width={32} />
          {tooltip}
          {series.map((item) => (
            <Line key={item.key} type="monotone" dataKey={item.key} stroke={item.color} strokeWidth={1.75} dot={false} />
          ))}
        </LineChart>
      </ResponsiveContainer>
    )
  }

  if (display === 'area') {
    return (
      <ResponsiveContainer width="100%" height={180}>
        <AreaChart data={data} onClick={handleClick}>
          {grid}
          <XAxis dataKey={categoryKey} tick={{ fontSize: 11, fill: '#6b7280' }} axisLine={false} tickLine={false} />
          <YAxis tick={{ fontSize: 11, fill: '#6b7280' }} axisLine={false} tickLine={false} width={32} />
          {tooltip}
          {series.map((item) => (
            <Area
              key={item.key}
              type="monotone"
              dataKey={item.key}
              stroke={item.color}
              fill={item.color}
              fillOpacity={0.12}
              stackId={item.stack}
              strokeWidth={1.75}
            />
          ))}
        </AreaChart>
      </ResponsiveContainer>
    )
  }

  return (
    <ResponsiveContainer width="100%" height={180}>
      <BarChart data={data} onClick={handleClick}>
        {grid}
        <XAxis dataKey={categoryKey} tick={{ fontSize: 11, fill: '#6b7280' }} axisLine={false} tickLine={false} />
        <YAxis tick={{ fontSize: 11, fill: '#6b7280' }} axisLine={false} tickLine={false} width={32} />
        {tooltip}
        {series.map((item) => (
          <Bar key={item.key} dataKey={item.key} fill={item.color} stackId={item.stack} radius={[3, 3, 0, 0]} maxBarSize={28} />
        ))}
      </BarChart>
    </ResponsiveContainer>
  )
}

function AgentTable({
  rows,
  onSelect,
}: {
  rows: Array<{ id: string; name: string; total: number; completed: number; failed: number; rate: number }>
  onSelect: (agentId: string) => void
}) {
  if (!rows.length) {
    return <p className="flex flex-1 items-center justify-center text-sm text-gray-400">No agents in this window</p>
  }
  return (
    <div className="overflow-auto">
      <table className="w-full text-left text-xs">
        <thead className="text-gray-400">
          <tr>
            <th className="pb-2 font-medium">Agent</th>
            <th className="pb-2 text-right font-medium">Runs</th>
            <th className="pb-2 text-right font-medium">Rate</th>
          </tr>
        </thead>
        <tbody>
          {rows.slice(0, 6).map((row) => (
            <tr key={row.id} className="border-t border-gray-100">
              <td className="py-2">
                <button
                  type="button"
                  onClick={(event) => {
                    event.stopPropagation()
                    onSelect(row.id)
                  }}
                  className="truncate text-left font-medium text-gray-900 hover:text-primary-700"
                >
                  {row.name}
                </button>
              </td>
              <td className="py-2 text-right text-gray-600">{row.total}</td>
              <td className="py-2 text-right text-gray-600">{row.rate}%</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function buildDetailViews(
  type: ResultsWidgetType | undefined,
  model: ChartModel | null,
  days: DayPoint[],
  lowest: Array<{ name: string; value: number; count?: number }>,
  agentRows: Array<{ name: string; total: number; rate: number }>,
  scenarioRows: Array<{ name: string; count: number; completed: number; failed: number }>,
  metric: CallImportMetricAggregate | null,
): Array<{
  id: string
  label: string
  headline: string
  caption?: string
  data: Array<Record<string, string | number>>
  series: Array<{ key: string; color: string; stack?: string }>
  horizontal?: boolean
}> {
  if (!model) return []
  if (!type) {
    return [{ id: 'main', label: 'Average', headline: model.headline, caption: model.caption, data: model.data, series: model.series, horizontal: model.horizontal }]
  }
  if (type === 'volume') {
    const completed = days.reduce((sum, day) => sum + day.completed, 0)
    const failed = days.reduce((sum, day) => sum + day.failed, 0)
    return [
      {
        id: 'both',
        label: 'Both',
        headline: model.headline,
        caption: 'Completed and failed',
        data: days.map((day) => ({ day: day.day, sortKey: day.sortKey, completed: day.completed, failed: day.failed })),
        series: model.series,
      },
      { id: 'completed', label: 'Completed', headline: formatHeadline(completed), caption: 'Completed runs', data: days.map((day) => ({ day: day.day, sortKey: day.sortKey, completed: day.completed })), series: [{ key: 'completed', color: PRIMARY }] },
      { id: 'failed', label: 'Failed', headline: formatHeadline(failed), caption: 'Failed runs', data: days.map((day) => ({ day: day.day, sortKey: day.sortKey, failed: day.failed })), series: [{ key: 'failed', color: FAIL }] },
    ]
  }
  if (type === 'completion') {
    return [
      {
        id: 'rate',
        label: 'Rate',
        headline: model.headline,
        caption: 'Completion rate',
        data: days.map((day) => {
          const denom = day.completed + day.failed
          return {
            day: day.day,
            sortKey: day.sortKey,
            rate: denom ? Math.round((day.completed / denom) * 100) : 0,
          }
        }),
        series: model.series,
      },
      { id: 'counts', label: 'Counts', headline: formatHeadline(days.reduce((sum, day) => sum + day.completed + day.failed, 0)), caption: 'Completed and failed counts', data: days.map((day) => ({ day: day.day, sortKey: day.sortKey, completed: day.completed, failed: day.failed })), series: [{ key: 'completed', color: PRIMARY, stack: 'runs' }, { key: 'failed', color: FAIL, stack: 'runs' }] },
    ]
  }
  if (type === 'total_calls' || type === 'avg_duration' || type === 'scenarios_by_agent') {
    return [{ id: 'main', label: 'Chart', headline: model.headline, caption: model.caption, data: model.data, series: model.series, horizontal: model.horizontal }]
  }
  if (type === 'avg_score' || type === 'metric_trend' || type === 'metric_usage') {
    const distribution = (metric?.histogram_buckets ?? []).map((bucket) => ({
      name: `${bucket.x0.toFixed(1)}–${bucket.x1.toFixed(1)}`,
      count: bucket.count,
    }))
    const views = [
      { id: 'average', label: 'Average', headline: model.headline, caption: model.caption, data: model.data, series: model.series },
    ]
    if (distribution.length) {
      views.push({ id: 'distribution', label: 'Distribution', headline: formatHeadline(metric?.count ?? null), caption: 'Score buckets', data: distribution, series: [{ key: 'count', color: PRIMARY }] })
    }
    return views
  }
  if (type === 'lowest_metrics') {
    return [
      { id: 'score', label: 'Score', headline: model.headline, caption: 'Lowest mean', data: model.data, series: model.series, horizontal: true },
      { id: 'samples', label: 'Samples', headline: formatHeadline(lowest.reduce((sum, row) => sum + (row.count ?? 0), 0)), caption: 'Rows scored', data: lowest.map((row) => ({ name: row.name, count: row.count ?? 0 })), series: [{ key: 'count', color: SERIES_MUTED }], horizontal: true },
    ]
  }
  if (type === 'agents') {
    return [
      { id: 'runs', label: 'Runs', headline: model.headline, caption: 'Runs by agent', data: agentRows.map((row) => ({ name: row.name, total: row.total })), series: [{ key: 'total', color: PRIMARY }], horizontal: true },
      { id: 'rate', label: 'Completion', headline: model.headline, caption: 'Completion rate', data: agentRows.map((row) => ({ name: row.name, rate: row.rate })), series: [{ key: 'rate', color: PRIMARY }], horizontal: true },
    ]
  }
  return [
    { id: 'runs', label: 'Runs', headline: model.headline, caption: 'Scenario runs', data: scenarioRows.map((row) => ({ name: row.name, count: row.count })), series: [{ key: 'count', color: PRIMARY }], horizontal: true },
    { id: 'completed', label: 'Completed', headline: formatHeadline(scenarioRows.reduce((sum, row) => sum + row.completed, 0)), caption: 'Completed scenario runs', data: scenarioRows.map((row) => ({ name: row.name, completed: row.completed })), series: [{ key: 'completed', color: PRIMARY }], horizontal: true },
    { id: 'failed', label: 'Failed', headline: formatHeadline(scenarioRows.reduce((sum, row) => sum + row.failed, 0)), caption: 'Failed scenario runs', data: scenarioRows.map((row) => ({ name: row.name, failed: row.failed })), series: [{ key: 'failed', color: FAIL }], horizontal: true },
  ]
}

function usesPaginatedRunLeaf(
  detail: { kind: 'widget'; widgetId: string } | { kind: 'metric'; metricId: string } | { kind: 'agent'; agentId: string },
  widget: ResultsWidget | null | undefined,
): boolean {
  if (detail.kind === 'agent' || detail.kind === 'metric') return true
  if (detail.kind !== 'widget' || !widget) return false
  return [
    'completion',
    'avg_duration',
    'total_calls',
    'scenarios',
    'scenarios_by_agent',
    'volume',
    'metric_trend',
    'avg_score',
    'agent_cost',
  ].includes(widget.type)
}

function usesCallRunLeaf(widget: ResultsWidget | null | undefined): boolean {
  return widget?.type === 'model_cost'
}

function runTableTitle({
  windowLabel,
  drillDayLabel,
  activeScenarioName,
  agentName,
}: {
  windowLabel: string
  drillDayLabel: string | null
  activeScenarioName: string | null
  agentName?: string
}): string {
  const parts = ['Runs']
  if (agentName) parts.push(agentName)
  if (activeScenarioName) parts.push(activeScenarioName)
  if (drillDayLabel) parts.push(drillDayLabel)
  if (parts.length === 1) parts.push(windowLabel)
  return parts.join(' · ')
}

function ResultsDetailView({
  detail,
  widgets,
  metrics,
  dateRange,
  allTime,
  days,
  duration,
  scenarioMatrix,
  scoreSeries,
  categorySeries,
  ops,
  lowest,
  agentRows,
  scenarioRows,
  primaryMetric,
  results,
  aggregateTotal,
  aggregateCompleted,
  onBack,
  onOpenMetric,
  onSelectAgent,
  onSelectScenario,
  onOpenRuns,
  onOpenResult,
  runListBase,
  drillCalls,
  onMetric,
}: {
  detail: { kind: 'widget'; widgetId: string } | { kind: 'metric'; metricId: string } | { kind: 'agent'; agentId: string }
  widgets: ResultsWidget[]
  metrics: CallImportMetricAggregate[]
  dateRange: { start: string; end: string } | null
  allTime?: boolean
  days: DayPoint[]
  duration: { average: number | null; points: Array<{ day: string; value: number }> }
  scenarioMatrix: Array<{ agentName: string; scenarioName: string; count: number }>
  scoreSeries: Map<string, Array<{ day: string; value: number }>>
  categorySeries: Map<string, { labels: string[]; data: Array<Record<string, string | number>> }>
  ops: EvaluatorResultsDashboardOpsResponse | undefined
  lowest: Array<{ name: string; value: number; count?: number; metricId?: string }>
  agentRows: Array<{ id: string; name: string; total: number; completed: number; failed: number; rate: number }>
  scenarioRows: Array<{ name: string; count: number; completed: number; failed: number; suiteId: string; scenarioId: string; agentId: string }>
  primaryMetric: CallImportMetricAggregate | null
  results: EvaluatorResultRow[]
  aggregateTotal: number
  aggregateCompleted: number
  onBack: () => void
  onOpenMetric: (metricId: string) => void
  onSelectAgent: (agentId: string) => void
  onSelectScenario: (suiteId: string, scenarioId: string, agentId: string) => void
  onOpenRuns: () => void
  onOpenResult: (resultId: string) => void
  runListBase: {
    agentId?: string
    suiteId?: string
    scenarioId?: string
    since?: string
    until?: string
    playground: boolean
    sampleOn: boolean
    sampleRows: EvaluatorResultRow[]
  }
  drillCalls: DashboardDrillCall[]
  onMetric: (metricId: string) => void
}) {
  const widget = detail.kind === 'widget' ? widgets.find((item) => item.id === detail.widgetId) : null
  const metric = detail.kind === 'metric'
    ? metrics.find((item) => item.metric_id === detail.metricId) ?? null
    : widget?.type === 'metric_trend' || widget?.type === 'metric_usage'
      ? metrics.find((item) => item.metric_id === widget.metricId) ?? primaryMetric
      : widget?.type === 'avg_score'
        ? primaryMetric
        : null
  const agent = detail.kind === 'agent' ? agentRows.find((row) => row.id === detail.agentId) : null
  const title = detail.kind === 'metric' || widget?.type === 'metric_trend' || widget?.type === 'metric_usage'
    ? metric?.metric_name ?? 'Metric'
    : detail.kind === 'agent'
      ? agent?.name ?? 'Agent'
      : widget ? WIDGET_LABELS[widget.type] : 'Details'
  const metricSeries = metric ? scoreSeries.get(metric.metric_id) ?? [] : []
  const model = widget
    ? buildRegisteredInsightCard(widget, {
      widget,
      days,
      duration,
      scenarioMatrix,
      scoreSeries,
      categorySeries,
      ops,
      lowest,
      agentRows,
      scenarioRows,
      primaryMetric,
      trendMetric: metric,
      aggregateTotal,
      aggregateCompleted,
    })
    : metric
      ? {
        headline: formatHeadline(metric.mean),
        caption: metric.metric_name,
        data: metricSeries,
        series: [{ key: 'value', color: PRIMARY }],
        horizontal: false,
      }
      : null
  const windowLabel = formatDashboardWindowLabel(dateRange, allTime)
  const showYearOnChart = useMemo(() => {
    if (days.length < 2) return false
    return days[0].sortKey.slice(0, 4) !== days[days.length - 1].sortKey.slice(0, 4)
  }, [days])
  const [drillSortKey, setDrillSortKey] = useState<string | null>(null)
  const [drillScenarioId, setDrillScenarioId] = useState<string | null>(null)
  const drillDayLabel = drillSortKey ? formatChartDayLabel(drillSortKey, showYearOnChart) : null
  const activeScenarioName = drillScenarioId
    ? scenarioRows.find((row) => row.scenarioId === drillScenarioId)?.name ?? null
    : null
  useEffect(() => {
    setDrillSortKey(null)
    setDrillScenarioId(null)
  }, [dateRange?.start, dateRange?.end, allTime])
  const agentSliceResults = useMemo(() => {
    if (detail.kind !== 'agent') return []
    return results.filter(
      (row) => row.agent_id === detail.agentId || row.agent?.id === detail.agentId,
    )
  }, [detail, results])
  const sliceResults = useMemo(() => {
    let rows = results
    if (drillSortKey) {
      rows = rows.filter((row) => resultLocalDayKey(row.timestamp) === drillSortKey)
    }
    if (drillScenarioId) {
      rows = rows.filter((row) => row.scenario?.id === drillScenarioId)
    }
    return rows
  }, [results, drillSortKey, drillScenarioId])
  const tableBase = useMemo(() => {
    if (!drillSortKey) return runListBase
    const bounds = dateRangeToSinceUntil(drillSortKey, drillSortKey)
    return { ...runListBase, since: bounds.since, until: bounds.until }
  }, [runListBase, drillSortKey])
  const recent = metric
    ? sliceResults.filter((row) => row.metric_scores?.[metric.metric_id]).slice(0, 12)
    : sliceResults.slice(0, 12)
  const [focusId, setFocusId] = useState<string | null>(null)
  const [durationDisplay, setDurationDisplay] = useState<ResultsChartType>(widget?.display ?? 'line')
  const trendUsesDays = widget?.type === 'avg_duration' || widget?.type === 'total_calls' || widget?.type === 'completion' || widget?.type === 'volume'
  const category = metric ? categorySeries.get(metric.metric_id) : undefined
  const categorical = Boolean(metric && isCategoricalMetric(metric) && (widget?.type === 'metric_trend' || widget?.type === 'metric_usage' || detail.kind === 'metric'))
  const baseViews = categorical && category
    ? [
      { id: 'counts', label: 'Counts', headline: formatHeadline(metric?.count ?? null), caption: metric?.metric_name, data: category.data, series: categoryColors(category.labels) },
      { id: 'share', label: 'Share', headline: formatHeadline(metric?.count ?? null), caption: 'Share of labels', data: shareSeries(category.data, category.labels), series: categoryColors(category.labels) },
    ]
    : buildDetailViews(widget?.type, model, days, lowest, agentRows, scenarioRows, metric)
  const views = widget?.type === 'agent_cost'
    ? (['all', 'agent', 'simulator', 'judge'] as const).map((role) => {
      const chart = agentCostDetail(ops, role === 'all' ? null : role, focusId)
      return { id: role, label: role === 'all' ? 'All' : role[0].toUpperCase() + role.slice(1), ...chart }
    })
    : widget?.type === 'model_cost'
      ? [{ id: 'cost', label: 'Cost', ...modelCostDetail(ops, focusId) }]
      : widget?.type === 'tool_calls'
        ? (['calls', 'errors'] as const).map((mode) => {
          const chart = toolCallDetail(ops, mode, focusId)
          return { id: mode, label: mode === 'calls' ? 'Calls' : 'Failures', ...chart }
        })
        : baseViews
  const [viewId, setViewId] = useState(views[0]?.id ?? 'main')
  const active = views.find((view) => view.id === viewId) ?? views[0]
  const costRole = widget?.type === 'agent_cost' && active?.id !== 'all' ? active?.id ?? null : null
  const focusedAgent = ops?.cost_by_agent.find((agent) => agent.agent_id === focusId)
  const focusedModels = modelsForAgent(focusedAgent, widget?.type === 'agent_cost' ? costRole : null)
  const modelCostCalls = useMemo(() => {
    if (widget?.type !== 'model_cost') return []
    const withCost = drillCalls.filter((call) => call.costUsd > 0)
    if (!focusId) return withCost
    return withCost.filter((call) => call.model === focusId)
  }, [drillCalls, focusId, widget?.type])
  const runInsight = usesRunInsightLayout(widget?.type) || detail.kind === 'agent'
  const drillDayActive = Boolean(drillSortKey || drillScenarioId)
  const scenarioCountsFromSample = drillDayActive
  const scopedRunTotal = useMemo(() => {
    if (detail.kind === 'agent' && agent) return agent.total
    if (runListBase.scenarioId) {
      const match = scenarioRows.find((row) => row.scenarioId === runListBase.scenarioId)
      if (match) return match.count
    }
    if (runListBase.agentId) {
      const match = agentRows.find((row) => row.id === runListBase.agentId)
      if (match) return match.total
    }
    if (runListBase.suiteId && !runListBase.agentId) {
      const suiteTotal = scenarioRows
        .filter((row) => row.suiteId === runListBase.suiteId)
        .reduce((sum, row) => sum + row.count, 0)
      if (suiteTotal > 0) return suiteTotal
    }
    return aggregateTotal
  }, [detail.kind, agent, runListBase, scenarioRows, agentRows, aggregateTotal])
  const trendChartData = useMemo(() => {
    if (!active?.data?.length) return []
    if (!trendUsesDays || !drillSortKey) return active.data
    const filtered = active.data.filter((point) => String(point.sortKey ?? '') === drillSortKey)
    return filtered.length ? filtered : active.data
  }, [active, trendUsesDays, drillSortKey])
  const scoreMetricId =
    metric?.metric_id ?? (detail.kind === 'metric' ? detail.metricId : undefined)
  const breakdownAgents = agentRows.map((row) => ({
    id: row.id,
    name: row.name,
    total: row.total,
    failed: row.failed,
  }))

  return (
    <div className="space-y-4">
      <button type="button" onClick={onBack} className="inline-flex items-center gap-1 text-sm font-medium text-gray-600 hover:text-gray-900">
        <ArrowLeft className="h-4 w-4" />
        Back to dashboard
      </button>
      <section className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="text-lg font-semibold text-gray-900">{title}</h2>
            <p className="mt-0.5 text-sm text-gray-500">{windowLabel}</p>
            <p className="mt-1 text-3xl font-semibold tracking-tight text-gray-900">
              {detail.kind === 'agent' && agent
                ? agent.total.toLocaleString()
                : active?.headline ?? model?.headline ?? '—'}
            </p>
            {active?.caption && (
              <p className="mt-1 text-sm text-gray-500">
                {active.caption}
                {trendUsesDays ? ` · ${windowLabel}` : ''}
              </p>
            )}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {views.length > 1 && (
              <div className="flex items-center rounded-lg border border-gray-200 bg-gray-50 p-0.5">
                {views.map((view) => (
                  <button
                    key={view.id}
                    type="button"
                    onClick={() => setViewId(view.id)}
                    className={`rounded-md border px-2.5 py-1 text-xs font-medium ${active?.id === view.id ? 'border-primary-200 bg-white text-primary-800 shadow-sm' : 'border-transparent text-gray-600 hover:text-gray-900'}`}
                  >
                    {view.label}
                  </button>
                ))}
              </div>
            )}
            {widget?.type === 'avg_duration' && (
              <div className="flex items-center rounded-lg border border-gray-200 bg-gray-50 p-0.5">
                {(['line', 'area', 'bar'] as ResultsChartType[]).map((type) => (
                  <button
                    key={type}
                    type="button"
                    onClick={() => setDurationDisplay(type)}
                    className={`rounded-md border px-2.5 py-1 text-xs font-medium ${durationDisplay === type ? 'border-primary-200 bg-white text-primary-800 shadow-sm' : 'border-transparent text-gray-600 hover:text-gray-900'}`}
                  >
                    {CHART_TYPE_LABELS[type]}
                  </button>
                ))}
              </div>
            )}
            <button type="button" onClick={onOpenRuns} className="rounded-md bg-primary-700 px-2.5 py-1 text-xs font-medium text-white hover:bg-primary-800">
              View runs
            </button>
          </div>
        </div>
        {widget?.type === 'metric_usage' && (
          <div className="mt-4">
            <MetricUsageFilters metrics={metrics} selectedId={metric?.metric_id ?? null} onSelect={onMetric} />
            {metric && metric.count === 0 && (
              <UnusedMetricList metrics={metrics} selectedId={metric.metric_id} onSelect={onMetric} />
            )}
          </div>
        )}
        {metric && (
          <dl className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-4">
            <Stat label="Mean" value={formatHeadline(metric.mean)} />
            <Stat label="Median" value={formatHeadline(metric.median)} />
            <Stat label="Scored" value={formatHeadline(metric.count)} />
            <Stat label="Skipped" value={formatHeadline(metric.skipped_count)} />
          </dl>
        )}
        {widget?.type === 'avg_duration' && <DurationSummary results={sliceResults} />}
        {active && trendChartData.length > 0 && (
          <div className="mt-4 h-[320px] cursor-pointer [&_.recharts-surface]:cursor-pointer">
            <PanelChart
              display={widget?.type === 'avg_duration' ? durationDisplay : widget?.display ?? 'bar'}
              data={trendChartData}
              series={active.series}
              layout={active.horizontal ? 'vertical' : 'horizontal'}
              listClassName="max-h-[320px]"
              onPoint={(_label, sortKey) => {
                if (trendUsesDays) setDrillSortKey((prev) => (prev === sortKey ? null : sortKey))
              }}
              onCategory={(name) => {
                if (widget?.type === 'scenarios') {
                  const match = scenarioRows.find((row) => row.name === name)
                  if (match) onSelectScenario(match.suiteId, match.scenarioId, match.agentId)
                }
                if (widget?.type === 'agents' || detail.kind === 'agent') {
                  const match = agentRows.find((row) => row.name === name)
                  if (match) onSelectAgent(match.id)
                }
                if (widget?.type === 'lowest_metrics') {
                  const match = metrics.find((item) => item.metric_id === lowest.find((row) => row.name === name)?.metricId)
                  if (match) onOpenMetric(match.metric_id)
                }
              }}
            />
          </div>
        )}
        {widget?.type === 'agent_cost' && (ops?.cost_by_agent.length ?? 0) > 0 && (
          <div className="mt-4">
            <div className="mb-2 flex items-center justify-between">
              <h3 className="text-xs font-semibold text-gray-900">Agents</h3>
              {focusId && detail.kind !== 'agent' && (
                <button type="button" onClick={() => setFocusId(null)} className="text-xs font-medium text-gray-500 hover:text-gray-800">
                  All agents
                </button>
              )}
            </div>
            <ul className="divide-y divide-gray-100">
              {(detail.kind === 'agent'
                ? ops?.cost_by_agent.filter((row) => row.agent_id === detail.agentId)
                : ops?.cost_by_agent
              )?.map((agent) => (
                <li key={agent.agent_id}>
                  <button
                    type="button"
                    onClick={() => setFocusId(agent.agent_id)}
                    className={`flex w-full items-center justify-between py-2 text-left text-sm ${focusId === agent.agent_id ? 'text-gray-900' : 'text-gray-700 hover:text-gray-900'}`}
                  >
                    <span className="truncate">{agent.agent_name}</span>
                    <span className="shrink-0 text-xs text-gray-500">{formatUsd(costRole === 'agent' ? agent.agent_usd : costRole === 'simulator' ? agent.simulator_usd : costRole === 'judge' ? agent.judge_usd : agent.total_usd)}</span>
                  </button>
                </li>
              ))}
            </ul>
            {focusedModels.length > 0 && (
              <p className="mt-2 text-xs text-gray-500">
                Models: {focusedModels.map((spend) => `${spend.model} ${formatUsd(spend.cost_usd)}`).join(' · ')}
              </p>
            )}
          </div>
        )}
        {widget?.type === 'model_cost' && (ops?.cost_by_model_day.length ?? 0) > 0 && (
          <div className="mt-4">
            <div className="mb-2 flex items-center justify-between">
              <h3 className="text-xs font-semibold text-gray-900">Models</h3>
              {focusId && (
                <button type="button" onClick={() => setFocusId(null)} className="text-xs font-medium text-gray-500 hover:text-gray-800">
                  All models
                </button>
              )}
            </div>
            <ul className="divide-y divide-gray-100">
              {modelTotals(ops).map((item) => (
                <li key={item.model}>
                  <button
                    type="button"
                    onClick={() => setFocusId(item.model)}
                    className="flex w-full items-center justify-between py-2 text-left text-sm text-gray-700 hover:text-gray-900"
                  >
                    <span className="truncate">{item.model}</span>
                    <span className="shrink-0 text-xs text-gray-500">{formatUsd(item.cost_usd)}</span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
        {widget?.type === 'tool_calls' && (ops?.tool_calls_by_agent_day.length ?? 0) > 0 && (
          <div className="mt-4">
            <div className="mb-2 flex items-center justify-between">
              <h3 className="text-xs font-semibold text-gray-900">Agents</h3>
              {focusId && (
                <button type="button" onClick={() => setFocusId(null)} className="text-xs font-medium text-gray-500 hover:text-gray-800">
                  All agents
                </button>
              )}
            </div>
            <ul className="divide-y divide-gray-100">
              {toolAgentTotals(ops, viewId === 'errors' ? 'errors' : 'calls').map((item) => (
                <li key={item.agent_id}>
                  <button
                    type="button"
                    onClick={() => setFocusId(item.agent_id)}
                    className="flex w-full items-center justify-between py-2 text-left text-sm text-gray-700 hover:text-gray-900"
                  >
                    <span className="truncate">{item.agent_name}</span>
                    <span className="shrink-0 text-xs text-gray-500">
                      {viewId === 'errors'
                        ? `${item.errors.toLocaleString()} failures`
                        : `${item.calls.toLocaleString()} calls`}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
        {widget?.type === 'metric_usage' && metric && (
          <MetricScenarioScores
            results={results}
            metricId={metric.metric_id}
            scenarioRows={scenarioRows}
            windowScoped
          />
        )}
        {agent && (
          <div className="mt-4 flex flex-wrap gap-2">
            <button type="button" onClick={() => onSelectAgent(agent.id)} className="rounded-lg border border-gray-200 px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50">
              Filter dashboard to this agent
            </button>
          </div>
        )}
      </section>
      {detail.kind === 'agent' && agent && (
        <>
          <RunInsightFilterBar
            dayLabel={drillDayLabel}
            scenarioName={activeScenarioName}
            onClearDay={() => setDrillSortKey(null)}
            onClearScenario={() => setDrillScenarioId(null)}
            onClearAll={() => {
              setDrillSortKey(null)
              setDrillScenarioId(null)
            }}
          />
          <RunInsightBreakdown
            results={agentSliceResults}
            scenarioRows={scenarioRows.filter((row) => row.agentId === detail.agentId)}
            agentRows={[{ id: agent.id, name: agent.name }]}
            agentRunRows={breakdownAgents.filter((row) => row.id === detail.agentId)}
            scenarioCountsFromSample={scenarioCountsFromSample}
            windowRunTotal={scopedRunTotal}
            sampleSize={results.length}
            windowDurationBuckets={ops?.duration_buckets}
            activeScenarioId={drillScenarioId}
            activeScenarioName={activeScenarioName}
            title={`${agent.name} · scenarios`}
            onScenarioClick={(scenarioId) => {
              setDrillScenarioId((prev) => (prev === scenarioId ? null : scenarioId))
            }}
          />
        </>
      )}
      {runInsight && widget && (
        <>
          <RunInsightFilterBar
            dayLabel={drillDayLabel}
            scenarioName={activeScenarioName}
            onClearDay={() => setDrillSortKey(null)}
            onClearScenario={() => setDrillScenarioId(null)}
            onClearAll={() => {
              setDrillSortKey(null)
              setDrillScenarioId(null)
            }}
          />
          <RunInsightBreakdown
            results={sliceResults}
            scenarioRows={scenarioRows}
            agentRows={agentRows.map((row) => ({ id: row.id, name: row.name }))}
            agentRunRows={breakdownAgents}
            scenarioCountsFromSample={scenarioCountsFromSample}
            windowRunTotal={scopedRunTotal}
            sampleSize={results.length}
            windowDurationBuckets={ops?.duration_buckets}
            activeScenarioId={drillScenarioId}
            activeScenarioName={activeScenarioName}
            title={
              widget.type === 'scenarios_by_agent'
                ? 'Scenarios across agents'
                : widget.type === 'scenarios'
                  ? 'Scenario runs'
                  : 'Call duration'
            }
            onScenarioClick={(scenarioId) => {
              setDrillScenarioId((prev) => (prev === scenarioId ? null : scenarioId))
            }}
          />
        </>
      )}
      {(widget?.type === 'total_calls' || widget?.type === 'volume' || widget?.type === 'completion') && (
        <RunInsightBreakdown
          results={sliceResults}
          scenarioRows={scenarioRows}
          agentRows={agentRows.map((row) => ({ id: row.id, name: row.name }))}
          agentRunRows={breakdownAgents}
          scenarioCountsFromSample={scenarioCountsFromSample}
          windowRunTotal={scopedRunTotal}
          sampleSize={results.length}
          windowDurationBuckets={ops?.duration_buckets}
          activeScenarioId={drillScenarioId}
          activeScenarioName={activeScenarioName}
          title="Runs in window"
          onScenarioClick={(scenarioId) => {
            setDrillScenarioId((prev) => (prev === scenarioId ? null : scenarioId))
          }}
        />
      )}
      {usesCallRunLeaf(widget) ? (
        <RunInsightRunsSection
          title={focusId ? `Runs · ${focusId}` : `Runs with model cost · ${windowLabel}`}
        >
          <PaginatedCallRunsTable
            calls={modelCostCalls}
            title=""
            onOpenResult={onOpenResult}
          />
        </RunInsightRunsSection>
      ) : usesPaginatedRunLeaf(detail, widget) ? (
        <RunInsightRunsSection title={runTableTitle({
          windowLabel,
          drillDayLabel,
          activeScenarioName,
          agentName: detail.kind === 'agent' ? agent?.name : detail.kind === 'widget' && widget?.type === 'agent_cost' && focusId
            ? ops?.cost_by_agent.find((row) => row.agent_id === focusId)?.agent_name
            : undefined,
        })}
        >
          <PaginatedRunsTable
            base={tableBase}
            filterAgentId={
              detail.kind === 'agent'
                ? detail.agentId
                : widget?.type === 'agent_cost' && focusId
                  ? focusId
                  : undefined
            }
            filterScenarioId={drillScenarioId ?? undefined}
            metricId={scoreMetricId}
            scoreMetricId={scoreMetricId}
            callsByResultId={widget?.type === 'agent_cost' ? drillCalls : undefined}
            rich={widget?.type === 'agent_cost'}
            title=""
            onOpenResult={onOpenResult}
          />
        </RunInsightRunsSection>
      ) : (
        <section className="rounded-xl border border-gray-200 bg-white p-5">
          <h3 className="text-sm font-semibold text-gray-900">{metric ? 'Recent scored runs' : 'Recent runs'}</h3>
          {recent.length === 0 ? (
            <p className="mt-3 text-sm text-gray-400">No runs in this window</p>
          ) : (
            <ul className="mt-3 divide-y divide-gray-100">
              {recent.map((row) => {
                const score = metric ? row.metric_scores?.[metric.metric_id] : null
                return (
                  <li key={row.id}>
                    <button
                      type="button"
                      onClick={() => onOpenResult(row.id)}
                      className="flex w-full items-center justify-between gap-3 py-2 text-left text-sm hover:text-primary-700"
                    >
                      <span className="truncate text-gray-900">{row.name || row.agent?.name || row.result_id}</span>
                      <span className="shrink-0 text-xs text-gray-500">
                        {score ? String(score.value) : row.status} · {dayKey(row.timestamp).day}
                      </span>
                    </button>
                  </li>
                )
              })}
            </ul>
          )}
        </section>
      )}
    </div>
  )
}

const AGENT_DOTS = ['#f97316', '#14b8a6', '#6366f1', '#ca8a04']
type AgentColumn = 'metrics' | 'scenarios' | 'calls' | 'cost' | 'tools'

function MetricAgentsTable({
  agents,
  results,
  ops,
  onOpenAgent,
}: {
  agents: EvaluatorResultsAgentSummary[]
  results: EvaluatorResultRow[]
  ops: EvaluatorResultsDashboardOpsResponse | undefined
  onOpenAgent: (agentId: string) => void
}) {
  const [columns, setColumns] = useState<AgentColumn[]>(['metrics', 'scenarios'])
  const labels: Record<AgentColumn, string> = {
    metrics: 'No. of metrics',
    scenarios: 'No. of scenarios',
    calls: 'Calls',
    cost: 'Cost',
    tools: 'Tool calls',
  }
  const toggle = (column: AgentColumn) => {
    setColumns((current) => current.includes(column) ? current.filter((item) => item !== column) : [...current, column])
  }
  const rows = agents.map((agent) => {
    const runs = results.filter((row) => row.agent_id === agent.agent_id || row.agent?.id === agent.agent_id)
    const metricIds = new Set<string>()
    for (const run of runs) {
      for (const id of Object.keys(run.metric_scores ?? {})) metricIds.add(id)
    }
    const rolledUp = ops?.agent_metric_counts?.find((row) => row.agent_id === agent.agent_id)?.metric_count
    const scenarioCount = (agent.suites ?? []).reduce((sum, suite) => sum + (suite.scenarios?.length ?? 0), 0)
    const cost = ops?.cost_by_agent.find((row) => row.agent_id === agent.agent_id)?.total_usd ?? 0
    const tools = (ops?.tool_calls_per_run ?? []).find((row) => row.agent_id === agent.agent_id)?.calls
      ?? (ops?.tool_calls_by_agent_day ?? []).filter((row) => row.agent_id === agent.agent_id).reduce((sum, row) => sum + row.calls, 0)
    return {
      id: agent.agent_id,
      name: agent.agent_name,
      metrics: rolledUp ?? metricIds.size,
      scenarios: scenarioCount,
      calls: agent.counts.total,
      cost,
      tools,
    }
  })
  const order: AgentColumn[] = ['metrics', 'scenarios', 'calls', 'cost', 'tools']
  const shown = order.filter((column) => columns.includes(column))
  return (
    <section className="rounded-xl border border-gray-200 bg-white shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-gray-100 px-4 py-3">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-wide text-gray-400">Table</p>
          <h3 className="text-sm font-semibold text-gray-900">Agents</h3>
        </div>
        <div className="flex flex-wrap gap-1">
          {order.map((column) => (
            <button
              key={column}
              type="button"
              onClick={() => toggle(column)}
              className={`rounded-full border px-2.5 py-1 text-xs font-medium ${columns.includes(column) ? 'border-primary-200 bg-primary-50 text-primary-800' : 'border-transparent text-gray-500 hover:bg-gray-50'}`}
            >
              {labels[column]}
            </button>
          ))}
        </div>
      </div>
      <table className="w-full text-left text-sm">
        <thead className="text-xs text-gray-400">
          <tr>
            <th className="px-4 py-2 font-medium">Agents</th>
            {shown.map((column) => (
              <th key={column} className="px-4 py-2 text-right font-medium">{labels[column]}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={row.id} className="border-t border-gray-100">
              <td className="px-4 py-2.5">
                <button type="button" onClick={() => onOpenAgent(row.id)} className="inline-flex items-center gap-2 font-medium text-gray-900 hover:text-primary-700">
                  <span className="h-2 w-2 rounded-full" style={{ backgroundColor: AGENT_DOTS[index % AGENT_DOTS.length] }} />
                  {row.name}
                </button>
              </td>
              {shown.map((column) => (
                <td key={column} className="px-4 py-2.5 text-right text-gray-700">
                  {column === 'cost' ? formatUsd(row.cost) : row[column].toLocaleString()}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  )
}

type MetricUsageMode = 'most' | 'least' | 'never'

function metricsForMode(metrics: CallImportMetricAggregate[], mode: MetricUsageMode): CallImportMetricAggregate[] {
  if (mode === 'never') return metrics.filter((metric) => metric.count === 0)
  return [...metrics].filter((metric) => metric.count > 0).sort((a, b) => (mode === 'most' ? b.count - a.count : a.count - b.count))
}

function MetricUsageFilters({
  metrics,
  selectedId,
  onSelect,
}: {
  metrics: CallImportMetricAggregate[]
  selectedId: string | null
  onSelect: (metricId: string) => void
}) {
  const [mode, setMode] = useState<MetricUsageMode>('most')
  const choose = (next: MetricUsageMode) => {
    setMode(next)
    const match = metricsForMode(metrics, next)[0]
    if (match) onSelect(match.metric_id)
  }
  const options = metricsForMode(metrics, mode)
  return (
    <div className="mb-3 flex flex-wrap items-center gap-2">
      <div className="flex items-center rounded-lg border border-gray-200 bg-gray-50 p-0.5">
        {(['most', 'least', 'never'] as MetricUsageMode[]).map((item) => (
          <button
            key={item}
            type="button"
            onClick={() => choose(item)}
            className={`rounded-md border px-2.5 py-1 text-xs font-medium ${mode === item ? 'border-primary-200 bg-white text-primary-800 shadow-sm' : 'border-transparent text-gray-600 hover:text-gray-900'}`}
          >
            {item === 'most' ? 'Most used' : item === 'least' ? 'Least used' : 'Never used'}
          </button>
        ))}
      </div>
      <select
        value={selectedId ?? ''}
        onChange={(event) => onSelect(event.target.value)}
        className="min-w-0 flex-1 rounded-lg border border-gray-200 bg-white px-2 py-1 text-xs text-gray-700"
      >
        {options.length === 0 && <option value="">{mode === 'never' ? 'No unused metrics' : 'No scored metrics'}</option>}
        {options.map((metric) => (
          <option key={metric.metric_id} value={metric.metric_id}>
            {metric.metric_name}{metric.count === 0 ? ' · never scored' : ''}
          </option>
        ))}
      </select>
    </div>
  )
}

function UnusedMetricList({
  metrics,
  selectedId,
  onSelect,
}: {
  metrics: CallImportMetricAggregate[]
  selectedId: string
  onSelect: (metricId: string) => void
}) {
  const unused = metrics.filter((metric) => metric.count === 0)
  if (!unused.length) {
    return <p className="text-sm text-gray-400">Every metric was scored in this window.</p>
  }
  return (
    <div className="min-h-0 flex-1 overflow-auto">
      <p className="mb-2 text-xs text-gray-500">{unused.length} metrics were not scored in this window</p>
      <ul className="divide-y divide-gray-100">
        {unused.map((metric) => (
          <li key={metric.metric_id}>
            <button
              type="button"
              onClick={() => onSelect(metric.metric_id)}
              className={`flex w-full items-center justify-between py-1.5 text-left text-sm ${metric.metric_id === selectedId ? 'font-medium text-primary-800' : 'text-gray-700 hover:text-gray-900'}`}
            >
              <span className="truncate pr-3">{metric.metric_name}</span>
              <span className="shrink-0 text-xs text-gray-400">Never scored</span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}

function MetricScenarioScores({
  results,
  metricId,
  scenarioRows,
  windowScoped = false,
}: {
  results: EvaluatorResultRow[]
  metricId: string
  scenarioRows?: Array<{ name: string; count: number; failed: number; scenarioId: string }>
  windowScoped?: boolean
}) {
  const groups = new Map<string, { sum: number; count: number; failed: number; scored: number }>()
  if (windowScoped && scenarioRows?.length) {
    for (const row of scenarioRows) {
      groups.set(row.name, { sum: 0, count: row.count, failed: row.failed, scored: 0 })
    }
  }
  for (const row of results) {
    const name = row.scenario?.name
    if (!name) continue
    const score = row.metric_scores?.[metricId]
    const bucket = groups.get(name) ?? { sum: 0, count: 0, failed: 0, scored: 0 }
    if (!windowScoped) {
      if (row.status === 'failed') bucket.failed += 1
      bucket.count += 1
    }
    const value = typeof score?.value === 'number' ? score.value : Number(score?.value)
    const scoreMeta = score as { skipped?: boolean; error?: string } | undefined
    if (!Number.isNaN(value) && score && !scoreMeta?.skipped && !scoreMeta?.error) {
      bucket.sum += value
      bucket.scored += 1
    }
    groups.set(name, bucket)
  }
  const rows = Array.from(groups.entries())
    .sort((a, b) => (windowScoped ? b[1].count - a[1].count : b[1].scored - a[1].scored))
  if (!rows.length) return <p className="mt-4 text-sm text-gray-400">No scored runs for this metric.</p>
  return (
    <div className="mt-4">
      <h3 className="text-sm font-semibold text-gray-900">By scenario</h3>
      {windowScoped && results.length < (scenarioRows?.reduce((sum, row) => sum + row.count, 0) ?? 0) ? (
        <p className="mt-1 text-[10px] text-gray-500">
          Run counts are for the full filter window; means use loaded scored runs.
        </p>
      ) : null}
      <ul className="mt-2 divide-y divide-gray-100">
        {rows.map(([name, stats]) => (
          <li key={name} className="flex items-center justify-between py-2 text-sm text-gray-700">
            <span className="truncate pr-3">{name}</span>
            <span className="shrink-0 text-xs text-gray-500">
              {stats.scored ? `avg ${(stats.sum / stats.scored).toFixed(2)}` : 'never scored'}
              {windowScoped
                ? ` · ${stats.count} runs · ${stats.failed} failed`
                : ` · ${stats.failed} failed`}
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}

function DurationSummary({ results }: { results: EvaluatorResultRow[] }) {
  const values = results.map((row) => row.duration_seconds).filter((value): value is number => value != null)
  if (!values.length) return null
  const average = values.reduce((sum, value) => sum + value, 0) / values.length
  return (
    <p className="mt-2 text-sm text-gray-500">
      Avg {formatDuration(average)} · shortest {formatDuration(Math.min(...values))} · longest {formatDuration(Math.max(...values))}
    </p>
  )
}

function drillCallsFromResults(rows: EvaluatorResultRow[]): DashboardDrillCall[] {
  return rows.map((row) => {
    const raw = row.call_data?.tool_calls
    const uses = Array.isArray(raw)
      ? raw.flatMap((item) => {
        if (!item || typeof item !== 'object') return []
        const call = item as { tool?: string; provider?: string; side?: string; status?: string }
        if (call.side && call.side !== 'production') return []
        return [{ tool: String(call.tool || 'tool'), provider: String(call.provider || 'unknown'), failed: call.status === 'error' }]
      })
      : []
    return {
      at: row.timestamp,
      agent: row.agent?.name || 'Agent',
      agentId: row.agent_id ?? row.agent?.id ?? undefined,
      title: row.name || row.result_id,
      durationSeconds: row.duration_seconds ?? 0,
      costUsd: 0,
      tokens: 0,
      model: '',
      tool: uses[0]?.tool ?? '',
      provider: uses[0]?.provider ?? '',
      uses,
      resultId: row.result_id || row.id,
    }
  })
}

function BreakdownTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean
  payload?: Array<{ name?: string; value?: number | string; color?: string }>
  label?: string | number
}) {
  if (!active || !payload?.length) return null
  return (
    <div className="rounded-lg border border-gray-200 bg-white px-3 py-2 text-xs shadow-md">
      <p className="mb-1 font-semibold text-gray-900">{label}</p>
      {payload.map((item) => {
        const value = typeof item.value === 'number' ? item.value.toFixed(2) : item.value
        return (
          <p key={item.name} className="font-medium" style={{ color: item.color ?? '#374151' }}>
            {item.name}: {value}
          </p>
        )
      })}
    </div>
  )
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-gray-100 px-3 py-2">
      <dt className="text-[11px] uppercase tracking-wide text-gray-400">{label}</dt>
      <dd className="mt-1 text-sm font-semibold text-gray-900">{value}</dd>
    </div>
  )
}
