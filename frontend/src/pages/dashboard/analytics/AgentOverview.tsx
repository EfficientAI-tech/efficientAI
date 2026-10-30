import { useMemo, useState } from 'react'
import MetricCard from './MetricCard'
import { defaultNorthStarIds, getPinnedMetricIds, togglePinnedMetric } from './northStarMetrics'
import { isInsightMetric, isQualityMetric } from './metricMath'
import type { AgentMetricSeries, ScoredMetric } from './types'

export default function AgentOverview({
  agentName,
  series,
  onOpenMetric,
}: {
  agentName: string
  series: AgentMetricSeries
  onOpenMetric: (metricId: string) => void
}) {
  const defaults = useMemo(() => defaultNorthStarIds(series.metrics), [series.metrics])
  const [pinned, setPinned] = useState(() => getPinnedMetricIds(series.agentId))
  const northStarIds = pinned.length > 0 ? pinned : defaults

  const quality = sortWorstFirst(series.metrics.filter((metric) => isQualityMetric(metric.agg)))
  const insights = series.metrics.filter((metric) => isInsightMetric(metric.agg))
  const northStar = quality.filter((metric) => northStarIds.includes(metric.agg.metric_id))
  const rest = quality.filter((metric) => !northStarIds.includes(metric.agg.metric_id))
  const biggestMover = quality
    .filter((metric) => metric.reliable && metric.sentiment !== 'flat' && metric.delta)
    .sort((a, b) => (b.delta?.points ?? 0) - (a.delta?.points ?? 0))[0]

  const handlePin = (metricId: string) => {
    setPinned(togglePinnedMetric(series.agentId, metricId, defaults))
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-gray-900">{agentName}</h1>
        <p className="mt-1 text-sm text-gray-600">
          {series.completedRows} completed simulation runs in this window
          {biggestMover ? ` · Biggest mover: ${biggestMover.headline}` : ''}.
        </p>
      </div>

      {northStar.length > 0 && (
        <section className="space-y-3">
          <h2 className="text-sm font-semibold text-gray-900">North-star metrics</h2>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            {northStar.map((metric) => (
              <MetricCard
                key={metric.agg.metric_id}
                metric={metric}
                size="large"
                pinned
                points={valuesFor(series, metric)}
                onPin={() => handlePin(metric.agg.metric_id)}
                onClick={() => onOpenMetric(metric.agg.metric_id)}
              />
            ))}
          </div>
        </section>
      )}

      <section className="space-y-3">
        <h2 className="text-sm font-semibold text-gray-900">Quality</h2>
        {rest.length === 0 && northStar.length === 0 ? (
          <p className="text-sm text-gray-500">No quality metrics scored in this window.</p>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {rest.map((metric) => (
              <MetricCard
                key={metric.agg.metric_id}
                metric={metric}
                points={valuesFor(series, metric)}
                pinned={northStarIds.includes(metric.agg.metric_id)}
                onPin={() => handlePin(metric.agg.metric_id)}
                onClick={() => onOpenMetric(metric.agg.metric_id)}
              />
            ))}
          </div>
        )}
      </section>

      {insights.length > 0 && (
        <section className="space-y-3">
          <h2 className="text-sm font-semibold text-gray-900">Insights</h2>
          <p className="text-xs text-gray-500">These labels describe the call. They are not optimized by GEPA.</p>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {insights.map((metric) => (
              <MetricCard
                key={metric.agg.metric_id}
                metric={metric}
                points={valuesFor(series, metric)}
                onClick={() => onOpenMetric(metric.agg.metric_id)}
              />
            ))}
          </div>
        </section>
      )}
    </div>
  )
}

function valuesFor(series: AgentMetricSeries, metric: ScoredMetric): Array<number | null> {
  return (series.pointsByMetric[metric.agg.metric_id] ?? []).map((point) => point.value)
}

function sortWorstFirst(metrics: ScoredMetric[]): ScoredMetric[] {
  const rank = { worsening: 0, flat: 1, improving: 2 }
  return [...metrics].sort((a, b) => {
    if (rank[a.sentiment] !== rank[b.sentiment]) return rank[a.sentiment] - rank[b.sentiment]
    return (b.score.failureRate ?? 0) - (a.score.failureRate ?? 0)
  })
}
