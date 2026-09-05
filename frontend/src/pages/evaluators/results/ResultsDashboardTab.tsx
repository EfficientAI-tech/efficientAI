import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { motion } from 'framer-motion'
import {
  Activity,
  Clock,
  Loader,
  Target,
} from 'lucide-react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import ResultsMetricTrendCard, { type TrendSeries } from './ResultsMetricTrendCard'
import { apiClient } from '../../../lib/api'
import ResultsCountCards from './ResultsCountCards'
import { dateRangeToSinceUntil, rangeForDays } from './resultsDateRange'
import type {
  CallImportMetricAggregate,
  EvaluatorResultCounts,
  EvaluatorResultsOverviewResponse,
} from '../../../types/api'

const CHART_COLORS = ['#6366f1', '#8b5cf6', '#ec4899', '#f43f5e', '#f97316']
const TRENDS_PAGE_LIMIT = 500

interface ResultsDashboardTabProps {
  agentId: string
  suiteId: string
  scenarioId: string
  startDate: string | null
  endDate: string | null
  overview: EvaluatorResultsOverviewResponse | undefined
  loadingOverview: boolean
}

function resolveScopeCounts(
  overview: EvaluatorResultsOverviewResponse | undefined,
  agentId: string,
  suiteId: string,
  scenarioId: string,
): EvaluatorResultCounts {
  if (!overview) {
    return { total: 0, completed: 0, failed: 0, in_progress: 0 }
  }
  if (scenarioId && suiteId) {
    for (const agent of overview.agents) {
      if (agentId && agent.agent_id !== agentId) continue
      for (const suite of agent.suites ?? []) {
        if (suite.suite_id !== suiteId) continue
        const scenario = suite.scenarios?.find((s) => s.scenario_id === scenarioId)
        if (scenario) return scenario.counts
      }
    }
  }
  if (suiteId) {
    for (const agent of overview.agents) {
      if (agentId && agent.agent_id !== agentId) continue
      const suite = agent.suites?.find((s) => s.suite_id === suiteId)
      if (suite) return suite.counts
    }
  }
  if (agentId) {
    const agent = overview.agents.find((a) => a.agent_id === agentId)
    if (agent) return agent.counts
  }
  return overview.workspace_counts
}

function metricNumericValue(value: unknown, type: string): number | null {
  const t = type.toLowerCase()
  if (t === 'number' || t === 'rating') {
    if (typeof value === 'number' && !Number.isNaN(value)) return value
    if (typeof value === 'string' && value.trim() !== '') {
      const n = Number(value)
      return Number.isNaN(n) ? null : n
    }
  }
  if (t === 'boolean') {
    if (value === true || value === 'true' || value === 1 || value === '1') return 1
    if (value === false || value === 'false' || value === 0 || value === '0') return 0
  }
  return null
}

function formatDayKey(iso: string): { label: string; sortKey: string } {
  const d = new Date(iso)
  return {
    label: d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' }),
    sortKey: d.toISOString().slice(0, 10),
  }
}

type ScoreEntry = {
  value?: unknown
  type?: string
  metric_name?: string
  selection_mode?: string
  chosen_child_name?: string
  selected_child_names?: string[]
  skipped?: boolean
  error?: string
}

function extractCategorizationLabels(
  scores: Record<string, ScoreEntry> | null | undefined,
  metricId: string,
  childIdsByParent: Map<string, string[]>,
  childNamesById: Map<string, string>,
): string[] {
  if (!scores) return []
  const entry = scores[metricId]
  if (entry && !entry.skipped && !entry.error) {
    if (
      entry.selection_mode === 'multi_label' &&
      Array.isArray(entry.selected_child_names)
    ) {
      return entry.selected_child_names
        .map((label) => String(label).trim())
        .filter(Boolean)
    }
    const chosen = entry.chosen_child_name ?? entry.value
    if (chosen != null && String(chosen).trim()) {
      return [String(chosen).trim()]
    }
  }
  const childIds = childIdsByParent.get(metricId) ?? []
  const labels: string[] = []
  for (const childId of childIds) {
    const child = scores[childId]
    if (!child || child.skipped || child.error) continue
    if (
      child.value === true ||
      child.value === 'true' ||
      child.value === 1 ||
      child.value === '1'
    ) {
      labels.push(childNamesById.get(childId) ?? child.metric_name ?? childId)
    }
  }
  return labels
}

function isCategoricalMetric(metric: CallImportMetricAggregate): boolean {
  return metric.value_counts.length > 0 && metric.mean == null
}

function shortMetricLabel(name: string): string {
  return name.length > 28 ? `${name.slice(0, 26)}…` : name
}

export default function ResultsDashboardTab({
  agentId,
  suiteId,
  scenarioId,
  startDate,
  endDate,
  overview,
  loadingOverview,
}: ResultsDashboardTabProps) {
  const [hiddenMetricIds, setHiddenMetricIds] = useState<Set<string>>(() => new Set())

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
      limit: TRENDS_PAGE_LIMIT,
    }),
    [agentId, suiteId, scenarioId, dateBounds],
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
      }),
  })

  const { data: listResponse, isLoading: loadingResults } = useQuery({
    queryKey: ['evaluator-results-dashboard', listParams],
    queryFn: () => apiClient.listEvaluatorResults(listParams),
  })

  const { data: metricsCatalog = [] } = useQuery({
    queryKey: ['metrics', 'agent', 'dashboard'],
    queryFn: () => apiClient.listMetrics('agent'),
  })

  const { childIdsByParent, childNamesById } = useMemo(() => {
    const childIdsByParent = new Map<string, string[]>()
    const childNamesById = new Map<string, string>()
    for (const metric of metricsCatalog) {
      if (metric.parent_metric_id && metric.id) {
        childNamesById.set(metric.id, metric.name)
        const siblings = childIdsByParent.get(metric.parent_metric_id) ?? []
        siblings.push(metric.id)
        childIdsByParent.set(metric.parent_metric_id, siblings)
      }
    }
    return { childIdsByParent, childNamesById }
  }, [metricsCatalog])

  const scopeCounts = useMemo(
    () => resolveScopeCounts(overview, agentId, suiteId, scenarioId),
    [overview, agentId, suiteId, scenarioId],
  )

  const results = listResponse?.items ?? []
  const totalInRange = listResponse?.total ?? 0
  const truncated = totalInRange > TRENDS_PAGE_LIMIT

  const successRate =
    scopeCounts.total > 0
      ? (scopeCounts.completed / scopeCounts.total) * 100
      : 0

  const avgDuration = useMemo(() => {
    const durations = results
      .map((r) => r.duration_seconds)
      .filter((d): d is number => typeof d === 'number' && d > 0)
    if (!durations.length) return 0
    return durations.reduce((a, b) => a + b, 0) / durations.length
  }, [results])

  const visibleMetrics = useMemo(() => {
    const metrics = aggregate?.metrics ?? []
    return metrics.filter((m) => !hiddenMetricIds.has(m.metric_id))
  }, [aggregate?.metrics, hiddenMetricIds])

  const numericMetricTrends = useMemo(() => {
    const completed = results.filter(
      (r) => r.status === 'completed' && r.metric_scores,
    )
    const numericMetrics = visibleMetrics.filter(
      (m) =>
        !isCategoricalMetric(m) &&
        (m.mean != null || m.metric_type === 'number' || m.metric_type === 'rating'),
    )

    return numericMetrics.map((metric, chartIndex) => {
      const dayMap = new Map<
        string,
        { label: string; sortKey: string; values: number[] }
      >()

      for (const row of completed) {
        const score = row.metric_scores?.[metric.metric_id]
        if (!score) continue
        const scoreMeta = score as ScoreEntry
        if (scoreMeta.skipped || scoreMeta.error) continue
        const num = metricNumericValue(score.value, score.type || metric.metric_type || '')
        if (num == null) continue
        const { label, sortKey } = formatDayKey(row.timestamp)
        if (!dayMap.has(sortKey)) {
          dayMap.set(sortKey, { label, sortKey, values: [] })
        }
        dayMap.get(sortKey)!.values.push(num)
      }

      const data = Array.from(dayMap.values())
        .sort((a, b) => a.sortKey.localeCompare(b.sortKey))
        .map(({ label, values }) => ({
          day: label,
          value: values.reduce((a, b) => a + b, 0) / values.length,
        }))

      const color = CHART_COLORS[chartIndex % CHART_COLORS.length]
      const series: TrendSeries[] = [
        {
          key: 'value',
          label: metric.metric_type === 'rating' ? 'Avg score' : 'Avg value',
          color,
          total: metric.count,
        },
      ]

      return { metric, data, series }
    }).filter((chart) => chart.data.length > 0)
  }, [results, visibleMetrics])

  const categoricalTrendCharts = useMemo(() => {
    const completed = results.filter(
      (r) => r.status === 'completed' && r.metric_scores,
    )
    const categoricalMetrics = visibleMetrics.filter(isCategoricalMetric)

    return categoricalMetrics.map((metric, chartIndex) => {
      const labelSet = new Set(metric.value_counts.map((vc) => vc.label))
      const dayMap = new Map<
        string,
        { label: string; sortKey: string; counts: Record<string, number> }
      >()

      for (const row of completed) {
        const labels = extractCategorizationLabels(
          row.metric_scores as Record<string, ScoreEntry>,
          metric.metric_id,
          childIdsByParent,
          childNamesById,
        )
        if (!labels.length) continue
        const { label, sortKey } = formatDayKey(row.timestamp)
        if (!dayMap.has(sortKey)) {
          dayMap.set(sortKey, { label, sortKey, counts: {} })
        }
        const bucket = dayMap.get(sortKey)!
        for (const lbl of labels) {
          labelSet.add(lbl)
          bucket.counts[lbl] = (bucket.counts[lbl] ?? 0) + 1
        }
      }

      const labels = Array.from(labelSet)
      const data = Array.from(dayMap.values())
        .sort((a, b) => a.sortKey.localeCompare(b.sortKey))
        .map(({ label, counts }) => {
          const point: Record<string, string | number> = { day: label }
          for (const lbl of labels) {
            point[lbl] = counts[lbl] ?? 0
          }
          return point
        })

      const series: TrendSeries[] = labels.map((label, i) => ({
        key: label,
        label,
        color: CHART_COLORS[(chartIndex + i) % CHART_COLORS.length],
        total: data.reduce((sum, row) => sum + (Number(row[label]) || 0), 0),
      }))

      return { metric, labels, data, series }
    }).filter((chart) => chart.data.length > 0 && chart.labels.length > 0)
  }, [results, visibleMetrics, childIdsByParent, childNamesById])

  const toggleMetricVisibility = (metricId: string) => {
    setHiddenMetricIds((prev) => {
      const next = new Set(prev)
      if (next.has(metricId)) next.delete(metricId)
      else next.add(metricId)
      return next
    })
  }

  const loading = loadingOverview || loadingAggregate || loadingResults

  if (loading && !aggregate && !results.length) {
    return (
      <div className="flex items-center justify-center py-16 text-gray-500">
        <Loader className="h-5 w-5 animate-spin mr-2" />
        Loading dashboard…
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {!startDate || !endDate ? (
        <p className="text-xs text-gray-500">
          Showing last 7 days ({effectiveDateRange.start} → {effectiveDateRange.end}). Set a date range above to change the window.
        </p>
      ) : null}

      {truncated ? (
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900">
          Trends use the newest {TRENDS_PAGE_LIMIT} runs in this window ({totalInRange.toLocaleString()} total match the filter).
        </div>
      ) : null}

      <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
        <div className="col-span-2 md:col-span-4">
          <ResultsCountCards counts={scopeCounts} />
        </div>
        <motion.div
          className="bg-white rounded-xl border border-gray-100 shadow-sm p-4 flex flex-col justify-center"
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
        >
          <p className="text-xs font-medium text-gray-500 uppercase tracking-wider">Success rate</p>
          <p className="text-2xl font-bold text-emerald-600 mt-1 tabular-nums">
            {successRate.toFixed(0)}%
          </p>
          <Target className="w-5 h-5 text-emerald-500 mt-2" />
        </motion.div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-4">
          <p className="text-xs font-medium text-gray-500 uppercase tracking-wider">Avg duration</p>
          <p className="text-xl font-bold text-gray-900 mt-1 tabular-nums">
            {Math.round(avgDuration)}s
          </p>
          <Clock className="w-4 h-4 text-amber-500 mt-2" />
        </div>
        <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-4 md:col-span-2">
          <p className="text-xs font-medium text-gray-500 uppercase tracking-wider mb-2">Runs in window</p>
          <p className="text-xl font-bold text-gray-900 tabular-nums">
            {results.length.toLocaleString()}
            {truncated ? (
              <span className="text-sm font-normal text-gray-500 ml-2">
                of {totalInRange.toLocaleString()} total
              </span>
            ) : null}
          </p>
        </div>
      </div>

      {aggregate?.metrics.length ? (
        <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-6 space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-sm font-semibold text-gray-900">Metric visibility</h2>
            <p className="text-xs text-gray-500">Toggle metrics to filter every chart below</p>
          </div>
          <div className="flex flex-wrap gap-2">
            {aggregate.metrics.map((m) => {
              const hidden = hiddenMetricIds.has(m.metric_id)
              return (
                <button
                  key={m.metric_id}
                  type="button"
                  onClick={() => toggleMetricVisibility(m.metric_id)}
                  className={`rounded-full border px-3 py-1 text-xs font-medium transition-colors ${
                    hidden
                      ? 'border-gray-200 bg-gray-50 text-gray-400 line-through'
                      : 'border-primary-200 bg-primary-50 text-primary-800'
                  }`}
                >
                  {m.metric_name}
                </button>
              )
            })}
          </div>
        </div>
      ) : null}

      {(numericMetricTrends.length > 0 || categoricalTrendCharts.length > 0) ? (
        <div className="space-y-3">
          <div>
            <h2 className="text-sm font-semibold text-gray-900">Metric trends</h2>
            <p className="text-xs text-gray-500 mt-0.5">
              Daily trends per metric — switch line or bar on each card
            </p>
          </div>
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {numericMetricTrends.map(({ metric, data, series }) => (
              <ResultsMetricTrendCard
                key={metric.metric_id}
                title={metric.metric_name}
                subtitle={
                  metric.mean != null
                    ? `${metric.count} rows · window avg ${metric.mean.toFixed(2)}`
                    : `${metric.count} rows scored`
                }
                series={series}
                data={data}
                defaultChartType="line"
              />
            ))}
            {categoricalTrendCharts.map(({ metric, data, series }) => (
              <ResultsMetricTrendCard
                key={metric.metric_id}
                title={metric.metric_name}
                subtitle={`${metric.count} rows scored in window`}
                series={series}
                data={data}
                defaultChartType="line"
                yAxisAllowDecimals={false}
              />
            ))}
          </div>
        </div>
      ) : null}

      {visibleMetrics.some((m) => m.histogram_buckets.length > 0) ? (
        <div className="grid gap-4 md:grid-cols-2">
          {visibleMetrics
            .filter((m) => m.histogram_buckets.length > 0)
            .slice(0, 4)
            .map((m) => (
              <div
                key={`hist-${m.metric_id}`}
                className="bg-white rounded-xl border border-gray-100 shadow-sm p-4"
              >
                <h3 className="text-xs font-semibold text-gray-900 mb-3">
                  {shortMetricLabel(m.metric_name)}
                </h3>
                <ResponsiveContainer width="100%" height={160}>
                  <BarChart
                    data={m.histogram_buckets.map((b) => ({
                      label: `${b.x0.toFixed(1)}–${b.x1.toFixed(1)}`,
                      count: b.count,
                    }))}
                  >
                    <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                    <XAxis dataKey="label" tick={{ fontSize: 9 }} />
                    <YAxis tick={{ fontSize: 10 }} />
                    <Tooltip />
                    <Bar dataKey="count" fill="#6366f1" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            ))}
        </div>
      ) : null}

      {!loading && !results.length && !aggregate?.metrics.length ? (
        <div className="rounded-xl border border-gray-100 bg-white p-12 text-center">
          <Activity className="h-8 w-8 text-gray-300 mx-auto mb-3" />
          <p className="text-sm font-medium text-gray-900">No evaluation data in this window</p>
          <p className="text-sm text-gray-500 mt-1">Adjust filters or expand the date range.</p>
        </div>
      ) : null}
    </div>
  )
}
