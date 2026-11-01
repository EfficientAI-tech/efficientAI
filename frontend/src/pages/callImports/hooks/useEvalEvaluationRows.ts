import { useEffect, useRef } from 'react'
import { keepPreviousData, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../../../lib/api'
import { itemsOf } from '../../../lib/safeData'
import type { CallImportEvaluation, CallImportEvaluationRow } from '../../../types/api'
import {
  evaluationHasActiveBulkOperation,
  evaluationRunPollMs,
} from '../evaluationBulkOperation'

export const EVAL_ROWS_PAGE_SIZE = 50

function evaluationRowsQueryEnabled(
  evaluation: CallImportEvaluation | undefined,
): boolean {
  if (!evaluation) return false
  if (evaluationHasActiveBulkOperation(evaluation)) return true
  const status = evaluation.status
  return (
    status === 'running' ||
    status === 'pending' ||
    status === 'cancelled' ||
    status === 'completed' ||
    status === 'partial' ||
    status === 'failed'
  )
}

export type EvalRowsMetricFilter = {
  metricId: string
  metricName: string
  value: string
} | null

export type EvalRowsClassificationFilter = {
  metricId: string
  metricName: string
  yesNo?: string | null
  choice?: string | null
  level?: string | null
} | null

export type EvalRowsFlowFilter = {
  parentId: string
  parentName: string
  nodeId: string
  nodeLabel: string
  targetNodeId?: string | null
  targetNodeLabel?: string | null
} | null

export type EvalRowsDiscoveredFilter = {
  parentId: string
  parentName: string
  labelKey?: string
  labelName?: string
  anyDiscovered?: boolean
} | null

type UseEvalEvaluationRowsArgs = {
  callImportId: string | undefined
  evaluationId: string | undefined
  activeWorkspaceId: string | null | undefined
  page: number
  searchQuery: string
  statusFilter: string | null
  metricFilter: EvalRowsMetricFilter
  classificationMetricFilter: EvalRowsClassificationFilter
  flowFilter: EvalRowsFlowFilter
  discoveredFilter: EvalRowsDiscoveredFilter
  sortBy: string | null
  sortDir: 'asc' | 'desc'
  resultsTab: 'table' | 'visualizations' | 'flow'
  evaluation: CallImportEvaluation | undefined
  detailRow: CallImportEvaluationRow | null
  setDetailRow: (row: CallImportEvaluationRow | null) => void
  deepLinkConversationId: string
  deepLinkRowId: string
  setSearchQuery: (q: string) => void
  setPage: (page: number) => void
}

export function useEvalEvaluationRows({
  callImportId,
  evaluationId,
  activeWorkspaceId,
  page,
  searchQuery,
  statusFilter,
  metricFilter,
  classificationMetricFilter,
  flowFilter,
  discoveredFilter,
  sortBy,
  sortDir,
  resultsTab,
  evaluation,
  detailRow,
  setDetailRow,
  deepLinkConversationId,
  deepLinkRowId,
  setSearchQuery,
  setPage,
}: UseEvalEvaluationRowsArgs) {
  const queryClient = useQueryClient()

  const rowsQuery = useQuery({
    queryKey: [
      'call-import-evaluation-rows',
      activeWorkspaceId,
      callImportId,
      evaluationId,
      page,
      searchQuery,
      statusFilter,
      metricFilter?.metricId,
      metricFilter?.value,
      classificationMetricFilter?.metricId,
      classificationMetricFilter?.yesNo,
      classificationMetricFilter?.choice,
      classificationMetricFilter?.level,
      flowFilter?.parentId,
      flowFilter?.nodeId,
      flowFilter?.targetNodeId,
      discoveredFilter?.parentId,
      discoveredFilter?.labelKey,
      discoveredFilter?.anyDiscovered,
      sortBy,
      sortDir,
    ],
    queryFn: () =>
      apiClient.callImports.listCallImportEvaluationRows(callImportId!, evaluationId!, {
        page,
        page_size: EVAL_ROWS_PAGE_SIZE,
        q: searchQuery || undefined,
        status: statusFilter || undefined,
        metric_id:
          classificationMetricFilter?.metricId || metricFilter?.metricId,
        metric_value: classificationMetricFilter
          ? undefined
          : metricFilter?.value,
        classification_yes_no: classificationMetricFilter?.yesNo || undefined,
        classification_choice:
          classificationMetricFilter?.choice || undefined,
        classification_level: classificationMetricFilter?.level || undefined,
        flow_parent_id: flowFilter?.parentId,
        flow_node: flowFilter?.nodeId,
        flow_edge_target: flowFilter?.targetNodeId || undefined,
        discovered_parent_id: discoveredFilter?.parentId,
        discovered_label_key: discoveredFilter?.labelKey,
        has_discovered: discoveredFilter?.anyDiscovered || undefined,
        sort_by: sortBy || undefined,
        sort_dir: sortBy ? sortDir : undefined,
      }),
    enabled:
      !!callImportId &&
      !!evaluationId &&
      resultsTab === 'table' &&
      evaluationRowsQueryEnabled(evaluation),
    staleTime: 60_000,
    placeholderData: keepPreviousData,
    refetchOnWindowFocus: false,
    refetchInterval: () => evaluationRunPollMs(evaluation),
  })

  const { data: detailRowFull } = useQuery({
    queryKey: [
      'call-import-evaluation-rows',
      activeWorkspaceId,
      callImportId,
      evaluationId,
      'row',
      detailRow?.id,
    ],
    queryFn: () =>
      apiClient.callImports.getCallImportEvaluationRow(
        callImportId!,
        evaluationId!,
        detailRow!.id,
      ),
    enabled: !!callImportId && !!evaluationId && !!detailRow?.id,
    staleTime: 60_000,
    refetchOnWindowFocus: false,
    refetchInterval: () => evaluationRunPollMs(evaluation),
  })

  useEffect(() => {
    if (!callImportId || !evaluationId || !rowsQuery.data) return
    if (page * EVAL_ROWS_PAGE_SIZE >= rowsQuery.data.total) return
    const nextPage = page + 1
    void queryClient.prefetchQuery({
      queryKey: [
        'call-import-evaluation-rows',
        activeWorkspaceId,
        callImportId,
        evaluationId,
        nextPage,
        searchQuery,
        statusFilter,
        metricFilter?.metricId,
        metricFilter?.value,
        classificationMetricFilter?.metricId,
        classificationMetricFilter?.yesNo,
        classificationMetricFilter?.choice,
        classificationMetricFilter?.level,
        flowFilter?.parentId,
        flowFilter?.nodeId,
        flowFilter?.targetNodeId,
        discoveredFilter?.parentId,
        discoveredFilter?.labelKey,
        discoveredFilter?.anyDiscovered,
        sortBy,
        sortDir,
      ],
      queryFn: () =>
        apiClient.callImports.listCallImportEvaluationRows(callImportId, evaluationId, {
          page: nextPage,
          page_size: EVAL_ROWS_PAGE_SIZE,
          q: searchQuery || undefined,
          status: statusFilter || undefined,
          metric_id:
            classificationMetricFilter?.metricId || metricFilter?.metricId,
          metric_value: classificationMetricFilter
            ? undefined
            : metricFilter?.value,
          classification_yes_no:
            classificationMetricFilter?.yesNo || undefined,
          classification_choice:
            classificationMetricFilter?.choice || undefined,
          classification_level:
            classificationMetricFilter?.level || undefined,
          flow_parent_id: flowFilter?.parentId,
          flow_node: flowFilter?.nodeId,
          flow_edge_target: flowFilter?.targetNodeId || undefined,
          discovered_parent_id: discoveredFilter?.parentId,
          discovered_label_key: discoveredFilter?.labelKey,
          has_discovered: discoveredFilter?.anyDiscovered || undefined,
          sort_by: sortBy || undefined,
          sort_dir: sortBy ? sortDir : undefined,
        }),
      staleTime: 60_000,
    })
  }, [
    callImportId,
    evaluationId,
    page,
    rowsQuery.data,
    searchQuery,
    statusFilter,
    metricFilter,
    classificationMetricFilter,
    flowFilter,
    discoveredFilter,
    sortBy,
    sortDir,
    activeWorkspaceId,
    queryClient,
  ])

  useEffect(() => {
    if (!detailRow) return
    const items = rowsQuery.data?.items ?? []
    if (!items.some((r) => r.id === detailRow.id)) {
      setDetailRow(null)
    }
  }, [rowsQuery.data?.items, detailRow, setDetailRow])

  const evaluationRowsLive = evaluationRunPollMs(evaluation) !== false
  const evaluationRowsWereLive = useRef(false)
  useEffect(() => {
    if (evaluationRowsLive) {
      evaluationRowsWereLive.current = true
      return
    }
    if (!evaluationRowsWereLive.current || !callImportId || !evaluationId) return
    evaluationRowsWereLive.current = false
    void queryClient.invalidateQueries({
      queryKey: [
        'call-import-evaluation-rows',
        activeWorkspaceId,
        callImportId,
        evaluationId,
      ],
    })
  }, [
    evaluationRowsLive,
    callImportId,
    evaluationId,
    activeWorkspaceId,
    queryClient,
  ])

  useEffect(() => {
    if (!deepLinkConversationId && !deepLinkRowId) return
    if (deepLinkConversationId && searchQuery !== deepLinkConversationId) {
      setSearchQuery(deepLinkConversationId)
      setPage(1)
    }
  }, [deepLinkConversationId, deepLinkRowId, searchQuery, setSearchQuery, setPage])

  useEffect(() => {
    if (!deepLinkConversationId && !deepLinkRowId) return
    const items = itemsOf<CallImportEvaluationRow>(rowsQuery.data)
    const match = items.find((row) =>
      deepLinkRowId
        ? row.id === deepLinkRowId
        : (row.conversation_id || '').trim() === deepLinkConversationId,
    )
    if (match) setDetailRow(match)
  }, [
    rowsQuery.data?.items,
    deepLinkConversationId,
    deepLinkRowId,
    setDetailRow,
  ])

  return { rowsQuery, detailRowFull }
}
