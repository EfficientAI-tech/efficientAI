import { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { DndContext, PointerSensor, closestCenter, useSensor, useSensors, type DragEndEvent } from '@dnd-kit/core'
import { SortableContext, rectSortingStrategy, useSortable } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { ArrowLeft, GripVertical, Loader, MoreHorizontal, Plus, RotateCcw } from 'lucide-react'
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
import { dateRangeToSinceUntil, rangeForDays } from './resultsDateRange'
import {
  CHART_TYPE_LABELS,
  ADDABLE_WIDGETS,
  DEFAULT_RESULTS_WIDGETS,
  MAX_VISIBLE_WIDGETS,
  WIDGET_LABELS,
  copyResultsWidgets,
  readResultsDashboardLayout,
  visibleWidgets,
  writeResultsDashboardLayout,
  type ResultsChartType,
  type ResultsWidget,
  type ResultsWidgetType,
} from './resultsDashboardLayout'
import {
  SAMPLE_AGENTS,
  SAMPLE_DRILL_CALLS,
  SAMPLE_OPS,
  SAMPLE_RESULTS,
  sampleMetricsFor,
  scopeSampleOps,
  type DashboardDrillCall,
} from './resultsDashboardSample'
import {
  agentCostCard,
  agentCostDetail,
  buildCategorySeries,
  categoryColors,
  formatUsd,
  isCategoricalMetric,
  formatDuration,
  modelCostCard,
  modelCostDetail,
  modelTotals,
  modelsForAgent,
  platformToolDetail,
  scenarioStack,
  shareSeries,
  toolAgentTotals,
  toolCallCard,
  toolCallDetail,
  toolFacts,
  toolsCard,
  toolsDetail,
  usageCard,
  usageDetail,
  usageFacts,
  usageHasS2S,
} from './resultsDashboardSeries'

const PRIMARY = '#ca8a04'
const SERIES_MUTED = '#9ca3af'
const FAIL = '#dc2626'
const GRID = '#e5e7eb'
const TRENDS_PAGE_LIMIT = 500

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
}

interface DayPoint {
  day: string
  sortKey: string
  completed: number
  failed: number
}

function metricNumericValue(value: unknown, type: string): number | null {
  const kind = type.toLowerCase()
  if (kind === 'number' || kind === 'rating') {
    if (typeof value === 'number' && !Number.isNaN(value)) return value
    if (typeof value === 'string' && value.trim() !== '') {
      const parsed = Number(value)
      return Number.isNaN(parsed) ? null : parsed
    }
  }
  if (kind === 'boolean') {
    if (value === true || value === 'true' || value === 1 || value === '1') return 1
    if (value === false || value === 'false' || value === 0 || value === '0') return 0
  }
  return null
}

function dayKey(iso: string): { day: string; sortKey: string } {
  const date = new Date(iso)
  return {
    day: date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' }),
    sortKey: date.toISOString().slice(0, 10),
  }
}

function isNumericMetric(metric: CallImportMetricAggregate): boolean {
  return metric.mean != null || metric.metric_type === 'number' || metric.metric_type === 'rating'
}

function formatHeadline(value: number | null, suffix = ''): string {
  if (value == null || Number.isNaN(value)) return '—'
  return `${value.toLocaleString(undefined, { maximumFractionDigits: 1 })}${suffix}`
}

function scopeSample(
  agentId: string,
  suiteId: string,
  scenarioId: string,
  start: string | null,
  end: string | null,
) {
  const suites = SAMPLE_AGENTS.flatMap((agent) => agent.suites ?? [])
  const suite = suites.find((item) => item.suite_id === suiteId)
  const scenarioOwner = SAMPLE_AGENTS.find((agent) => (
    (agent.suites ?? []).some((item) => (item.scenarios ?? []).some((scenario) => scenario.scenario_id === scenarioId))
  ))
  const agentFilter = agentId || suite?.agent_id || scenarioOwner?.agent_id || ''
  const scenarioIds = scenarioId
    ? new Set([scenarioId])
    : suite
      ? new Set((suite.scenarios ?? []).map((scenario) => scenario.scenario_id))
      : null
  const filtered = SAMPLE_RESULTS.filter((row) => {
    if (agentFilter && row.agent_id !== agentFilter) return false
    if (scenarioIds && !scenarioIds.has(row.scenario?.id ?? '')) return false
    const day = row.timestamp.slice(0, 10)
    if (start && day < start) return false
    if (end && day > end) return false
    return true
  })
  return { results: filtered, ops: scopeSampleOps(SAMPLE_OPS, agentFilter, start, end) }
}

function sampleDrillCalls(agentId: string, start: string | null, end: string | null): DashboardDrillCall[] {
  const agentName = SAMPLE_AGENTS.find((agent) => agent.agent_id === agentId)?.agent_name
  return SAMPLE_DRILL_CALLS.filter((call) => {
    if (agentName && call.agent !== agentName) return false
    const day = call.at.slice(0, 10)
    if (start && day < start) return false
    if (end && day > end) return false
    return true
  })
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
}: ResultsDashboardTabProps) {
  const [widgets, setWidgets] = useState<ResultsWidget[]>(readResultsDashboardLayout)
  const [addOpen, setAddOpen] = useState(false)
  const [source, setSource] = useState<'simulation' | 'live'>('simulation')
  const [sampleOn, setSampleOn] = useState(true)
  const playground = source === 'live'
  const [detail, setDetail] = useState<
    | { kind: 'platform'; section: 'usage' | 'tool_calls' | 'tools' }
    | { kind: 'widget'; widgetId: string }
    | { kind: 'metric'; metricId: string }
    | { kind: 'agent'; agentId: string }
    | null
  >(null)
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 6 } }))

  useEffect(() => {
    writeResultsDashboardLayout(widgets)
  }, [widgets])

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
      limit: TRENDS_PAGE_LIMIT,
    }),
    [agentId, suiteId, scenarioId, dateBounds, playground],
  )

  const dashboardQueryOptions = { enabled: !sampleOn, staleTime: 60_000 }
  const { data: listResponse } = useQuery({
    queryKey: ['evaluator-results-dashboard', listParams],
    queryFn: () => apiClient.listEvaluatorResults(listParams),
    enabled: !sampleOn && detail !== null,
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

  const { data: metricsCatalog = [] } = useQuery({
    queryKey: ['metrics', 'agent', 'dashboard'],
    queryFn: () => apiClient.listMetrics('agent'),
    enabled: !sampleOn,
    staleTime: 5 * 60_000,
  })

  const scopedSample = useMemo(
    () => scopeSample(agentId, suiteId, scenarioId, effectiveDateRange?.start ?? null, effectiveDateRange?.end ?? null),
    [agentId, suiteId, scenarioId, effectiveDateRange],
  )
  const ops = sampleOn ? scopedSample.ops : liveOps
  const results = sampleOn ? scopedSample.results : itemsOf<EvaluatorResultRow>(listResponse)
  const aggregateTotal = sampleOn ? scopedSample.results.length : liveOps?.total_rows ?? 0
  const aggregateCompleted = sampleOn
    ? scopedSample.results.filter((row) => row.status === 'completed').length
    : liveOps?.completed_rows ?? 0
  const metrics = useMemo(
    () => (sampleOn ? sampleMetricsFor(scopedSample.results) : withUnusedMetrics(liveOps?.metrics ?? [], metricsCatalog)),
    [sampleOn, scopedSample.results, liveOps, metricsCatalog],
  )
  const primaryMetric = useMemo(
    () =>
      [...metrics]
        .filter(isNumericMetric)
        .sort((a, b) => b.count - a.count)[0] ?? null,
    [metrics],
  )

  const days = useMemo(
    () => (sampleOn ? buildDays(scopedSample.results) : daysFromRunDays(liveOps?.run_days)),
    [sampleOn, scopedSample.results, liveOps],
  )
  const callDays = useMemo(
    () => (sampleOn ? buildCallDays(scopedSample.results) : callDaysFromRunDays(liveOps?.run_days)),
    [sampleOn, scopedSample.results, liveOps],
  )
  const duration = useMemo(
    () => (sampleOn ? buildDuration(scopedSample.results) : durationFromRunDays(liveOps?.run_days)),
    [sampleOn, scopedSample.results, liveOps],
  )
  const scoreSeries = useMemo(
    () => (sampleOn ? buildScoreSeries(scopedSample.results, sampleMetricsFor(scopedSample.results)) : scoreSeriesFromDays(liveOps?.score_days)),
    [sampleOn, scopedSample.results, liveOps],
  )
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
    () => narrowAgents(sampleOn ? SAMPLE_AGENTS : liveOps?.agents ?? agents, agentId, suiteId, scenarioId),
    [sampleOn, liveOps, agents, agentId, suiteId, scenarioId],
  )
  useEffect(() => {
    if (!onDashboardAgents) return
    if (sampleOn) {
      onDashboardAgents(SAMPLE_AGENTS)
      return
    }
    if (liveOps) onDashboardAgents(liveOps.agents ?? [])
  }, [onDashboardAgents, sampleOn, liveOps])
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
  const visibleCount = widgets.filter((widget) => !widget.hidden).length
  const loading = !sampleOn && loadingOps && !liveOps

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
    if (visibleCount >= MAX_VISIBLE_WIDGETS) return
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
      const lineTypes: ResultsWidgetType[] = ['completion', 'avg_score', 'avg_duration', 'metric_usage', 'model_cost', 'tool_calls']
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

  if (loading) {
    return (
      <div className="flex items-center justify-center py-16 text-gray-500">
        <Loader className="mr-2 h-5 w-5 animate-spin" />
        Loading dashboard…
      </div>
    )
  }

  if (detail?.kind === 'platform') {
    return (
      <PlatformDetail
        section={detail.section}
        ops={ops}
        calls={sampleOn ? sampleDrillCalls(agentId, effectiveDateRange?.start ?? null, effectiveDateRange?.end ?? null) : drillCallsFromResults(results)}
        onBack={() => setDetail(null)}
        onOpenRuns={onOpenRuns}
        onOpenResult={onOpenResult}
      />
    )
  }

  if (detail) {
    return (
      <ResultsDetailView
        detail={detail}
        widgets={widgets}
        metrics={metrics}
        days={days}
        callDays={callDays}
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
        onMetric={(metricId) => {
          if (detail.kind === 'widget') setMetric(detail.widgetId, metricId)
        }}
      />
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-xs text-gray-500">
          {effectiveDateRange ? `${effectiveDateRange.start} → ${effectiveDateRange.end}` : 'All time'}
        </p>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => {
              setSampleOn((on) => {
                if (on && (agentId.startsWith('sample-') || suiteId.startsWith('sample-') || scenarioId.startsWith('sample-'))) {
                  onSelectAgent('')
                }
                return !on
              })
            }}
            className={`rounded-lg border px-2.5 py-1 text-xs font-medium ${sampleOn ? 'border-amber-300 bg-amber-50 text-amber-900' : 'border-gray-200 bg-white text-gray-600'}`}
          >
            {sampleOn ? 'Sample data on' : 'Sample data'}
          </button>
          <div className="flex items-center rounded-lg bg-gray-100 p-0.5">
            {(['simulation', 'live'] as const).map((item) => (
              <button
                key={item}
                type="button"
                onClick={() => setSource(item)}
                className={`rounded-md px-2.5 py-1 text-xs font-medium ${source === item ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-500 hover:text-gray-800'}`}
              >
                {item === 'simulation' ? 'Simulations' : 'Live'}
              </button>
            ))}
          </div>
          <div className="relative">
            <button
              type="button"
              onClick={() => setAddOpen((open) => !open)}
              disabled={visibleCount >= MAX_VISIBLE_WIDGETS}
              title={visibleCount >= MAX_VISIBLE_WIDGETS ? 'Hide a chart before adding another' : 'Add chart'}
              className="inline-flex items-center gap-1 rounded-lg border border-gray-200 bg-white px-2.5 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:text-gray-400"
            >
              <Plus className="h-3.5 w-3.5" />
              Add chart
            </button>
            {addOpen && (
              <div className="absolute right-0 z-20 mt-1 max-h-80 w-56 overflow-y-auto rounded-lg border border-gray-200 bg-white py-1 shadow-lg">
                {ADDABLE_WIDGETS.flatMap((type) => {
                  if (type === 'metric_trend') {
                    if (!metrics.length) {
                      return [(
                        <button key={type} type="button" disabled className="block w-full px-3 py-1.5 text-left text-xs text-gray-300">
                          Metric trend
                        </button>
                      )]
                    }
                    return [
                      <p key="metric-trend-label" className="px-3 pb-1 pt-2 text-[10px] font-semibold uppercase tracking-wide text-gray-400">
                        Metric trend
                      </p>,
                      ...metrics.map((metric) => {
                        const alreadyVisible = widgets.some((widget) => widget.type === 'metric_trend' && widget.metricId === metric.metric_id && !widget.hidden)
                        return (
                          <button
                            key={metric.metric_id}
                            type="button"
                            disabled={alreadyVisible || visibleCount >= MAX_VISIBLE_WIDGETS}
                            onClick={() => addWidget('metric_trend', metric.metric_id)}
                            className="block w-full px-3 py-1.5 text-left text-xs text-gray-700 hover:bg-gray-50 disabled:text-gray-300"
                          >
                            {metric.metric_name}
                          </button>
                        )
                      }),
                    ]
                  }
                  const alreadyVisible = widgets.some((widget) => widget.type === type && !widget.hidden)
                  return [(
                    <button
                      key={type}
                      type="button"
                      disabled={alreadyVisible || visibleCount >= MAX_VISIBLE_WIDGETS}
                      onClick={() => addWidget(type)}
                      className="block w-full px-3 py-1.5 text-left text-xs text-gray-700 hover:bg-gray-50 disabled:text-gray-300"
                    >
                      {WIDGET_LABELS[type]}
                    </button>
                  )]
                })}
              </div>
            )}
          </div>
          <button
            type="button"
            onClick={() => update(copyResultsWidgets(DEFAULT_RESULTS_WIDGETS))}
            className="inline-flex items-center gap-1 rounded-lg border border-gray-200 bg-white px-2.5 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50"
          >
            <RotateCcw className="h-3.5 w-3.5" />
            Reset
          </button>
        </div>
      </div>

      <section className="rounded-2xl border border-amber-200/80 bg-gradient-to-b from-amber-50 to-white p-4">
        <div className="mb-3 flex items-end justify-between gap-3">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-amber-700">Platform</p>
            <h2 className="mt-0.5 text-sm font-semibold text-gray-900">Usage, tool calls, and tools</h2>
          </div>
          <span className="hidden text-xs text-amber-800/80 sm:inline">Spend and what the agents invoke</span>
        </div>
        <div className="grid gap-4 md:grid-cols-3">
          <PlatformCard title="Usage" model={usageCard(ops)} onOpen={() => setDetail({ kind: 'platform', section: 'usage' })} />
          <PlatformCard title="Tool calls" model={toolCallCard(ops, 'line')} onOpen={() => setDetail({ kind: 'platform', section: 'tool_calls' })} />
          <PlatformCard title="Tools" model={toolsCard(ops)} onOpen={() => setDetail({ kind: 'platform', section: 'tools' })} />
        </div>
      </section>

      <div className="flex items-center gap-3 pt-1">
        <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-gray-500">Metrics</p>
        <span className="h-px flex-1 bg-gray-200" />
        <span className="text-xs text-gray-400">Scores, duration, and scenarios</span>
      </div>

      {shown.length === 0 ? (
        <div className="rounded-xl border border-gray-200 bg-white p-12 text-center">
          <p className="text-sm font-medium text-gray-900">No charts on this dashboard</p>
          <p className="mt-1 text-sm text-gray-500">Add a chart or reset the layout.</p>
        </div>
      ) : (
        <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onDragEnd}>
          <SortableContext items={shown.map((widget) => widget.id)} strategy={rectSortingStrategy}>
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
              {shown.map((widget) => (
                <DashboardPanel
                  key={widget.id}
                  widget={widget}
                  canMoveUp={shown.findIndex((item) => item.id === widget.id) > 0}
                  canMoveDown={shown.findIndex((item) => item.id === widget.id) < shown.length - 1}
                  metrics={metrics}
                  days={days}
                  callDays={callDays}
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
                  onOpenDetail={() => setDetail({ kind: 'widget', widgetId: widget.id })}
                  onOpenAgent={(id) => setDetail({ kind: 'agent', agentId: id })}
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

function labelDay(iso: string): { day: string; sortKey: string } {
  const sortKey = iso.slice(0, 10)
  const [year, month, date] = sortKey.split('-').map(Number)
  const local = new Date(year, (month || 1) - 1, date || 1)
  return {
    day: local.toLocaleDateString(undefined, { month: 'short', day: 'numeric' }),
    sortKey,
  }
}

function daysFromRunDays(rows: DashboardOpsRunDay[] | undefined): DayPoint[] {
  return (rows ?? [])
    .map((row) => {
      const labeled = labelDay(row.day)
      return { day: labeled.day, sortKey: labeled.sortKey, completed: row.completed, failed: row.failed }
    })
    .sort((a, b) => a.sortKey.localeCompare(b.sortKey))
}

function callDaysFromRunDays(rows: DashboardOpsRunDay[] | undefined): Array<{ day: string; calls: number }> {
  return daysFromRunDays(rows).map((row) => ({ day: row.day, calls: row.completed + row.failed }))
}

function durationFromRunDays(rows: DashboardOpsRunDay[] | undefined): { average: number | null; points: Array<{ day: string; value: number }> } {
  let sum = 0
  let count = 0
  const points = [...(rows ?? [])]
    .sort((a, b) => a.day.localeCompare(b.day))
    .map((row) => {
      sum += row.duration_seconds
      count += row.duration_count
      return {
        day: labelDay(row.day).day,
        value: row.duration_count ? Number((row.duration_seconds / row.duration_count).toFixed(1)) : 0,
      }
    })
  return { average: count ? sum / count : null, points }
}

function scoreSeriesFromDays(rows: DashboardOpsScoreDay[] | undefined) {
  const series = new Map<string, Array<{ day: string; value: number; sortKey: string }>>()
  for (const row of rows ?? []) {
    if (!row.score_count) continue
    const labeled = labelDay(row.day)
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

function buildCallDays(results: EvaluatorResultRow[]): Array<{ day: string; calls: number }> {
  const buckets = new Map<string, { day: string; sortKey: string; calls: number }>()
  for (const row of results) {
    const { day, sortKey } = dayKey(row.timestamp)
    const bucket = buckets.get(sortKey) ?? { day, sortKey, calls: 0 }
    bucket.calls += 1
    buckets.set(sortKey, bucket)
  }
  return Array.from(buckets.values())
    .sort((a, b) => a.sortKey.localeCompare(b.sortKey))
    .map(({ day, calls }) => ({ day, calls }))
}

function buildDuration(results: EvaluatorResultRow[]): { average: number | null; points: Array<{ day: string; value: number }> } {
  const buckets = new Map<string, { day: string; sortKey: string; sum: number; count: number }>()
  let sum = 0
  let count = 0
  for (const row of results) {
    if (row.duration_seconds == null) continue
    sum += row.duration_seconds
    count += 1
    const { day, sortKey } = dayKey(row.timestamp)
    const bucket = buckets.get(sortKey) ?? { day, sortKey, sum: 0, count: 0 }
    bucket.sum += row.duration_seconds
    bucket.count += 1
    buckets.set(sortKey, bucket)
  }
  return {
    average: count ? sum / count : null,
    points: Array.from(buckets.values())
      .sort((a, b) => a.sortKey.localeCompare(b.sortKey))
      .map((bucket) => ({ day: bucket.day, value: Number((bucket.sum / bucket.count).toFixed(1)) })),
  }
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

function buildDays(results: EvaluatorResultRow[]): DayPoint[] {
  const buckets = new Map<string, DayPoint>()
  for (const row of results) {
    const { day, sortKey } = dayKey(row.timestamp)
    const bucket = buckets.get(sortKey) ?? { day, sortKey, completed: 0, failed: 0 }
    if (row.status === 'completed') bucket.completed += 1
    else if (row.status === 'failed') bucket.failed += 1
    buckets.set(sortKey, bucket)
  }
  return Array.from(buckets.values()).sort((a, b) => a.sortKey.localeCompare(b.sortKey))
}

function buildScoreSeries(results: EvaluatorResultRow[], metrics: CallImportMetricAggregate[]) {
  const series = new Map<string, Array<{ day: string; value: number }>>()
  for (const metric of metrics.filter(isNumericMetric)) {
    const buckets = new Map<string, { day: string; sortKey: string; sum: number; count: number }>()
    for (const row of results) {
      const score = row.metric_scores?.[metric.metric_id]
      const numeric = score
        ? metricNumericValue(score.value, score.type || metric.metric_type || '')
        : null
      if (numeric == null) continue
      const { day, sortKey } = dayKey(row.timestamp)
      const bucket = buckets.get(sortKey) ?? { day, sortKey, sum: 0, count: 0 }
      bucket.sum += numeric
      bucket.count += 1
      buckets.set(sortKey, bucket)
    }
    series.set(
      metric.metric_id,
      Array.from(buckets.values())
        .sort((a, b) => a.sortKey.localeCompare(b.sortKey))
        .map((bucket) => ({ day: bucket.day, value: Number((bucket.sum / bucket.count).toFixed(2)) })),
    )
  }
  return series
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
  callDays,
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
}: {
  widget: ResultsWidget
  canMoveUp: boolean
  canMoveDown: boolean
  metrics: CallImportMetricAggregate[]
  days: DayPoint[]
  callDays: Array<{ day: string; calls: number }>
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
}) {
  const [menuOpen, setMenuOpen] = useState(false)
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
  const model = panelModel(widget, {
    days,
    callDays,
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
  })

  return (
    <section
      ref={setNodeRef}
      style={{ transform: CSS.Transform.toString(transform), transition, opacity: isDragging ? 0.55 : 1 }}
      className="relative flex min-h-[280px] flex-col rounded-xl border border-gray-200 bg-white p-4 shadow-sm"
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
            <div className="absolute right-0 z-20 mt-1 w-36 rounded-lg border border-gray-200 bg-white py-1 shadow-lg">
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

      {widget.type === 'metric_usage' && (
        <MetricUsageFilters
          metrics={metrics}
          selectedId={trendMetric?.metric_id ?? null}
          onSelect={onMetric}
        />
      )}

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
      ) : widget.type === 'metric_usage' && trendMetric && trendMetric.count === 0 ? (
        <UnusedMetricList metrics={metrics} selectedId={trendMetric.metric_id} onSelect={onMetric} />
      ) : model.data.length === 0 ? (
        <button type="button" onClick={onOpenDetail} className="flex flex-1 flex-col items-center justify-center gap-2 text-sm text-gray-400">
          <span>No data in this window</span>
          <span className="text-[11px] font-medium">Show details</span>
        </button>
      ) : (
        <div onClick={onOpenDetail} className="relative min-h-[160px] flex-1 cursor-pointer text-left [&_.recharts-surface]:cursor-pointer">
          <PanelChart
            display={widget.display}
            data={model.data}
            series={model.series}
            layout={model.horizontal ? 'vertical' : 'horizontal'}
            onPoint={() => onOpenDetail()}
            onCategory={() => onOpenDetail()}
          />
          <span className="mt-2 block text-[11px] font-medium text-gray-400">Show details</span>
        </div>
      )}
    </section>
  )
}

function panelModel(
  widget: ResultsWidget,
  source: {
    days: DayPoint[]
    callDays: Array<{ day: string; calls: number }>
    duration: { average: number | null; points: Array<{ day: string; value: number }> }
    scenarioMatrix: Array<{ agentName: string; scenarioName: string; count: number }>
    scoreSeries: Map<string, Array<{ day: string; value: number }>>
    categorySeries: Map<string, { labels: string[]; data: Array<Record<string, string | number>> }>
    ops: EvaluatorResultsDashboardOpsResponse | undefined
    lowest: Array<{ name: string; value: number }>
    agentRows: Array<{ id: string; name: string; total: number; completed: number; failed: number; rate: number }>
    scenarioRows: Array<{ name: string; count: number }>
    primaryMetric: CallImportMetricAggregate | null
    trendMetric: CallImportMetricAggregate | null
    aggregateTotal: number
    aggregateCompleted: number
  },
): {
  headline: string
  caption?: string
  data: Array<Record<string, string | number>>
  series: Array<{ key: string; color: string; stack?: string }>
  horizontal?: boolean
} {
  const terminalDays = source.days
  if (widget.type === 'agent_cost') return agentCostCard(source.ops, widget.display)
  if (widget.type === 'model_cost') return modelCostCard(source.ops)
  if (widget.type === 'tool_calls') return toolCallCard(source.ops, widget.display)
  if (widget.type === 'total_calls') {
    const loaded = source.callDays.reduce((sum, day) => sum + day.calls, 0)
    return {
      headline: formatHeadline(source.aggregateTotal || loaded),
      caption: 'Calls in window',
      data: source.callDays.map((day) => ({ day: day.day, calls: day.calls })),
      series: [{ key: 'calls', color: PRIMARY }],
    }
  }
  if (widget.type === 'avg_duration') {
    return {
      headline: formatDuration(source.duration.average),
      caption: 'Average call length',
      data: source.duration.points,
      series: [{ key: 'value', color: PRIMARY }],
    }
  }
  if (widget.type === 'scenarios_by_agent') return scenarioStack(source.scenarioMatrix)
  if (widget.type === 'volume') {
    return {
      headline: formatHeadline(source.aggregateTotal),
      caption: 'Runs in window',
      data: terminalDays.map((day) => ({ day: day.day, completed: day.completed, failed: day.failed })),
      series: [
        { key: 'completed', color: PRIMARY, stack: 'runs' },
        { key: 'failed', color: FAIL, stack: 'runs' },
      ],
    }
  }
  if (widget.type === 'completion') {
    const rate = source.aggregateTotal ? (source.aggregateCompleted / source.aggregateTotal) * 100 : null
    return {
      headline: formatHeadline(rate, '%'),
      caption: 'Completed runs',
      data: terminalDays.map((day) => {
        const denom = day.completed + day.failed
        return { day: day.day, rate: denom ? Math.round((day.completed / denom) * 100) : 0 }
      }),
      series: [{ key: 'rate', color: PRIMARY }],
    }
  }
  if (widget.type === 'avg_score' || widget.type === 'metric_trend' || widget.type === 'metric_usage') {
    const metric = widget.type === 'avg_score' ? source.primaryMetric : source.trendMetric
    if (metric && metric.count === 0 && widget.type !== 'avg_score') {
      return {
        headline: 'Never scored',
        caption: metric.metric_name,
        data: [],
        series: [{ key: 'value', color: PRIMARY }],
      }
    }
    if (metric && widget.type !== 'avg_score' && isCategoricalMetric(metric)) {
      const category = source.categorySeries.get(metric.metric_id)
      if (category?.data.length) {
        return {
          headline: formatHeadline(metric.count),
          caption: metric.metric_name,
          data: category.data,
          series: categoryColors(category.labels),
        }
      }
      return {
        headline: formatHeadline(metric.count),
        caption: metric.metric_name,
        data: metric.value_counts.map((count) => ({ name: count.label, count: count.count })),
        series: [{ key: 'count', color: PRIMARY }],
        horizontal: true,
      }
    }
    const points = metric ? source.scoreSeries.get(metric.metric_id) ?? [] : []
    return {
      headline: formatHeadline(metric?.mean ?? null),
      caption: metric?.metric_name ?? 'No scored metric',
      data: points,
      series: [{ key: 'value', color: PRIMARY }],
    }
  }
  if (widget.type === 'lowest_metrics') {
    return {
      headline: formatHeadline(source.lowest[0]?.value ?? null),
      caption: 'Lowest mean first',
      data: source.lowest,
      series: [{ key: 'value', color: SERIES_MUTED }],
      horizontal: widget.display === 'bar',
    }
  }
  if (widget.type === 'agents') {
    return {
      headline: formatHeadline(source.agentRows.length),
      caption: 'Agents in this window',
      data: source.agentRows.map((row) => ({ name: row.name, total: row.total })),
      series: [{ key: 'total', color: PRIMARY }],
      horizontal: widget.display === 'bar',
    }
  }
  return {
    headline: formatHeadline(source.scenarioRows.reduce((sum, row) => sum + row.count, 0)),
    caption: 'Scenario runs',
    data: source.scenarioRows.map((row) => ({ name: row.name, count: row.count })),
    series: [{ key: 'count', color: PRIMARY }],
    horizontal: widget.display === 'bar',
  }
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
  onPoint: (label: string, detail: string) => void
  onCategory: (name: string) => void
  listClassName?: string
}) {
  const categoryKey = data[0] && 'name' in data[0] ? 'name' : 'day'
  const handleClick = (state: { activeLabel?: string | number; activePayload?: Array<{ name?: string; value?: number }> }) => {
    if (state?.activeLabel == null) return
    const label = String(state.activeLabel)
    const detail = (state.activePayload ?? [])
      .map((item) => `${item.name}: ${item.value ?? 0}`)
      .join(' · ')
    if (categoryKey === 'name') {
      onCategory(label)
      return
    }
    onPoint(label, detail || 'No values')
  }

  const grid = <CartesianGrid stroke={GRID} vertical={false} />
  const tooltip = <Tooltip content={<BreakdownTooltip />} cursor={{ fill: '#f9fafb' }} />

  if (layout === 'stacked') {
    return (
      <ResponsiveContainer width="100%" height="100%">
        <BarChart layout="vertical" data={data} margin={{ top: 4, right: 12, left: 4, bottom: 4 }}>
          <XAxis type="number" hide />
          <YAxis type="category" dataKey="name" width={120} tick={{ fontSize: 11, fill: '#4b5563' }} />
          <Tooltip content={<BreakdownTooltip />} cursor={{ fill: '#f9fafb' }} />
          {series.map((item) => (
            <Bar
              key={item.key}
              dataKey={item.key}
              name={item.key}
              stackId={item.stack ?? 'agents'}
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
  model: ReturnType<typeof panelModel> | null,
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
      { id: 'both', label: 'Both', headline: model.headline, caption: 'Completed and failed', data: model.data, series: model.series },
      { id: 'completed', label: 'Completed', headline: formatHeadline(completed), caption: 'Completed runs', data: days.map((day) => ({ day: day.day, completed: day.completed })), series: [{ key: 'completed', color: PRIMARY }] },
      { id: 'failed', label: 'Failed', headline: formatHeadline(failed), caption: 'Failed runs', data: days.map((day) => ({ day: day.day, failed: day.failed })), series: [{ key: 'failed', color: FAIL }] },
    ]
  }
  if (type === 'completion') {
    return [
      { id: 'rate', label: 'Rate', headline: model.headline, caption: 'Completion rate', data: model.data, series: model.series },
      { id: 'counts', label: 'Counts', headline: formatHeadline(days.reduce((sum, day) => sum + day.completed + day.failed, 0)), caption: 'Completed and failed counts', data: days.map((day) => ({ day: day.day, completed: day.completed, failed: day.failed })), series: [{ key: 'completed', color: PRIMARY, stack: 'runs' }, { key: 'failed', color: FAIL, stack: 'runs' }] },
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

function ResultsDetailView({
  detail,
  widgets,
  metrics,
  days,
  callDays,
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
  onMetric,
}: {
  detail: { kind: 'widget'; widgetId: string } | { kind: 'metric'; metricId: string } | { kind: 'agent'; agentId: string }
  widgets: ResultsWidget[]
  metrics: CallImportMetricAggregate[]
  days: DayPoint[]
  callDays: Array<{ day: string; calls: number }>
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
    ? panelModel(widget, {
      days,
      callDays,
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
  const recent = metric
    ? results.filter((row) => row.metric_scores?.[metric.metric_id]).slice(0, 12)
    : results.slice(0, 12)
  const [focusId, setFocusId] = useState<string | null>(null)
  const [durationDisplay, setDurationDisplay] = useState<ResultsChartType>(widget?.display ?? 'line')
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
          return { id: mode, label: mode === 'calls' ? 'Calls' : 'Errors', ...chart }
        })
        : baseViews
  const [viewId, setViewId] = useState(views[0]?.id ?? 'main')
  const active = views.find((view) => view.id === viewId) ?? views[0]
  const costRole = widget?.type === 'agent_cost' && active?.id !== 'all' ? active?.id ?? null : null
  const focusedAgent = ops?.cost_by_agent.find((agent) => agent.agent_id === focusId)
  const focusedModels = modelsForAgent(focusedAgent, widget?.type === 'agent_cost' ? costRole : null)

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
            <p className="mt-1 text-3xl font-semibold tracking-tight text-gray-900">{active?.headline ?? model?.headline ?? '—'}</p>
            {active?.caption && <p className="mt-1 text-sm text-gray-500">{active.caption}</p>}
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
        {widget?.type === 'avg_duration' && <DurationSummary results={results} />}
        {active && active.data.length > 0 && (
          <div className="mt-4 h-[320px] cursor-pointer [&_.recharts-surface]:cursor-pointer">
            <PanelChart
              display={widget?.type === 'avg_duration' ? durationDisplay : widget?.display ?? 'bar'}
              data={active.data}
              series={active.series}
              layout={active.horizontal ? 'vertical' : 'horizontal'}
              listClassName="max-h-[320px]"
              onPoint={() => undefined}
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
              {focusId && (
                <button type="button" onClick={() => setFocusId(null)} className="text-xs font-medium text-gray-500 hover:text-gray-800">
                  All agents
                </button>
              )}
            </div>
            <ul className="divide-y divide-gray-100">
              {ops?.cost_by_agent.map((agent) => (
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
              {toolAgentTotals(ops).map((item) => (
                <li key={item.agent_id}>
                  <button
                    type="button"
                    onClick={() => setFocusId(item.agent_id)}
                    className="flex w-full items-center justify-between py-2 text-left text-sm text-gray-700 hover:text-gray-900"
                  >
                    <span className="truncate">{item.agent_name}</span>
                    <span className="shrink-0 text-xs text-gray-500">{item.calls.toLocaleString()} calls</span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
        {(widget?.type === 'avg_duration' || widget?.type === 'total_calls' || widget?.type === 'scenarios_by_agent') && (
          <DurationBreakdown results={results} />
        )}
        {widget?.type === 'metric_usage' && metric && <MetricScenarioScores results={results} metricId={metric.metric_id} />}
        {agent && (
          <div className="mt-4 flex flex-wrap gap-2">
            <button type="button" onClick={() => onSelectAgent(agent.id)} className="rounded-lg border border-gray-200 px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50">
              Filter dashboard to this agent
            </button>
          </div>
        )}
      </section>
      {detail.kind === 'agent' && (
        <section className="rounded-xl border border-gray-200 bg-white p-5">
          <h3 className="text-sm font-semibold text-gray-900">Scenarios</h3>
          <ul className="mt-3 divide-y divide-gray-100">
            {scenarioRows.filter((row) => row.agentId === detail.agentId).map((row) => (
              <li key={row.scenarioId}>
                <button
                  type="button"
                  onClick={() => onSelectScenario(row.suiteId, row.scenarioId, row.agentId)}
                  className="flex w-full items-center justify-between py-2 text-left text-sm text-gray-800 hover:text-primary-700"
                >
                  <span>{row.name}</span>
                  <span className="text-xs text-gray-500">{row.count} runs</span>
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}
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
                    onClick={() => onOpenResult(row.result_id || row.id)}
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

function MetricScenarioScores({ results, metricId }: { results: EvaluatorResultRow[]; metricId: string }) {
  const groups = new Map<string, { sum: number; count: number; failed: number }>()
  for (const row of results) {
    const name = row.scenario?.name
    if (!name) continue
    const score = row.metric_scores?.[metricId]
    const bucket = groups.get(name) ?? { sum: 0, count: 0, failed: 0 }
    if (row.status === 'failed') bucket.failed += 1
    const value = typeof score?.value === 'number' ? score.value : Number(score?.value)
    if (!Number.isNaN(value) && score) {
      bucket.sum += value
      bucket.count += 1
    }
    groups.set(name, bucket)
  }
  const rows = Array.from(groups.entries()).sort((a, b) => b[1].count - a[1].count)
  if (!rows.length) return <p className="mt-4 text-sm text-gray-400">No scored runs for this metric.</p>
  return (
    <div className="mt-4">
      <h3 className="text-sm font-semibold text-gray-900">By scenario</h3>
      <ul className="mt-2 divide-y divide-gray-100">
        {rows.map(([name, stats]) => (
          <li key={name} className="flex items-center justify-between py-2 text-sm text-gray-700">
            <span className="truncate pr-3">{name}</span>
            <span className="shrink-0 text-xs text-gray-500">
              {stats.count ? `avg ${(stats.sum / stats.count).toFixed(2)}` : 'never scored'}
              {` · ${stats.failed} failed`}
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

function DurationBreakdown({ results }: { results: EvaluatorResultRow[] }) {
  const values = results.map((row) => row.duration_seconds).filter((value): value is number => value != null)
  const edges = [0, 60, 90, 120, 150, 180, 240]
  const buckets = edges.slice(0, -1).map((start, index) => {
    const end = edges[index + 1]
    const count = values.filter((value) => value >= start && value < end).length
    return { name: `${start}–${end}s`, count }
  }).filter((bucket) => bucket.count > 0)
  const max = Math.max(...buckets.map((bucket) => bucket.count), 1)
  const byScenario = new Map<string, { total: number; failed: number }>()
  for (const row of results) {
    const name = row.scenario?.name
    if (!name) continue
    const bucket = byScenario.get(name) ?? { total: 0, failed: 0 }
    bucket.total += 1
    if (row.status === 'failed') bucket.failed += 1
    byScenario.set(name, bucket)
  }
  const scenarios = Array.from(byScenario.entries()).sort((a, b) => b[1].total - a[1].total)
  return (
    <div className="mt-4 space-y-4">
      <div>
        <h3 className="text-sm font-semibold text-gray-900">Distribution</h3>
        <ul className="mt-3 space-y-2">
          {buckets.map((bucket) => (
            <li key={bucket.name} className="grid grid-cols-[7rem_minmax(0,1fr)_2rem] items-center gap-3 text-xs text-gray-600">
              <span>{bucket.name}</span>
              <span className="h-2 overflow-hidden rounded-full bg-gray-100">
                <span className="block h-full rounded-full bg-primary-600" style={{ width: `${(bucket.count / max) * 100}%` }} />
              </span>
              <span className="text-right">{bucket.count}</span>
            </li>
          ))}
        </ul>
      </div>
      <div>
        <h3 className="text-sm font-semibold text-gray-900">By scenario</h3>
        <ul className="mt-2 divide-y divide-gray-100">
          {scenarios.map(([name, stats]) => (
            <li key={name} className="flex items-center justify-between py-2 text-sm text-gray-700">
              <span className="truncate pr-3">{name}</span>
              <span className="shrink-0 text-xs text-gray-500">
                {stats.total} · {stats.total ? Math.round((stats.failed / stats.total) * 100) : 0}% fail
              </span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}

function OverviewStats({
  section,
  ops,
  spend,
  products,
}: {
  section: 'usage' | 'tool_calls' | 'tools'
  ops: EvaluatorResultsDashboardOpsResponse | undefined
  spend: { most: string; least: string; highest: string } | null
  products: { most: string; least: string; empty: string } | null
}) {
  const byAgent = new Map<string, number>()
  const byTool = new Map<string, number>()
  if (section === 'tool_calls') {
    for (const row of ops?.tool_calls_by_agent_day ?? []) {
      byAgent.set(row.agent_name, (byAgent.get(row.agent_name) ?? 0) + row.calls)
    }
    for (const row of ops?.tool_calls_by_tool ?? []) {
      byTool.set(row.tool, (byTool.get(row.tool) ?? 0) + row.calls)
    }
  }
  const busiest = Array.from(byAgent.entries()).sort((a, b) => b[1] - a[1])[0]?.[0] ?? '—'
  const topUse = Array.from(byTool.entries()).sort((a, b) => b[1] - a[1])[0]?.[0] ?? '—'
  const totalCalls = Array.from(byAgent.values()).reduce((sum, value) => sum + value, 0)
  const calls = section === 'tool_calls'
    ? { busiest, topUse, total: totalCalls.toLocaleString() }
    : null
  if (!spend && !products && !calls) return null
  return (
    <dl className="mt-4 grid grid-cols-3 gap-2">
      {spend && (
        <>
          <Stat label="Highest spend" value={spend.most} />
          <Stat label="Lowest spend" value={spend.least} />
          <Stat label="Top model cost" value={spend.highest} />
        </>
      )}
      {products && (
        <>
          <Stat label="Most used" value={products.most} />
          <Stat label="Least used" value={products.least} />
          <Stat label="Calls with no tools" value={products.empty} />
        </>
      )}
      {calls && (
        <>
          <Stat label="Busiest agent" value={calls.busiest} />
          <Stat label="Top use case" value={calls.topUse} />
          <Stat label="Total calls" value={calls.total} />
        </>
      )}
    </dl>
  )
}

function PlatformCard({
  title,
  model,
  onOpen,
}: {
  title: string
  model: {
    headline: string
    caption?: string
    data: Array<Record<string, string | number>>
    series: Array<{ key: string; color: string; stack?: string }>
    horizontal?: boolean
  }
  onOpen: () => void
}) {
  return (
    <section className="flex min-h-[280px] flex-col rounded-xl border border-gray-200 bg-white p-4 shadow-sm">
      <h3 className="text-sm font-semibold text-gray-900">{title}</h3>
      <p className="mt-1 text-2xl font-semibold tracking-tight text-gray-900">{model.headline}</p>
      {model.caption && <p className="mt-0.5 text-xs text-gray-500">{model.caption}</p>}
      {model.data.length === 0 ? (
        <button type="button" onClick={onOpen} className="mt-4 flex flex-1 items-center justify-center text-sm text-gray-400">
          No data in this window
        </button>
      ) : (
        <div onClick={onOpen} className="mt-3 min-h-[160px] flex-1 cursor-pointer [&_.recharts-surface]:cursor-pointer">
          <PanelChart
            display={model.horizontal ? 'bar' : 'line'}
            data={model.data}
            series={model.series}
            layout={model.horizontal ? 'vertical' : 'horizontal'}
            onPoint={() => onOpen()}
            onCategory={() => onOpen()}
          />
          <span className="mt-2 block text-[11px] font-medium text-gray-400">Show details</span>
        </div>
      )}
    </section>
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

function PlatformDetail({
  section,
  ops,
  calls,
  onBack,
  onOpenRuns,
  onOpenResult,
}: {
  section: 'usage' | 'tool_calls' | 'tools'
  ops: EvaluatorResultsDashboardOpsResponse | undefined
  calls: DashboardDrillCall[]
  onBack: () => void
  onOpenRuns: () => void
  onOpenResult: (resultId: string) => void
}) {
  const views = section === 'usage'
    ? [
      { id: 'stt', label: 'STT models' },
      { id: 'tts', label: 'TTS models' },
      { id: 'llm', label: 'LLM models' },
      ...(usageHasS2S(ops) ? [{ id: 's2s', label: 'S2S models' }] : []),
      { id: 'price_minute', label: 'Price / minute' },
      { id: 'price_million', label: 'Price / 1M tokens' },
    ]
    : section === 'tool_calls'
      ? [
        { id: 'over_time', label: 'Over time' },
        { id: 'per_call', label: 'Per call' },
        { id: 'use_cases', label: 'Use cases' },
      ]
      : [
        { id: 'share', label: 'Share' },
        { id: 'over_time', label: 'Over time' },
        { id: 'by_agent', label: 'By agent' },
      ]
  const [viewId, setViewId] = useState(views[0]?.id ?? 'main')
  const [focus, setFocus] = useState<string | null>(null)
  const [leaf, setLeaf] = useState<{ kind: 'model' | 'use_case' | 'product'; name: string } | null>(null)
  const activeId = views.some((view) => view.id === viewId) ? viewId : views[0]?.id
  const chart = section === 'usage'
    ? usageDetail(ops, activeId, focus)
    : section === 'tool_calls'
      ? platformToolDetail(ops, activeId, focus)
      : toolsDetail(ops, activeId, focus)
  const spend = section === 'usage' ? usageFacts(ops) : null
  const products = section === 'tools' ? toolFacts(ops) : null
  const title = section === 'usage' ? 'Usage' : section === 'tool_calls' ? 'Tool calls' : 'Tools'
  const openLeaf = (name: string) => {
    if (section === 'usage' && activeId !== 'price_minute' && activeId !== 'price_million') {
      setLeaf({ kind: 'model', name })
      return
    }
    if (section === 'tool_calls' && activeId === 'use_cases') {
      setLeaf({ kind: 'use_case', name })
      return
    }
    if (section === 'tools' && activeId === 'share') {
      setLeaf({ kind: 'product', name })
      return
    }
    setFocus(name)
  }

  if (leaf) {
    return (
      <ChartLeaf
        kind={leaf.kind}
        name={leaf.name}
        ops={ops}
        calls={calls}
        onBack={() => setLeaf(null)}
        onOpenRelated={(next) => setLeaf(next)}
        onOpenResult={onOpenResult}
      />
    )
  }

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
            <p className="mt-1 text-3xl font-semibold tracking-tight text-gray-900">{chart.headline}</p>
            {chart.caption && <p className="mt-1 text-sm text-gray-500">{chart.caption}</p>}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <div className="flex flex-wrap items-center gap-0.5 rounded-lg border border-gray-200 bg-gray-50 p-0.5">
              {views.map((view) => (
                <button
                  key={view.id}
                  type="button"
                  onClick={() => {
                    setFocus(null)
                    setViewId(view.id)
                  }}
                  className={`rounded-md px-2.5 py-1 text-xs font-medium ${activeId === view.id
                    ? 'border border-primary-200 bg-white text-primary-800 shadow-sm'
                    : 'border border-transparent text-gray-600 hover:text-gray-900'
                    }`}
                >
                  {view.label}
                </button>
              ))}
            </div>
            <button type="button" onClick={onOpenRuns} className="rounded-md bg-primary-700 px-2.5 py-1 text-xs font-medium text-white hover:bg-primary-800">
              View runs
            </button>
          </div>
        </div>
        <OverviewStats section={section} ops={ops} spend={spend} products={products} />
        {chart.data.length > 0 && (
          <div className="mt-4 h-[320px] cursor-pointer [&_.recharts-surface]:cursor-pointer">
            <PanelChart
              display={chart.stacked || chart.horizontal ? 'bar' : 'line'}
              data={chart.data}
              series={chart.series}
              layout={chart.stacked ? 'stacked' : chart.horizontal ? 'vertical' : 'horizontal'}
              listClassName="max-h-[320px]"
              onPoint={() => undefined}
              onCategory={openLeaf}
            />
          </div>
        )}
        {section === 'usage' && (activeId === 'price_minute' || activeId === 'price_million') && (
          <div className="mt-3 flex flex-wrap gap-2">
            {chart.series.map((item) => (
              <button
                key={item.key}
                type="button"
                onClick={() => setLeaf({ kind: 'model', name: item.key })}
                className="rounded-full border border-gray-200 px-2.5 py-1 text-xs font-medium text-gray-700 hover:border-primary-300 hover:text-primary-800"
              >
                {item.key}
              </button>
            ))}
          </div>
        )}
        {focus && (
          <button type="button" onClick={() => setFocus(null)} className="mt-3 text-xs font-medium text-gray-500 hover:text-gray-800">
            Show all
          </button>
        )}
      </section>
    </div>
  )
}

function callUses(call: DashboardDrillCall): Array<{ tool: string; provider: string; failed: boolean }> {
  if (call.uses?.length) return call.uses
  if (!call.tool && !call.provider) return []
  return [{ tool: call.tool, provider: call.provider, failed: false }]
}

function ChartLeaf({
  kind,
  name,
  ops,
  calls,
  onBack,
  onOpenRelated,
  onOpenResult,
}: {
  kind: 'model' | 'use_case' | 'product'
  name: string
  ops: EvaluatorResultsDashboardOpsResponse | undefined
  calls: DashboardDrillCall[]
  onBack: () => void
  onOpenRelated: (next: { kind: 'model' | 'use_case' | 'product'; name: string }) => void
  onOpenResult: (resultId: string) => void
}) {
  const layer = ops?.model_layers.find((row) => row.model === name)
  const matched = calls.filter((call) => {
    const uses = callUses(call)
    if (kind === 'model') return call.model === name
    if (kind === 'use_case') return uses.some((use) => use.tool === name) || call.tool === name
    return uses.some((use) => use.provider === name) || call.provider === name
  })
  const rows = (matched.length ? matched : []).slice().sort((a, b) => b.tokens - a.tokens || b.costUsd - a.costUsd)
  const byDay = new Map<string, number>()
  for (const call of rows) {
    const day = call.at.slice(0, 10)
    const uses = callUses(call).filter((use) => kind === 'product' ? use.provider === name : kind === 'use_case' ? use.tool === name : true)
    byDay.set(day, (byDay.get(day) ?? 0) + (kind === 'model' ? call.costUsd : Math.max(uses.length, 1)))
  }
  const series = Array.from(byDay.entries()).sort(([a], [b]) => a.localeCompare(b)).map(([day, value]) => ({
    day: new Date(`${day}T12:00:00`).toLocaleDateString(undefined, { month: 'numeric', day: 'numeric' }),
    value: Number(value.toFixed(3)),
  }))
  const unit = layer?.usd_per_minute ? '$ / minute' : layer?.usd_per_million_tokens ? '$ / 1M tokens' : 'usage'
  const useCaseCounts = new Map<string, { calls: number; failed: number }>()
  const hostCounts = new Map<string, number>()
  for (const call of rows) {
    for (const use of callUses(call)) {
      if (kind === 'product' && use.provider === name) {
        const bucket = useCaseCounts.get(use.tool) ?? { calls: 0, failed: 0 }
        bucket.calls += 1
        if (use.failed) bucket.failed += 1
        useCaseCounts.set(use.tool, bucket)
      }
      if (kind === 'use_case' && use.tool === name) {
        hostCounts.set(use.provider, (hostCounts.get(use.provider) ?? 0) + 1)
      }
    }
  }
  const useCases = Array.from(useCaseCounts.entries()).sort((a, b) => b[1].calls - a[1].calls)
  const host = Array.from(hostCounts.entries()).sort((a, b) => b[1] - a[1])[0]?.[0]
  const eyebrow = kind === 'model' ? 'Model' : kind === 'use_case' ? 'Use case' : 'Tool'
  const subtitle = kind === 'model' ? `${(layer?.usage_kind || 'model').toUpperCase()} · ${unit}` : kind === 'use_case' ? 'What the agent asked the tool to do' : 'Product the agents connect to'
  const listTitle = kind === 'product' ? 'Calls using this tool' : kind === 'use_case' ? 'Calls using this use case' : 'Calls · most tokens first'

  return (
    <div className="space-y-4">
      <button type="button" onClick={onBack} className="inline-flex items-center gap-1 text-sm font-medium text-gray-600 hover:text-gray-900">
        <ArrowLeft className="h-4 w-4" />
        Back
      </button>
      <div>
        <p className="text-[11px] font-semibold uppercase tracking-wide text-gray-400">{eyebrow}</p>
        <h2 className="text-lg font-semibold text-gray-900">{name}</h2>
        <p className="mt-1 text-sm text-gray-500">{subtitle}</p>
        {kind === 'use_case' && host && (
          <button type="button" onClick={() => onOpenRelated({ kind: 'product', name: host })} className="mt-1 text-sm font-medium text-primary-700 hover:underline">
            Runs on {host}
          </button>
        )}
      </div>
      {useCases.length > 0 && (
        <section className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
          <h3 className="text-sm font-semibold text-gray-900">Use cases on this tool</h3>
          <ul className="mt-3 divide-y divide-gray-100">
            {useCases.map(([tool, stats]) => (
              <li key={tool}>
                <button type="button" onClick={() => onOpenRelated({ kind: 'use_case', name: tool })} className="flex w-full items-center justify-between py-2 text-left text-sm text-gray-800 hover:text-primary-700">
                  <span>{tool}</span>
                  <span className="text-xs text-gray-500">{stats.calls} uses{stats.failed ? ` · ${stats.failed} failed` : ''}</span>
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}
      <section className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
        <p className="mb-2 text-sm font-medium text-gray-900">Usage over time</p>
        {series.length > 0 && (
          <div className="h-64">
            <PanelChart
              display="area"
              data={series}
              series={[{ key: 'value', color: PRIMARY }]}
              layout="horizontal"
              onPoint={() => undefined}
              onCategory={() => undefined}
            />
          </div>
        )}
      </section>
      <section className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
        <h3 className="text-sm font-semibold text-gray-900">{listTitle}</h3>
        <ul className="mt-3 divide-y divide-gray-100">
          {rows.map((call) => {
            const uses = callUses(call).filter((use) => kind === 'product' ? use.provider === name : kind === 'use_case' ? use.tool === name : true)
            const failed = uses.filter((use) => use.failed).length
            const names = Array.from(new Set(uses.map((use) => use.tool).filter(Boolean)))
            const detail = uses.length
              ? `${uses.length} use${uses.length === 1 ? '' : 's'}${failed ? ` · ${failed} failed` : ''}${kind === 'product' && names.length ? ` · ${names.join(', ')}` : ''}`
              : null
            return (
              <li key={`${call.at}-${call.agent}-${call.title}`}>
                <button
                  type="button"
                  onClick={() => call.resultId && onOpenResult(call.resultId)}
                  className="flex w-full flex-wrap items-center justify-between gap-3 py-2 text-left text-sm text-gray-700 hover:text-gray-900"
                >
                  <span className="min-w-0">
                    <span className="block text-xs text-gray-500">{formatCallTime(call.at)} · {call.agent}</span>
                    <span className="block truncate font-medium text-gray-900">{call.title}</span>
                    {detail && <span className="block text-xs text-gray-500">{detail}</span>}
                  </span>
                  <span className="shrink-0 text-xs text-gray-500">
                    {formatDuration(call.durationSeconds)}
                    {call.costUsd ? ` · ${formatUsd(call.costUsd)}` : ''}
                    {call.tokens ? ` · ${call.tokens.toLocaleString()} tok` : ''}
                  </span>
                </button>
              </li>
            )
          })}
        </ul>
      </section>
    </div>
  )
}

function formatCallTime(iso: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  return date.toLocaleString(undefined, { day: '2-digit', month: 'numeric', year: 'numeric', hour: '2-digit', minute: '2-digit' })
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
