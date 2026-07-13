import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Layers } from 'lucide-react'
import { apiClient } from '../../../lib/api'
import {
  getTopLevelMetrics,
  isCategorizationParent,
  getEnabledChildren,
  normalizeSelectedMetricIds,
  toggleMetricSelection,
  type MetricRow,
} from './metricSelectionUtils'

interface Props {
  selectedMetricIds: string[]
  onChange: (ids: string[]) => void
}

export default function EvaluatorMetricPicker({ selectedMetricIds, onChange }: Props) {
  const { data: metrics = [] } = useQuery({
    queryKey: ['metrics', 'agent'],
    queryFn: () => apiClient.listMetrics('agent', true),
  })

  const metricRows = metrics as MetricRow[]
  const enabledParents = getTopLevelMetrics(metricRows)
  const disabledCount = metricRows.filter((m) => m.enabled === false).length
  const normalizedSelected = normalizeSelectedMetricIds(selectedMetricIds, metricRows)

  const handleToggle = (metric: MetricRow) => {
    onChange(toggleMetricSelection(metric, selectedMetricIds, metricRows))
  }

  return (
    <div className="space-y-3">
      <p className="text-sm text-gray-600">
        Optional — leave empty to score against all enabled agent metrics. Categorization metrics select as one unit (all sub-labels included).
      </p>
      <div className="max-h-80 overflow-y-auto border border-gray-200 rounded-xl p-3 space-y-2 bg-gray-50/30">
        {enabledParents.length === 0 ? (
          <p className="text-sm text-gray-500 p-2">
            No metrics enabled. Configure in{' '}
            <Link to="/metrics-management" className="underline text-primary-700">Metrics</Link>.
          </p>
        ) : (
          enabledParents.map((metric) => {
            const isCategory = isCategorizationParent(metric)
            const children = isCategory ? getEnabledChildren(metric) : []
            const checked = normalizedSelected.includes(metric.id)

            return (
              <label
                key={metric.id}
                className={`flex items-start gap-3 cursor-pointer p-3 rounded-xl border transition-all ${
                  checked
                    ? isCategory
                      ? 'bg-purple-50 border-purple-200 shadow-sm'
                      : 'bg-primary-50 border-primary-200 shadow-sm'
                    : 'border-transparent bg-white hover:border-gray-200 hover:shadow-sm'
                }`}
              >
                <input
                  type="checkbox"
                  checked={checked}
                  onChange={() => handleToggle(metric)}
                  className="mt-1 rounded border-gray-300 text-primary-600 focus:ring-primary-500"
                />
                <div className="flex-1 min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    {isCategory && <Layers className="h-3.5 w-3.5 text-purple-600 shrink-0" />}
                    <span className="text-sm font-semibold text-gray-900">{metric.name}</span>
                    {isCategory && (
                      <span className="inline-flex items-center gap-1 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide rounded-full bg-purple-100 text-purple-800 border border-purple-200">
                        {metric.selection_mode === 'single_choice' ? 'Single-choice' : 'Multi-label'}
                        <span className="px-1 py-0.5 bg-purple-200/80 rounded text-[9px]">
                          {children.length}
                        </span>
                      </span>
                    )}
                  </div>
                  {metric.description && (
                    <p className="text-xs text-gray-500 mt-1 line-clamp-2">{metric.description}</p>
                  )}
                  {isCategory && children.length > 0 && (
                    <div className="mt-2 flex flex-wrap gap-1">
                      {children.map((child) => (
                        <span
                          key={child.id}
                          className="inline-flex px-1.5 py-0.5 text-[10px] rounded-md bg-purple-100/60 text-purple-700 border border-purple-200/50"
                          title="Sub-label included with parent metric"
                        >
                          {child.name}
                        </span>
                      ))}
                    </div>
                  )}
                  {isCategory && children.length === 0 && (
                    <p className="text-[11px] text-amber-700 mt-1">No sub-labels configured yet</p>
                  )}
                </div>
              </label>
            )
          })
        )}
      </div>
      {disabledCount > 0 && (
        <p className="text-xs text-gray-500">
          {disabledCount} disabled metric{disabledCount !== 1 ? 's' : ''} hidden.
        </p>
      )}
      {normalizedSelected.length > 0 && (
        <p className="text-xs text-gray-600">
          {normalizedSelected.length} metric{normalizedSelected.length !== 1 ? 's' : ''} selected
        </p>
      )}
    </div>
  )
}
