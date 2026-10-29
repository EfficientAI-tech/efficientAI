import { useQuery } from '@tanstack/react-query'
import { apiClient } from '../../../lib/api'
import type { CallImportEvaluation } from '../../../types/api'
import { evaluationRunPollMs } from '../evaluationBulkOperation'

export function useCallImportEvaluationAggregate(options: {
  callImportId: string | undefined
  evaluationId: string | undefined
  workspaceId: string | null
  baselineEvaluationId: string | null
  enabled: boolean
  evaluation: CallImportEvaluation | undefined
}) {
  const {
    callImportId,
    evaluationId,
    workspaceId,
    baselineEvaluationId,
    enabled,
    evaluation,
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
      apiClient.callImports.getCallImportEvaluationAggregate(
        callImportId!,
        evaluationId!,
        baselineEvaluationId,
      ),
    enabled: Boolean(callImportId && evaluationId && enabled),
    staleTime: 60_000,
    refetchOnWindowFocus: false,
    refetchInterval: () => evaluationRunPollMs(evaluation) || false,
  })
}
