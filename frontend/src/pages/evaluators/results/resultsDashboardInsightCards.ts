import type { CallImportMetricAggregate } from '../../../types/api'
import { formatDashboardHeadline } from './resultsDashboardFormat'
import type { InsightPanelContext } from './resultsDashboardInsightContext'
import type { ResultsWidget } from './resultsDashboardLayout'
import {
  agentCostCard,
  categoryColors,
  formatDuration,
  isCategoricalMetric,
  mergedToolsCard,
  metricUsageAgentsCard,
  modelCostCard,
  scenarioStack,
  totalCallsByAgentCard,
  usageCard,
  type ChartModel,
} from './resultsDashboardSeries'

const PRIMARY = '#ca8a04'
const FAIL = '#dc2626'
const SERIES_MUTED = '#9ca3af'

export function buildInsightCardModel(widget: ResultsWidget, source: InsightPanelContext): ChartModel {
  const terminalDays = source.days
  if (widget.type === 'usage') {
    return usageCard(source.ops, {
      currency: source.usageCurrency,
      inrRate: source.usageInrRate,
    })
  }
  if (widget.type === 'tools' || widget.type === 'tool_calls') return mergedToolsCard(source.ops)
  if (widget.type === 'total_calls') {
    return totalCallsByAgentCard(
      source.agentRows.map((row) => ({ name: row.name, total: row.total })),
      source.aggregateTotal,
    )
  }
  if (widget.type === 'metric_usage') {
    return metricUsageAgentsCard(source.agentRows.map((row) => ({ name: row.name, total: row.total })))
  }
  if (widget.type === 'agent_cost') return agentCostCard(source.ops, widget.display)
  if (widget.type === 'model_cost') return modelCostCard(source.ops)
  if (widget.type === 'avg_duration') {
    return {
      headline: formatDuration(source.duration.average),
      caption: 'Avg duration / call',
      data: source.duration.points,
      series: [{ key: 'value', color: PRIMARY }],
    }
  }
  if (widget.type === 'scenarios_by_agent') return scenarioStack(source.scenarioMatrix)
  if (widget.type === 'volume') {
    return {
      headline: formatDashboardHeadline(source.aggregateTotal),
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
      headline: formatDashboardHeadline(rate, '%'),
      caption: 'Completed runs',
      data: terminalDays.map((day) => {
        const denom = day.completed + day.failed
        return { day: day.day, rate: denom ? Math.round((day.completed / denom) * 100) : 0 }
      }),
      series: [{ key: 'rate', color: PRIMARY }],
    }
  }
  if (widget.type === 'avg_score' || widget.type === 'metric_trend') {
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
      return categoricalMetricCard(metric, source.categorySeries.get(metric.metric_id))
    }
    const points = metric ? source.scoreSeries.get(metric.metric_id) ?? [] : []
    return {
      headline: formatDashboardHeadline(metric?.mean ?? null),
      caption: metric?.metric_name ?? 'No scored metric',
      data: points,
      series: [{ key: 'value', color: PRIMARY }],
    }
  }
  if (widget.type === 'lowest_metrics') {
    return {
      headline: formatDashboardHeadline(source.lowest[0]?.value ?? null),
      caption: 'Lowest mean first',
      data: source.lowest,
      series: [{ key: 'value', color: SERIES_MUTED }],
      horizontal: widget.display === 'bar',
    }
  }
  if (widget.type === 'agents') {
    return {
      headline: formatDashboardHeadline(source.agentRows.length),
      caption: 'Agents in this window',
      data: source.agentRows.map((row) => ({ name: row.name, total: row.total })),
      series: [{ key: 'total', color: PRIMARY }],
      horizontal: widget.display === 'bar',
    }
  }
  return {
    headline: formatDashboardHeadline(source.scenarioRows.reduce((sum, row) => sum + row.count, 0)),
    caption: 'Scenario runs',
    data: source.scenarioRows.map((row) => ({ name: row.name, count: row.count })),
    series: [{ key: 'count', color: PRIMARY }],
    horizontal: widget.display === 'bar',
  }
}

function categoricalMetricCard(
  metric: CallImportMetricAggregate,
  category: { labels: string[]; data: Array<Record<string, string | number>> } | undefined,
): ChartModel {
  if (category?.data.length) {
    return {
      headline: formatDashboardHeadline(metric.count),
      caption: metric.metric_name,
      data: category.data,
      series: categoryColors(category.labels),
    }
  }
  return {
    headline: formatDashboardHeadline(metric.count),
    caption: metric.metric_name,
    data: metric.value_counts.map((count) => ({ name: count.label, count: count.count })),
    series: [{ key: 'count', color: PRIMARY }],
    horizontal: true,
  }
}