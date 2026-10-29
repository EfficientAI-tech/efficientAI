import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ChevronDown,
  ChevronRight,
  Filter,
  Merge,
  Plus,
  Sparkles,
  Trash2,
} from 'lucide-react'
import { apiClient } from '../../../../lib/api'
import { itemsOf } from '../../../../lib/safeData'
import type { DiscoveredMetric } from '../../../../types/api'
import { getActiveWorkspaceId } from '../../../../store/workspaceStore'

function DiscoveredLabelsPanel({
  callImportId,
  evalId,
  parent,
  onViewDiscoveredCalls,
  onViewAnyDiscoveredCalls,
}: {
  callImportId: string
  evalId: string
  parent: {
    id: string
    name: string
    selection_mode: 'single_choice' | 'multi_label' | null
    children: { id: string; name: string }[]
  }
  onViewDiscoveredCalls?: (item: { key: string; name: string }) => void
  onViewAnyDiscoveredCalls?: () => void
}) {
  const queryClient = useQueryClient()
  const discoveredQuery = useQuery({
    queryKey: [
      'call-import-eval-discovered',
      getActiveWorkspaceId(),
      callImportId,
      evalId,
      parent.id,
    ],
    queryFn: () =>
      apiClient.callImports.getCallImportEvaluationDiscoveredLabels(
        callImportId,
        evalId,
        parent.id,
      ),
  })

  const invalidateAll = () => {
    queryClient.invalidateQueries({
      queryKey: ['call-import-eval-discovered', getActiveWorkspaceId(), callImportId, evalId, parent.id],
    })
    queryClient.invalidateQueries({
      queryKey: ['call-import-eval-flow', getActiveWorkspaceId(), callImportId, evalId, parent.id],
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
      capture_rationale?: boolean
    }) => apiClient.callImports.promoteDiscoveredChild(parent.id, entry),
    onSuccess: invalidateAll,
  })

  const mergeMutation = useMutation({
    mutationFn: (body: { from_key: string; to_key: string }) =>
      apiClient.callImports.mergeCallImportEvaluationDiscoveredLabels(
        callImportId,
        evalId,
        { parent_metric_id: parent.id, ...body },
      ),
    onSuccess: invalidateAll,
  })

  const deleteMutation = useMutation({
    mutationFn: (key: string) =>
      apiClient.callImports.deleteCallImportEvaluationDiscoveredLabel(
        callImportId,
        evalId,
        { parent_metric_id: parent.id, key },
      ),
    onSuccess: invalidateAll,
  })

  // Defense-in-depth: even though the backend now hides candidates whose
  // slug already matches a real promoted child, we re-filter here so a
  // stale GET response can't briefly resurrect a candidate the user has
  // already accepted (e.g. between promote and the discovered-labels
  // refetch).
  const childSlugs = useMemo(() => {
    const set = new Set<string>()
    for (const c of parent.children || []) {
      const slug = c.name.trim().toLowerCase().split(/\s+/).join('_')
      if (slug) set.add(slug)
    }
    return set
  }, [parent.children])
  const items = itemsOf<DiscoveredMetric>(discoveredQuery.data).filter(
    (item) => !childSlugs.has(item.key),
  )

  // Per-parent collapse state. Defaults to expanded so existing users
  // see the panel as before; collapsing only hides the body so the
  // header still shows the candidate count.
  const [collapsed, setCollapsed] = useState(false)
  // Two-step delete confirmation: clicking Delete arms the entry, a
  // second click within ``confirmKey`` actually fires the mutation.
  // Avoids a global modal and keeps the action inline with the
  // candidate row that's about to disappear.
  const [confirmKey, setConfirmKey] = useState<string | null>(null)

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
          {items.length} {items.length === 1 ? 'candidate' : 'candidates'}
        </span>
      </header>
      {collapsed ? null : onViewAnyDiscoveredCalls && items.length > 0 && (
        <button
          type="button"
          onClick={onViewAnyDiscoveredCalls}
          className="mb-2 inline-flex items-center gap-1 text-[10px] font-medium text-amber-800 hover:text-amber-900 underline underline-offset-2"
        >
          <Filter className="h-3 w-3" />
          Show all calls with discovered metrics
        </button>
      )}
      {collapsed ? null : discoveredQuery.isLoading ? (
        <p className="text-amber-700 italic">Loading…</p>
      ) : items.length === 0 ? (
        <p className="text-amber-800/70 italic">
          No new metrics yet. As rows finish, the LLM may propose
          candidates here that you can promote into real sub-metrics.
        </p>
      ) : (
        <ul className="space-y-2">
          {items.map((item) => {
            const others = items.filter((o) => o.key !== item.key)
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
                  <button
                    type="button"
                    disabled={promoteMutation.isPending}
                    onClick={() => {
                      // Pull up to 2 distinct rationales captured for
                      // this candidate, append them as an Examples
                      // block to the new sub-metric's rubric, and
                      // turn on capture_rationale so future rows that
                      // hit this label keep producing rationales.
                      // Older payloads (before the backend learned to
                      // collect ``examples``) only carry
                      // ``sample_rationale`` — fall back to that so
                      // promote still works against legacy evals.
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
                        capture_rationale: true,
                      })
                    }}
                    className="inline-flex items-center gap-1 text-[10px] font-medium rounded px-1.5 py-0.5 bg-amber-600 text-white hover:bg-amber-700 disabled:opacity-60"
                  >
                    <Plus className="h-3 w-3" /> Promote
                  </button>
                  {onViewDiscoveredCalls && (
                    <button
                      type="button"
                      onClick={() =>
                        onViewDiscoveredCalls({
                          key: item.key,
                          name: item.name,
                        })
                      }
                      className="inline-flex items-center gap-1 text-[10px] font-medium rounded px-1.5 py-0.5 border border-amber-300 text-amber-800 bg-white hover:bg-amber-50"
                      title="Filter the row table to calls that produced this discovered metric"
                    >
                      <Filter className="h-3 w-3" /> View calls
                    </button>
                  )}
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

export { DiscoveredLabelsPanel }
