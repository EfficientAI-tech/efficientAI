import { useQuery } from '@tanstack/react-query'
import { Filter, RefreshCw } from 'lucide-react'
import { apiClient } from '../../../../lib/api'
import { getActiveWorkspaceId } from '../../../../store/workspaceStore'
import MetricFlowChart from '../MetricFlowChart'
import { DiscoveredLabelsPanel } from './DiscoveredLabelsPanel'

function FlowDiagramForParent({
  callImportId,
  evalId,
  parent,
  onNodeClick,
  onEdgeClick,
  onViewDiscoveredCalls,
  onViewAnyDiscoveredCalls,
}: {
  callImportId: string
  evalId: string
  parent: {
    id: string
    name: string
    selection_mode: 'single_choice' | 'multi_label' | null
    allow_discovery: boolean
    children: { id: string; name: string }[]
  }
  onNodeClick?: (node: import('../MetricFlowChart').FlowNodeClick) => void
  onEdgeClick?: (edge: import('../MetricFlowChart').FlowEdgeClick) => void
  onViewDiscoveredCalls?: (item: {
    key: string
    name: string
  }) => void
  onViewAnyDiscoveredCalls?: () => void
}) {
  const flowQuery = useQuery({
    queryKey: ['call-import-eval-flow', getActiveWorkspaceId(), callImportId, evalId, parent.id],
    queryFn: () =>
      apiClient.callImports.getCallImportEvaluationFlow(callImportId, evalId, parent.id),
  })

  const showDiscoveryPanel =
    !!parent.selection_mode && parent.allow_discovery

  return (
    <div className="border border-gray-200 rounded-lg p-3 bg-white">
      <div className="flex items-baseline justify-between mb-2 gap-3 flex-wrap">
        <div>
          <p className="text-sm font-semibold text-gray-900 inline-flex items-center gap-1.5">
            {parent.name}
            {parent.allow_discovery && (
              <span
                className="text-[9px] uppercase tracking-wide font-semibold rounded-sm bg-amber-50 text-amber-700 border border-amber-200 px-1 py-[1px]"
                title="LLM-driven discovery enabled for this category"
              >
                +disc
              </span>
            )}
          </p>
          <p className="text-[11px] text-gray-500">
            {parent.selection_mode === 'single_choice'
              ? 'Pick-one category'
              : 'Multi-label category'}{' '}
            · {parent.children.length} sub-labels
          </p>
        </div>
        {flowQuery.data && (
          <p className="text-[11px] text-gray-500 tabular-nums">
            {flowQuery.data.rows_with_sequence}/{flowQuery.data.total_rows}{' '}
            rows scored
          </p>
        )}
      </div>
      <div
        className={
          showDiscoveryPanel
            ? 'grid grid-cols-1 lg:grid-cols-[1fr_320px] gap-3'
            : ''
        }
      >
        <div>
          {flowQuery.isLoading || !flowQuery.data ? (
            <div className="text-center py-8 text-gray-500">
              <RefreshCw className="h-5 w-5 mx-auto mb-2 animate-spin" />
              <p className="text-xs">Loading flow…</p>
            </div>
          ) : flowQuery.data.rows_with_sequence === 0 ? (
            <p className="text-xs text-gray-500 italic">
              No rows produced a label sequence for this category yet.
            </p>
          ) : (
            <>
              <MetricFlowChart
                data={flowQuery.data}
                mode="aggregate"
                height={360}
                onNodeClick={onNodeClick}
                onEdgeClick={onEdgeClick}
              />
              {(onNodeClick || onEdgeClick) && (
                <p className="text-[11px] text-gray-500 mt-1.5 inline-flex items-center gap-1">
                  <Filter className="h-3 w-3" />
                  Click a node to filter calls that passed through that
                  label, or an edge for the directed transition.
                </p>
              )}
            </>
          )}
        </div>
        {showDiscoveryPanel && (
          <DiscoveredLabelsPanel
            callImportId={callImportId}
            evalId={evalId}
            parent={parent}
            onViewDiscoveredCalls={onViewDiscoveredCalls}
            onViewAnyDiscoveredCalls={onViewAnyDiscoveredCalls}
          />
        )}
      </div>
    </div>
  )
}

export { FlowDiagramForParent }
