import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ChevronDown,
  ChevronRight,
  Merge,
  Plus,
  Sparkles,
  Trash2,
} from 'lucide-react'
import { apiClient } from '../../../../lib/api'
import { itemsOf } from '../../../../lib/safeData'
import type { DiscoveredMetric } from '../../../../types/api'
import { getActiveWorkspaceId } from '../../../../store/workspaceStore'

function DiscoveredMetricsTopPanel({
  callImportId,
  evalId,
}: {
  callImportId: string
  evalId: string
}) {
  const queryClient = useQueryClient()

  const discoveredQuery = useQuery({
    queryKey: ['call-import-eval-discovered-metrics', getActiveWorkspaceId(), callImportId, evalId],
    queryFn: () =>
      apiClient.callImports.getCallImportEvaluationDiscoveredMetrics(
        callImportId,
        evalId,
      ),
  })

  const invalidateAll = () => {
    queryClient.invalidateQueries({
      queryKey: [
        'call-import-eval-discovered-metrics',
        getActiveWorkspaceId(),
        callImportId,
        evalId,
      ],
    })
    queryClient.invalidateQueries({ queryKey: ['metrics'] })
    queryClient.invalidateQueries({
      queryKey: ['call-import-evaluation', getActiveWorkspaceId(), callImportId, evalId],
    })
  }

  const promoteMutation = useMutation({
    mutationFn: (entry: {
      key: string
      name: string
      description?: string | null
      metric_type: 'boolean' | 'rating' | 'category'
      capture_rationale?: boolean
    }) => apiClient.callImports.promoteDiscoveredMetric(entry),
    onSuccess: invalidateAll,
  })

  const mergeMutation = useMutation({
    mutationFn: (body: { from_key: string; to_key: string }) =>
      apiClient.callImports.mergeCallImportEvaluationDiscoveredMetrics(
        callImportId,
        evalId,
        body,
      ),
    onSuccess: invalidateAll,
  })

  const deleteMutation = useMutation({
    mutationFn: (key: string) =>
      apiClient.callImports.deleteCallImportEvaluationDiscoveredMetric(
        callImportId,
        evalId,
        { key },
      ),
    onSuccess: invalidateAll,
  })

  const items = itemsOf<DiscoveredMetric>(discoveredQuery.data)
  const [collapsed, setCollapsed] = useState(false)
  const [confirmKey, setConfirmKey] = useState<string | null>(null)
  // Per-candidate type override. Defaults to the LLM-suggested type
  // on first render; the user can pick a different shape before
  // hitting Promote.
  const [typeOverrides, setTypeOverrides] = useState<
    Record<string, 'boolean' | 'rating' | 'category'>
  >({})

  const typeFor = (item: (typeof items)[number]) =>
    typeOverrides[item.key] || item.suggested_type || 'boolean'

  return (
    <aside className="border border-amber-200 bg-amber-50/40 rounded-md p-3 text-xs">
      <header className="flex items-center justify-between mb-2 gap-2">
        <button
          type="button"
          onClick={() => setCollapsed((c) => !c)}
          className="font-semibold text-amber-900 inline-flex items-center gap-1 hover:text-amber-950"
          aria-expanded={!collapsed}
          title={collapsed ? 'Expand panel' : 'Collapse panel'}
        >
          {collapsed ? (
            <ChevronRight className="h-3 w-3" />
          ) : (
            <ChevronDown className="h-3 w-3" />
          )}
          <Sparkles className="h-3 w-3" /> Discovered metrics
        </button>
        <span className="text-[10px] text-amber-700">
          {items.length}{' '}
          {items.length === 1 ? 'candidate' : 'candidates'}
        </span>
      </header>
      {collapsed ? null : discoveredQuery.isLoading ? (
        <p className="text-amber-700 italic">Loading…</p>
      ) : items.length === 0 ? (
        <p className="text-amber-800/70 italic">
          No new metrics yet. As rows finish, the LLM may propose
          candidate top-level metrics here that you can promote into
          real Metric rows.
        </p>
      ) : (
        <ul className="space-y-2">
          {items.map((item) => {
            const others = items.filter((o) => o.key !== item.key)
            const chosenType = typeFor(item)
            return (
              <li
                key={item.key}
                className="rounded border border-amber-200 bg-white p-2"
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <p className="font-semibold text-gray-900 truncate">
                      {item.name}
                    </p>
                    <p className="text-[10px] text-gray-500 font-mono truncate">
                      {item.key}
                    </p>
                  </div>
                  <span className="text-[10px] tabular-nums text-amber-700 whitespace-nowrap">
                    {item.count}{' '}
                    {item.count === 1 ? 'call' : 'calls'}
                  </span>
                </div>
                {item.description && (
                  <p className="text-gray-700 mt-1">{item.description}</p>
                )}
                {item.sample_rationale && (
                  <blockquote className="text-gray-500 italic mt-1 border-l-2 border-amber-300 pl-2">
                    "{item.sample_rationale}"
                  </blockquote>
                )}
                <div className="flex items-center gap-1.5 mt-2 flex-wrap">
                  <label className="inline-flex items-center gap-1 text-[10px] text-gray-700">
                    Type
                    <select
                      className="border border-gray-300 rounded px-1 py-0.5 text-[10px] bg-white"
                      value={chosenType}
                      disabled={promoteMutation.isPending}
                      onChange={(e) =>
                        setTypeOverrides((prev) => ({
                          ...prev,
                          [item.key]: e.target.value as
                            | 'boolean'
                            | 'rating'
                            | 'category',
                        }))
                      }
                    >
                      <option value="boolean">Boolean</option>
                      <option value="rating">Rating</option>
                      <option value="category">Category</option>
                    </select>
                  </label>
                  <button
                    type="button"
                    disabled={promoteMutation.isPending}
                    onClick={() => {
                      // Build the description: prefer the LLM's
                      // description, append a single example
                      // rationale so the new metric's rubric starts
                      // with one concrete case. The user can edit
                      // the metric afterwards in the Metrics page.
                      const examplesArr =
                        item.examples && item.examples.length > 0
                          ? item.examples
                          : item.sample_rationale
                            ? [item.sample_rationale]
                            : []
                      const exampleSlice = examplesArr.slice(0, 2)
                      const baseDescription = (item.description || '').trim()
                      const description =
                        exampleSlice.length > 0
                          ? [
                              baseDescription,
                              'Examples:',
                              ...exampleSlice.map((ex) => `- "${ex}"`),
                            ]
                              .filter((part) => part.length > 0)
                              .join('\n\n')
                              .replace(/\n{3,}/g, '\n\n')
                          : baseDescription || null
                      promoteMutation.mutate({
                        key: item.key,
                        name: item.key.replace(/_/g, ' '),
                        description,
                        metric_type: chosenType,
                        capture_rationale: true,
                      })
                    }}
                    className="inline-flex items-center gap-1 text-[10px] font-medium rounded px-1.5 py-0.5 bg-amber-600 text-white hover:bg-amber-700 disabled:opacity-60"
                  >
                    <Plus className="h-3 w-3" /> Promote
                  </button>
                  {others.length > 0 && (
                    <label className="inline-flex items-center gap-1 text-[10px] text-gray-700">
                      <Merge className="h-3 w-3" />
                      <select
                        className="border border-gray-300 rounded px-1 py-0.5 text-[10px] bg-white"
                        defaultValue=""
                        disabled={mergeMutation.isPending}
                        onChange={(e) => {
                          const target = e.target.value
                          if (!target) return
                          mergeMutation.mutate({
                            from_key: item.key,
                            to_key: target,
                          })
                          e.target.value = ''
                        }}
                      >
                        <option value="">Merge into…</option>
                        {others.map((o) => (
                          <option key={o.key} value={o.key}>
                            {o.name}
                          </option>
                        ))}
                      </select>
                    </label>
                  )}
                  {confirmKey === item.key ? (
                    <span className="inline-flex items-center gap-1 text-[10px]">
                      <button
                        type="button"
                        onClick={() => {
                          deleteMutation.mutate(item.key)
                          setConfirmKey(null)
                        }}
                        disabled={deleteMutation.isPending}
                        className="inline-flex items-center gap-1 font-medium rounded px-1.5 py-0.5 bg-red-600 text-white hover:bg-red-700 disabled:opacity-60"
                        title="Permanently remove this candidate from the evaluation"
                      >
                        <Trash2 className="h-3 w-3" /> Confirm delete
                      </button>
                      <button
                        type="button"
                        onClick={() => setConfirmKey(null)}
                        className="inline-flex items-center px-1.5 py-0.5 rounded border border-gray-300 text-gray-600 hover:bg-gray-50"
                      >
                        Cancel
                      </button>
                    </span>
                  ) : (
                    <button
                      type="button"
                      onClick={() => setConfirmKey(item.key)}
                      disabled={deleteMutation.isPending}
                      className="inline-flex items-center gap-1 text-[10px] font-medium rounded px-1.5 py-0.5 border border-red-200 text-red-700 hover:bg-red-50 disabled:opacity-60"
                      title="Delete this LLM-discovered candidate (use for gibberish or irrelevant suggestions)"
                    >
                      <Trash2 className="h-3 w-3" /> Delete
                    </button>
                  )}
                </div>
                {/* Per-type guidance — without this the Promote
                    button silently creates a metric that may not
                    appear on the surface the user expects.
                    Boolean/rating standalone metrics live in the
                    Table / Visualizations tabs (the Flow diagram is
                    reserved for category parents with sub-labels);
                    a category metric promoted with no children is
                    silently skipped by the next eval until children
                    are added. */}
                <p className="text-[10px] text-gray-500 mt-1.5 italic">
                  {chosenType === 'category' ? (
                    <>
                      Creates an empty parent metric. <strong>Add
                      child sub-labels in the Metrics page</strong>{' '}
                      before re-running — without children the next
                      evaluation skips this metric and the Flow
                      diagram has nothing to render.
                    </>
                  ) : chosenType === 'rating' ? (
                    <>
                      Scored 0–1 per call. Appears in the{' '}
                      <strong>Table</strong> and{' '}
                      <strong>Visualizations</strong> tabs on the
                      next run (the Flow diagram is reserved for
                      category metrics with sub-labels).
                    </>
                  ) : (
                    <>
                      Scored true/false per call. Appears in the{' '}
                      <strong>Table</strong> and{' '}
                      <strong>Visualizations</strong> tabs on the
                      next run (the Flow diagram is reserved for
                      category metrics with sub-labels).
                    </>
                  )}
                </p>
              </li>
            )
          })}
        </ul>
      )}
      {(promoteMutation.isError ||
        mergeMutation.isError ||
        deleteMutation.isError) && (
        <p className="text-[10px] text-red-700 mt-1">
          {String(
            (promoteMutation.error as any)?.message ||
              (mergeMutation.error as any)?.message ||
              (deleteMutation.error as any)?.message ||
              'Action failed.',
          )}
        </p>
      )}
    </aside>
  )
}

export { DiscoveredMetricsTopPanel }
