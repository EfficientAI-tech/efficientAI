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
  EvaluatorResultRow,
  EvaluatorResultsAgentSummary,
} from '../../../types/api'
import { dateRangeToSinceUntil, rangeForDays } from './resultsDateRange'
import {
  CHART_TYPE_LABELS,
  MAX_VISIBLE_WIDGETS,
  WIDGET_LABELS,
  readResultsDashboardLayout,
  visibleWidgets,
  writeResultsDashboardLayout,
  type ResultsChartType,
  type ResultsWidget,
  type ResultsWidgetType,
} from './resultsDashboardLayout'

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
  agents: EvaluatorResultsAgentSummary[]
  onSelectAgent: (agentId: string) => void
  onSelectScenario: (suiteId: string, scenarioId: string, agentId: string) => void
  onOpenRuns: () => void
  onOpenResult: (resultId: string) => void
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

export default function ResultsDashboardTab({
  agentId,
  suiteId,
  scenarioId,
  startDate,
  endDate,
  agents,
  onSelectAgent,
  onSelectScenario,
  onOpenRuns,
  onOpenResult,
}: ResultsDashboardTabProps) {
  const [widgets, setWidgets] = useState<ResultsWidget[]>(readResultsDashboardLayout)
  const [addOpen, setAddOpen] = useState(false)
  const [source, setSource] = useState<'simulation' | 'live'>('simulation')
  const playground = source === 'live'
  const [detail, setDetail] = useState<
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
    if (startDate && endDate) return { start: startDate, end: endDate }
    return rangeForDays(7)
  }, [startDate, endDate])

  const dateBounds = useMemo(
    () => dateRangeToSinceUntil(effectiveDateRange.start, effectiveDateRange.end),
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

  const { data: aggregate, isLoading: loadingAggregate } = useQuery({
    queryKey: ['evaluator-results-aggregate', listParams],
    queryFn: () =>
      apiClient.getEvaluatorResultsAggregate({
        agentId: agentId || undefined,
        suiteId: suiteId || undefined,
        scenarioId: scenarioId || undefined,
        since: dateBounds.since,
        until: dateBounds.until,
        playground,
      }),
  })

  const { data: listResponse, isLoading: loadingResults } = useQuery({
    queryKey: ['evaluator-results-dashboard', listParams],
    queryFn: () => apiClient.listEvaluatorResults(listParams),
  })

  const results = itemsOf<EvaluatorResultRow>(listResponse)
  const totalInRange = listResponse?.total ?? aggregate?.total_rows ?? 0
  const truncated = totalInRange > TRENDS_PAGE_LIMIT
  const metrics = aggregate?.metrics ?? []
  const primaryMetric = useMemo(
    () =>
      [...metrics]
        .filter(isNumericMetric)
        .sort((a, b) => b.count - a.count)[0] ?? null,
    [metrics],
  )

  const days = useMemo(() => buildDays(results), [results])
  const scoreSeries = useMemo(() => buildScoreSeries(results, metrics), [results, metrics])
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

  const scenarioRows = useMemo(
    () => collectScenarios(agents, agentId, suiteId),
    [agents, agentId, suiteId],
  )
  const agentRows = useMemo(() => {
    const source = agentId ? agents.filter((agent) => agent.agent_id === agentId) : agents
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
  }, [agents, agentId])

  const shown = visibleWidgets(widgets)
  const visibleCount = widgets.filter((widget) => !widget.hidden).length
  const loading = loadingAggregate || loadingResults

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

  const addWidget = (type: ResultsWidgetType) => {
    if (visibleCount >= MAX_VISIBLE_WIDGETS) return
    const existing = widgets.find((widget) => widget.type === type)
    if (existing) {
      update(widgets.map((widget) => (widget.id === existing.id ? { ...widget, hidden: false } : widget)))
    } else {
      update([
        ...widgets,
        {
          id: type,
          type,
          display: type === 'completion' || type === 'avg_score' || type === 'metric_trend' ? 'line' : 'bar',
          metricId: type === 'metric_trend' ? primaryMetric?.metric_id ?? null : null,
        },
      ])
    }
    setAddOpen(false)
  }

  const setMetric = (id: string, metricId: string) => {
    update(widgets.map((widget) => (widget.id === id ? { ...widget, metricId } : widget)))
  }

  if (loading && !aggregate && !results.length) {
    return (
      <div className="flex items-center justify-center py-16 text-gray-500">
        <Loader className="mr-2 h-5 w-5 animate-spin" />
        Loading dashboard…
      </div>
    )
  }

  if (detail) {
    return (
      <ResultsDetailView
        detail={detail}
        widgets={widgets}
        metrics={metrics}
        days={days}
        scoreSeries={scoreSeries}
        lowest={lowest}
        agentRows={agentRows}
        scenarioRows={scenarioRows}
        primaryMetric={primaryMetric}
        results={results}
        aggregateTotal={aggregate?.total_rows ?? results.length}
        aggregateCompleted={aggregate?.completed_rows ?? 0}
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
      />
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-xs text-gray-500">
          {startDate && endDate
            ? `${effectiveDateRange.start} → ${effectiveDateRange.end}`
            : `Last 7 days (${effectiveDateRange.start} → ${effectiveDateRange.end})`}
          {truncated ? ` · trends use the newest ${TRENDS_PAGE_LIMIT.toLocaleString()} of ${totalInRange.toLocaleString()} runs` : ''}
        </p>
        <div className="flex items-center gap-2">
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
              <div className="absolute right-0 z-20 mt-1 w-48 rounded-lg border border-gray-200 bg-white py-1 shadow-lg">
                {(Object.keys(WIDGET_LABELS) as ResultsWidgetType[]).map((type) => {
                  const alreadyVisible = widgets.some((widget) => widget.type === type && !widget.hidden)
                  return (
                    <button
                      key={type}
                      type="button"
                      disabled={alreadyVisible || visibleCount >= MAX_VISIBLE_WIDGETS}
                      onClick={() => addWidget(type)}
                      className="block w-full px-3 py-1.5 text-left text-xs text-gray-700 hover:bg-gray-50 disabled:text-gray-300"
                    >
                      {WIDGET_LABELS[type]}
                    </button>
                  )
                })}
              </div>
            )}
          </div>
          <button
            type="button"
            onClick={() => update(readDefaultWidgets())}
            className="inline-flex items-center gap-1 rounded-lg border border-gray-200 bg-white px-2.5 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50"
          >
            <RotateCcw className="h-3.5 w-3.5" />
            Reset
          </button>
        </div>
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
                  scoreSeries={scoreSeries}
                  lowest={lowest}
                  agentRows={agentRows}
                  scenarioRows={scenarioRows}
                  primaryMetric={primaryMetric}
                  aggregateTotal={aggregate?.total_rows ?? results.length}
                  aggregateCompleted={aggregate?.completed_rows ?? 0}
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
    </div>
  )
}

function readDefaultWidgets(): ResultsWidget[] {
  return [
    { id: 'volume', type: 'volume', display: 'bar' },
    { id: 'completion', type: 'completion', display: 'line' },
    { id: 'avg_score', type: 'avg_score', display: 'line' },
    { id: 'lowest_metrics', type: 'lowest_metrics', display: 'bar' },
    { id: 'agents', type: 'agents', display: 'bar' },
    { id: 'scenarios', type: 'scenarios', display: 'bar' },
  ]
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
  scoreSeries,
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
  scoreSeries: Map<string, Array<{ day: string; value: number }>>
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
    scoreSeries,
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
    scoreSeries: Map<string, Array<{ day: string; value: number }>>
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
  if (widget.type === 'avg_score' || widget.type === 'metric_trend') {
    const metric = widget.type === 'metric_trend' ? source.trendMetric : source.primaryMetric
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
  layout: 'horizontal' | 'vertical'
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
  const tooltip = (
    <Tooltip
      cursor={{ fill: '#f9fafb' }}
      contentStyle={{ border: '1px solid #e5e7eb', borderRadius: 8, fontSize: 12 }}
    />
  )

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
  if (type === 'avg_score' || type === 'metric_trend') {
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
  scoreSeries,
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
}: {
  detail: { kind: 'widget'; widgetId: string } | { kind: 'metric'; metricId: string } | { kind: 'agent'; agentId: string }
  widgets: ResultsWidget[]
  metrics: CallImportMetricAggregate[]
  days: DayPoint[]
  scoreSeries: Map<string, Array<{ day: string; value: number }>>
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
}) {
  const widget = detail.kind === 'widget' ? widgets.find((item) => item.id === detail.widgetId) : null
  const metric = detail.kind === 'metric'
    ? metrics.find((item) => item.metric_id === detail.metricId) ?? null
    : widget?.type === 'metric_trend'
      ? metrics.find((item) => item.metric_id === widget.metricId) ?? primaryMetric
      : widget?.type === 'avg_score'
        ? primaryMetric
        : null
  const agent = detail.kind === 'agent' ? agentRows.find((row) => row.id === detail.agentId) : null
  const title = detail.kind === 'metric'
    ? metric?.metric_name ?? 'Metric'
    : detail.kind === 'agent'
      ? agent?.name ?? 'Agent'
      : widget ? WIDGET_LABELS[widget.type] : 'Details'
  const metricSeries = metric ? scoreSeries.get(metric.metric_id) ?? [] : []
  const model = widget
    ? panelModel(widget, {
      days,
      scoreSeries,
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
  const views = buildDetailViews(widget?.type, model, days, lowest, agentRows, scenarioRows, metric)
  const [viewId, setViewId] = useState(views[0]?.id ?? 'main')
  const active = views.find((view) => view.id === viewId) ?? views[0]

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
              <div className="flex items-center rounded-lg bg-gray-100 p-0.5">
                {views.map((view) => (
                  <button
                    key={view.id}
                    type="button"
                    onClick={() => setViewId(view.id)}
                    className={`rounded-md px-2.5 py-1 text-xs font-medium ${active?.id === view.id ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-500 hover:text-gray-800'}`}
                  >
                    {view.label}
                  </button>
                ))}
              </div>
            )}
            <button type="button" onClick={onOpenRuns} className="rounded-lg bg-gray-900 px-3 py-1.5 text-xs font-medium text-white">
              View runs
            </button>
          </div>
        </div>
        {active && active.data.length > 0 && (
          <div className="mt-4 h-[320px] cursor-pointer [&_.recharts-surface]:cursor-pointer">
            <PanelChart
              display={widget?.display ?? 'bar'}
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
        {metric && (
          <dl className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Stat label="Mean" value={formatHeadline(metric.mean)} />
            <Stat label="Median" value={formatHeadline(metric.median)} />
            <Stat label="Scored" value={formatHeadline(metric.count)} />
            <Stat label="Skipped" value={formatHeadline(metric.skipped_count)} />
          </dl>
        )}
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

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-gray-100 px-3 py-2">
      <dt className="text-[11px] uppercase tracking-wide text-gray-400">{label}</dt>
      <dd className="mt-1 text-sm font-semibold text-gray-900">{value}</dd>
    </div>
  )
}
