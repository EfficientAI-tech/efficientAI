import { Trash2 } from 'lucide-react'
import type {
  EvaluatorResultClusterScopeSummary,
  MetricClusterGenerationScope,
} from '../../types/api'
import type { EvaluatorResultClusterScope } from './clients'
import {
  clusterScopeStatusLabel,
  formatClusterScopeHistoryLabel,
  generationScopeToClusterScope,
  clusterScopesMatch,
} from './clusterScopeUtils'

export interface ClusterScopeHistoryProps {
  items: EvaluatorResultClusterScopeSummary[]
  activeScope: EvaluatorResultClusterScope | null
  onSelectScope: (scope: EvaluatorResultClusterScope) => void
  onDeleteScope?: (scope: EvaluatorResultClusterScope) => void | Promise<void>
  onCreateNew?: () => void
  isLoading?: boolean
}

function scopeItemKey(item: EvaluatorResultClusterScopeSummary): string {
  return item.scope_key
}

export default function ClusterScopeHistory({
  items,
  activeScope,
  onSelectScope,
  onDeleteScope,
  onCreateNew,
  isLoading,
}: ClusterScopeHistoryProps) {
  if (isLoading) {
    return (
      <section className="rounded-lg border border-gray-200 bg-white px-4 py-3">
        <p className="text-sm text-gray-500">Loading cluster reports…</p>
      </section>
    )
  }

  if (!items.length) {
    return (
      <section className="rounded-lg border border-dashed border-gray-200 bg-gray-50/70 px-4 py-3">
        <p className="text-sm font-semibold text-gray-900">Cluster reports</p>
        <p className="text-sm text-gray-600 mt-1">
          Generate a cluster report for an agent and scope. Each unique agent,
          scenario set, and date range is saved here for later review.
        </p>
        {onCreateNew ? (
          <button
            type="button"
            onClick={onCreateNew}
            className="mt-3 text-sm font-medium text-primary-700 hover:text-primary-900"
          >
            Generate your first report
          </button>
        ) : null}
      </section>
    )
  }

  return (
    <section className="rounded-lg border border-gray-200 bg-white px-4 py-3 space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h3 className="text-sm font-semibold text-gray-900">Cluster reports</h3>
          <p className="text-xs text-gray-500 mt-0.5">
            Switch between saved scopes to drill into charts and clusters for each
            report.
          </p>
        </div>
        {onCreateNew ? (
          <button
            type="button"
            onClick={onCreateNew}
            className="text-xs font-medium text-primary-700 hover:text-primary-900 shrink-0"
          >
            New report
          </button>
        ) : null}
      </div>
      <div className="flex gap-2 overflow-x-auto pb-1">
        {items.map((item) => {
          const itemScope = generationScopeToClusterScope(
            item.generation_scope,
            item.job_id,
          )
          const selected = clusterScopesMatch(activeScope, itemScope)
          return (
            <ScopeHistoryCard
              key={scopeItemKey(item)}
              item={item}
              generationScope={item.generation_scope}
              selected={selected}
              onSelect={() => onSelectScope(itemScope)}
              onDelete={
                onDeleteScope
                  ? () => onDeleteScope(itemScope)
                  : undefined
              }
            />
          )
        })}
      </div>
    </section>
  )
}

function ScopeHistoryCard({
  item,
  generationScope,
  selected,
  onSelect,
  onDelete,
}: {
  item: EvaluatorResultClusterScopeSummary
  generationScope: MetricClusterGenerationScope
  selected: boolean
  onSelect: () => void
  onDelete?: () => void | Promise<void>
}) {
  const label = formatClusterScopeHistoryLabel(generationScope)
  const statusLabel = clusterScopeStatusLabel(item.status)
  const generatedLabel = item.generated_at
    ? new Date(item.generated_at).toLocaleString(undefined, {
        dateStyle: 'medium',
        timeStyle: 'short',
      })
    : null

  const handleDelete = async (event: React.MouseEvent) => {
    event.stopPropagation()
    if (!onDelete) return
    const labelShort = generationScope.agent_name ?? 'this report'
    if (
      !window.confirm(
        `Delete the cluster report for ${labelShort}? This cannot be undone.`,
      )
    ) {
      return
    }
    await onDelete()
  }

  return (
    <div
      className={`relative min-w-[220px] max-w-[280px] shrink-0 rounded-lg border transition-colors ${
        selected
          ? 'border-primary-500 bg-primary-50/80 ring-1 ring-primary-200'
          : 'border-gray-200 bg-gray-50/50 hover:border-gray-300 hover:bg-white'
      }`}
    >
      <button
        type="button"
        onClick={onSelect}
        className="w-full px-3 py-2.5 text-left"
      >
        <p className="text-xs font-semibold text-gray-900 leading-snug pr-6">
          {label}
        </p>
        <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
          <span
            className={`inline-flex rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${
              item.status === 'completed'
                ? 'bg-emerald-50 text-emerald-800'
                : item.status === 'running'
                  ? 'bg-amber-50 text-amber-800'
                  : item.status === 'failed'
                    ? 'bg-rose-50 text-rose-800'
                    : 'bg-gray-100 text-gray-700'
            }`}
          >
            {statusLabel}
          </span>
          {item.is_stale ? (
            <span className="inline-flex rounded-full bg-amber-50 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-amber-800">
              Stale
            </span>
          ) : null}
          {generationScope.selected_call_count ? (
            <span className="text-[10px] text-gray-500 tabular-nums">
              {generationScope.selected_call_count} calls
            </span>
          ) : null}
        </div>
        {generatedLabel ? (
          <p className="mt-1 text-[10px] text-gray-500">
            Generated {generatedLabel}
          </p>
        ) : null}
      </button>
      {onDelete ? (
        <button
          type="button"
          onClick={handleDelete}
          className="absolute top-2 right-2 rounded p-1 text-gray-400 hover:text-rose-600 hover:bg-rose-50"
          aria-label="Delete cluster report"
          title="Delete report"
        >
          <Trash2 className="h-3.5 w-3.5" />
        </button>
      ) : null}
    </div>
  )
}
