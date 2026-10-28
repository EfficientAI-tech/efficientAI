import { useQuery } from '@tanstack/react-query'
import { apiClient } from '../../../lib/api'
import { evaluationTerminalStatus } from '../evaluationBulkOperation'

export function useCallImportEvaluationAggregate(options: {
  callImportId: string | undefined
  evaluationId: string | undefined
  workspaceId: string | null
  baselineEvaluationId: string | null
  enabled: boolean
  evaluationStatus: string | undefined
}) {
  const {
    callImportId,
    evaluationId,
    workspaceId,
    baselineEvaluationId,
    enabled,
    evaluationStatus,
  } = options

  return useQuery({
    queryKey: [
      'call-import-evaluation-aggregate',
      workspaceId,
      callImportId,
      evaluationId,
      baselineEvaluationId,
    ],
    queryFn: () =>
      apiClient.getCallImportEvaluationAggregate(
        callImportId!,
        evaluationId!,
        baselineEvaluationId,
      ),
    enabled: Boolean(callImportId && evaluationId && enabled),
    staleTime: 60_000,
    refetchOnWindowFocus: false,
    refetchInterval: () => {
      if (evaluationTerminalStatus(evaluationStatus)) return false
      return evaluationStatus === 'pending' || evaluationStatus === 'running'
        ? 5000
        : false
    },
  })
}
