import { Pin } from 'lucide-react'
import DeltaChip from './DeltaChip'
import SampleSizeBadge from './SampleSizeBadge'
import Sparkline from './Sparkline'
import { isInsightMetric } from './metricMath'
import type { ScoredMetric } from './types'

export default function MetricCard({
  metric,
  points,
  pinned,
  onPin,
  onClick,
  size = 'default',
}: {
  metric: ScoredMetric
  points?: Array<number | null>
  pinned?: boolean
  onPin?: () => void
  onClick?: () => void
  size?: 'default' | 'large'
}) {
  const insight = isInsightMetric(metric.agg)
  return (
    <button
      type="button"
      onClick={onClick}
      className={`w-full text-left rounded-xl border bg-white shadow-sm hover:border-gray-300 hover:shadow transition-all ${
        size === 'large' ? 'p-5' : 'p-4'
      } ${
        metric.sentiment === 'worsening'
          ? 'border-rose-200'
          : metric.sentiment === 'improving'
            ? 'border-emerald-200'
            : 'border-gray-200'
      }`}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <h3 className="text-sm font-semibold text-gray-900 truncate">
              {metric.agg.metric_name}
            </h3>
            {insight && (
              <span className="text-[10px] uppercase tracking-wide text-violet-600 bg-violet-50 px-1.5 py-0.5 rounded-full">
                Insight
              </span>
            )}
            <SampleSizeBadge count={metric.score.count} />
          </div>
          <p className="mt-1 text-sm text-gray-600 leading-snug">{metric.headline}</p>
        </div>
        <div className="flex items-center gap-2 flex-shrink-0">
          <DeltaChip sentiment={metric.sentiment} delta={metric.delta} />
          {onPin && (
            <span
              role="button"
              tabIndex={0}
              title={pinned ? 'Unpin from north-star' : 'Pin as north-star'}
              onClick={(event) => {
                event.stopPropagation()
                onPin()
              }}
              onKeyDown={(event) => {
                if (event.key === 'Enter' || event.key === ' ') {
                  event.preventDefault()
                  event.stopPropagation()
                  onPin()
                }
              }}
              className={`p-1 rounded-md ${
                pinned ? 'text-amber-600 bg-amber-50' : 'text-gray-300 hover:text-gray-500'
              }`}
            >
              <Pin className="h-3.5 w-3.5" />
            </span>
          )}
        </div>
      </div>
      <div className="mt-3 flex items-end justify-between gap-3">
        <div>
          <div className={`${size === 'large' ? 'text-3xl' : 'text-2xl'} font-semibold text-gray-900 tabular-nums`}>
            {metric.score.display}
          </div>
          {metric.score.topLabel && (
            <div className="text-xs text-gray-500 mt-0.5">Most common label</div>
          )}
        </div>
        {points && points.some((value) => value != null) && (
          <Sparkline values={points} width={size === 'large' ? 120 : 88} />
        )}
      </div>
      {metric.agg.value_counts.length > 0 && metric.score.kind !== 'mean' && (
        <div className="mt-3 flex h-2 overflow-hidden rounded-full bg-gray-100">
          {metric.agg.value_counts.slice(0, 5).map((item) => {
            const total = metric.agg.value_counts.reduce((sum, row) => sum + row.count, 0) || 1
            return (
              <div
                key={item.label}
                title={`${item.label}: ${item.count}`}
                className="h-full"
                style={{
                  width: `${(item.count / total) * 100}%`,
                  backgroundColor: stackColor(item.label),
                }}
              />
            )
          })}
        </div>
      )}
    </button>
  )
}

function stackColor(label: string): string {
  const key = label.toLowerCase()
  if (['false', 'no', 'fail', 'failed'].some((item) => key.includes(item))) return '#f43f5e'
  if (['true', 'yes', 'pass', 'resolved'].some((item) => key.includes(item))) return '#10b981'
  const palette = ['#6366f1', '#8b5cf6', '#f97316', '#14b8a6', '#eab308']
  return palette[Math.abs(hash(label)) % palette.length]
}

function hash(value: string): number {
  return [...value].reduce((sum, char) => sum + char.charCodeAt(0), 0)
}
