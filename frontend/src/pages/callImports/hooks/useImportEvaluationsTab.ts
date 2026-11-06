import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../../../lib/api'
import { itemsOf } from '../../../lib/safeData'
import type {
  CallImportEvaluation,
  CallImportEvaluationBulkActionResponse,
  CallImportEvaluationListResponse,
} from '../../../types/api'
import {
  bulkCancelResponseKeepsBulkOperation,
  evaluationListPollMs,
  type BulkEvaluationOperation,
} from '../evaluationBulkOperation'
import {
  type LatestEvalSnapshot,
  latestEvaluationPollMs,
  latestEvaluationShouldPoll,
} from '../importPolling'

type ActiveTab = 'rows' | 'evaluations' | 'insights'

export function useImportEvaluationsTab(
  importId: string | undefined,
  activeWorkspaceId: string | null,
  activeTab: ActiveTab,
  reportDeleteError: (
    err: unknown,
    fallback: string,
    setError: (message: string) => void,
  ) => void,
  importHeader?: LatestEvalSnapshot,
) {
  const queryClient = useQueryClient()

  const evaluationsQueryKey = [
    'call-import-evaluations',
    activeWorkspaceId,
    importId,
  ] as const

  const setEvaluationBulkOperationInList = (
    evaluationId: string,
    operation: BulkEvaluationOperation | null,
  ) => {
    if (!importId) return
    queryClient.setQueryData<CallImportEvaluationListResponse>(
      evaluationsQueryKey,
      (prev) => {
        if (!prev) return prev
        return {
          ...prev,
          items: prev.items.map((item) =>
            item.id === evaluationId
              ? { ...item, bulk_operation: operation }
              : item,
          ),
        }
      },
    )
  }

  const { data: evaluationsData } = useQuery({
    queryKey: evaluationsQueryKey,
    queryFn: () => apiClient.callImports.listCallImportEvaluations(importId!),
    enabled: !!importId,
    refetchOnWindowFocus: false,
    refetchInterval: (query) => {
      const items = itemsOf<CallImportEvaluation>(query.state.data)
      const listMs = evaluationListPollMs(items)
      if (listMs) return listMs
      if (
        activeTab !== 'evaluations' &&
        activeTab !== 'insights' &&
        latestEvaluationShouldPoll(importHeader)
      ) {
        return latestEvaluationPollMs(importHeader) || false
      }
      if (activeTab === 'evaluations' || activeTab === 'insights') {
        return false
      }
      return false
    },
  })

  const evaluationsWithBulkOperation = useMemo(
    () =>
      itemsOf<CallImportEvaluation>(evaluationsData).filter(
        (evaluation) => evaluation.bulk_operation != null,
      ),
    [evaluationsData],
  )

  const [selectedEvalIds, setSelectedEvalIds] = useState<Set<string>>(new Set())
  const [showBulkDeleteEvals, setShowBulkDeleteEvals] = useState(false)
  const [bulkDeleteEvalsError, setBulkDeleteEvalsError] = useState<string | null>(
    null,
  )

  const bulkDeleteEvalsMutation = useMutation({
    mutationFn: (ids: string[]) =>
      apiClient.callImports.bulkDeleteCallImportEvaluations(importId!, ids),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ['call-import-evaluations', activeWorkspaceId, importId],
      })
      setSelectedEvalIds(new Set())
      setShowBulkDeleteEvals(false)
      setBulkDeleteEvalsError(null)
    },
    onError: (err: unknown) => {
      reportDeleteError(
        err,
        'Failed to delete evaluation runs.',
        setBulkDeleteEvalsError,
      )
    },
  })

  const [cancellingEvalId, setCancellingEvalId] = useState<string | null>(null)

  const cancelEvaluationMutation = useMutation({
    mutationFn: (evaluationId: string) =>
      apiClient.callImports.cancelCallImportEvaluation(importId!, evaluationId),
    onMutate: (evaluationId) => {
      setCancellingEvalId(evaluationId)
    },
    onSuccess: (data: CallImportEvaluationBulkActionResponse, evaluationId) => {
      if (bulkCancelResponseKeepsBulkOperation(data)) {
        setEvaluationBulkOperationInList(evaluationId, 'abort')
      }
      queryClient.invalidateQueries({ queryKey: evaluationsQueryKey })
    },
    onError: (err: unknown) => {
      console.error('cancelEvaluationMutation failed:', err)
    },
    onSettled: () => {
      setCancellingEvalId(null)
    },
  })

  const bulkCancelEvalsMutation = useMutation({
    mutationFn: async (ids: string[]) => {
      const results = await Promise.allSettled(
        ids.map(async (evalId) => ({
          evalId,
          response: await apiClient.callImports.cancelCallImportEvaluation(importId!, evalId),
        })),
      )
      const fulfilled = results.filter((r) => r.status === 'fulfilled').length
      const rejected = results.filter((r) => r.status === 'rejected').length
      return { results, fulfilled, rejected }
    },
    onSuccess: ({ results }) => {
      for (const result of results) {
        if (
          result.status === 'fulfilled' &&
          bulkCancelResponseKeepsBulkOperation(result.value.response)
        ) {
          setEvaluationBulkOperationInList(result.value.evalId, 'abort')
        }
      }
      queryClient.invalidateQueries({ queryKey: evaluationsQueryKey })
      setSelectedEvalIds(new Set())
    },
    onError: (err: unknown) => {
      console.error('bulkCancelEvalsMutation failed:', err)
    },
  })

  return {
    evaluationsData,
    evaluationsWithBulkOperation,
    selectedEvalIds,
    setSelectedEvalIds,
    showBulkDeleteEvals,
    setShowBulkDeleteEvals,
    bulkDeleteEvalsError,
    setBulkDeleteEvalsError,
    bulkDeleteEvalsMutation,
    cancellingEvalId,
    cancelEvaluationMutation,
    bulkCancelEvalsMutation,
  }
}
