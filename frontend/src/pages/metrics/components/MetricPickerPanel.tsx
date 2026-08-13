import { ChevronDown, ChevronRight } from 'lucide-react'
import { useMemo, useState } from 'react'

export interface MetricPickerItem {
  id: string
  name: string
  enabled?: boolean
  lifecycle?: string
  selection_mode?: string | null
  children?: MetricPickerItem[]
}

interface MetricPickerPanelProps {
  metrics: MetricPickerItem[]
  selectedMetricIds: string[]
  onChange: (ids: string[]) => void
  emptyMessage?: string
}

export default function MetricPickerPanel({
  metrics,
  selectedMetricIds,
  onChange,
  emptyMessage = 'No metrics available.',
}: MetricPickerPanelProps) {
  const [expandedParents, setExpandedParents] = useState<Set<string>>(new Set())
  const selectedSet = useMemo(() => new Set(selectedMetricIds), [selectedMetricIds])

  const toggleMetric = (id: string) => {
    const next = new Set(selectedSet)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    onChange(Array.from(next))
  }

  const enabledChildIds = (parent: MetricPickerItem): string[] =>
    (parent.children ?? [])
      .filter((c) => c.enabled !== false || c.lifecycle === 'draft')
      .map((c) => c.id)

  const toggleParentMetric = (parent: MetricPickerItem) => {
    const childIds = enabledChildIds(parent)
    const next = new Set(selectedSet)
    const parentSelected = next.has(parent.id)
    const someChildren = childIds.some((cid) => next.has(cid))
    if (parentSelected || someChildren) {
      next.delete(parent.id)
      for (const cid of childIds) next.delete(cid)
    } else {
      next.add(parent.id)
      for (const cid of childIds) next.add(cid)
    }
    onChange(Array.from(next))
  }

  const toggleParentExpanded = (id: string) => {
    setExpandedParents((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  if (metrics.length === 0) {
    return <p className="text-sm text-gray-500">{emptyMessage}</p>
  }

  return (
    <div className="space-y-1 max-h-80 overflow-y-auto border border-gray-200 rounded-lg p-2">
      {metrics.map((metric) => {
        const children = (metric.children ?? []).filter(
          (c) => c.enabled !== false || c.lifecycle === 'draft',
        )
        const isParent = Boolean(metric.selection_mode && children.length > 0)
        const isExpanded = expandedParents.has(metric.id)
        const childIds = enabledChildIds(metric)
        const selectedChildCount = childIds.filter((cid) => selectedSet.has(cid)).length
        const parentChecked =
          selectedSet.has(metric.id) ||
          (childIds.length > 0 && childIds.every((cid) => selectedSet.has(cid)))
        const parentIndeterminate =
          !parentChecked && childIds.some((cid) => selectedSet.has(cid))

        if (isParent) {
          return (
            <div key={metric.id} className="rounded-md bg-gray-50/80">
              <div className="flex items-center gap-2 px-2 py-1.5">
                <button
                  type="button"
                  onClick={() => toggleParentExpanded(metric.id)}
                  className="text-gray-500 hover:text-gray-800"
                >
                  {isExpanded ? (
                    <ChevronDown className="h-4 w-4" />
                  ) : (
                    <ChevronRight className="h-4 w-4" />
                  )}
                </button>
                <label className="flex flex-1 items-start gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={parentChecked}
                    ref={(el) => {
                      if (el) el.indeterminate = parentIndeterminate
                    }}
                    onChange={() => toggleParentMetric(metric)}
                    className="mt-0.5"
                  />
                  <span className="flex-1">
                    <span className="text-sm font-medium text-gray-900">{metric.name}</span>
                    <span className="ml-2 inline-flex items-center rounded-full bg-primary-100 px-2 py-0.5 text-[10px] font-medium text-primary-700">
                      {metric.selection_mode === 'single_choice' ? 'pick one' : 'multi-label'}
                    </span>
                    <span className="ml-2 text-[11px] text-gray-500">
                      {selectedChildCount}/{childIds.length} labels
                    </span>
                    {metric.lifecycle === 'draft' && (
                      <span className="ml-2 text-[10px] uppercase tracking-wide px-1.5 py-0.5 rounded bg-amber-100 text-amber-800">
                        Draft
                      </span>
                    )}
                  </span>
                </label>
              </div>
              {isExpanded && (
                <div className="pl-8 pb-2 space-y-1 border-l border-gray-200 ml-4">
                  {children.map((child) => (
                    <div key={child.id} className="text-sm text-gray-600 px-2 py-0.5">
                      {child.name}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )
        }

        return (
          <label
            key={metric.id}
            className="flex items-center gap-2 px-2 py-1.5 text-sm text-gray-700 cursor-pointer hover:bg-gray-50 rounded"
          >
            <input
              type="checkbox"
              checked={selectedSet.has(metric.id)}
              onChange={() => toggleMetric(metric.id)}
            />
            <span>{metric.name}</span>
            {metric.lifecycle === 'draft' && (
              <span className="text-[10px] uppercase tracking-wide px-1.5 py-0.5 rounded bg-amber-100 text-amber-800">
                Draft
              </span>
            )}
          </label>
        )
      })}
    </div>
  )
}
