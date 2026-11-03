import { useQuery } from '@tanstack/react-query'
import { apiClient } from '../../../lib/api'
import type { CallImportEvaluation } from '../../../types/api'
import { evaluationRunPollMs } from '../evaluationBulkOperation'

/** Chart histograms for the Visualizations tab (never includes baseline comparison). */
export function useCallImportEvaluationAggregate(options: {
  callImportId: string | undefined
  evaluationId: string | undefined
  workspaceId: string | null
  enabled: boolean
  evaluation: CallImportEvaluation | undefined
}) {
  const { callImportId, evaluationId, workspaceId, enabled, evaluation } =
    options

  return useQuery({
    queryKey: [
      'call-import-evaluation-aggregate',
      workspaceId,
      callImportId,
      evaluationId,
    ],
    queryFn: () =>
      apiClient.callImports.getCallImportEvaluationAggregate(
        callImportId!,
        evaluationId!,
        null,
      ),
    enabled: Boolean(callImportId && evaluationId && enabled),
    staleTime: 60_000,
    refetchOnWindowFocus: false,
    refetchInterval: () => evaluationRunPollMs(evaluation) || false,
  })
}

/** Week-over-week ``period_deltas`` badges; separate query so charts stay mounted. */
export function useCallImportEvaluationAggregatePeriodDeltas(options: {
  callImportId: string | undefined
  evaluationId: string | undefined
  workspaceId: string | null
  baselineEvaluationId: string | null
  enabled: boolean
  chartsReady: boolean
}) {
  const {
    callImportId,
    evaluationId,
    workspaceId,
    baselineEvaluationId,
    enabled,
    chartsReady,
  } = options

  return useQuery({
    queryKey: [
      'call-import-evaluation-aggregate-deltas',
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
    enabled: Boolean(
      callImportId &&
        evaluationId &&
        enabled &&
        chartsReady &&
        baselineEvaluationId,
    ),
    staleTime: 60_000,
    refetchOnWindowFocus: false,
    refetchInterval: false,
    select: (data) => ({
      period_deltas: data.period_deltas ?? {},
      baseline_evaluation_id: data.baseline_evaluation_id ?? null,
    }),
  })
}
