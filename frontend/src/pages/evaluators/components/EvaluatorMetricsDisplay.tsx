import { Layers, BarChart3 } from 'lucide-react'
import { buildDisplayMetrics, getMetricTypeBadge, type MetricRow } from './metricSelectionUtils'

interface Props {
  selectedMetricIds?: string[] | null
  metrics: MetricRow[]
}

export default function EvaluatorMetricsDisplay({ selectedMetricIds, metrics }: Props) {
  const displayMetrics = buildDisplayMetrics(selectedMetricIds, metrics)

  if (!displayMetrics) {
    return (
      <div className="rounded-xl border border-dashed border-gray-200 bg-gray-50/50 p-5 text-center">
        <BarChart3 className="w-8 h-8 text-gray-400 mx-auto mb-2" />
        <p className="text-sm font-medium text-gray-900">All enabled agent metrics</p>
        <p className="text-xs text-gray-500 mt-1">Every metric enabled for the agent surface will be scored</p>
      </div>
    )
  }

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
      {displayMetrics.map((metric) => {
        const typeBadge = getMetricTypeBadge(metric)
        return (
          <div
            key={metric.id}
            className={`rounded-xl border p-4 transition-shadow hover:shadow-sm ${
              metric.isCategory
                ? 'border-purple-100 bg-purple-50/30'
                : 'border-gray-100 bg-white'
            }`}
          >
            <div className="flex items-start justify-between gap-2 mb-2">
              <div className="flex items-center gap-2 min-w-0">
                {metric.isCategory && (
                  <Layers className="h-4 w-4 text-purple-600 shrink-0" />
                )}
                <h4 className="text-sm font-semibold text-gray-900 truncate">{metric.name}</h4>
              </div>
              <span
                className={`shrink-0 inline-flex px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide rounded-full border ${typeBadge.className}`}
              >
                {typeBadge.label}
              </span>
            </div>
            {metric.description && (
              <p className="text-xs text-gray-600 line-clamp-2 mb-2">{metric.description}</p>
            )}
            {metric.isCategory && (
              <div className="mt-2 pt-2 border-t border-purple-100/80">
                <p className="text-[11px] font-medium text-purple-800 mb-1.5">
                  {metric.subLabelCount} sub-label{metric.subLabelCount !== 1 ? 's' : ''} included
                </p>
                {metric.subLabels && metric.subLabels.length > 0 && (
                  <div className="flex flex-wrap gap-1">
                    {metric.subLabels.map((label) => (
                      <span
                        key={label}
                        className="inline-flex px-1.5 py-0.5 text-[10px] rounded-md bg-purple-100/80 text-purple-700 border border-purple-200/60"
                      >
                        {label}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
