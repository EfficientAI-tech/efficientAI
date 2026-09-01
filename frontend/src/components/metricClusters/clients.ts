import { apiClient } from '../../lib/api'
import type {
  EvaluationMetricClustersState,
  MetricClusterEvidence,
  MetricClusterEligibleRowsResponse,
  MetricFailurePoliciesResponse,
  MetricFailurePolicy,
} from '../../types/api'

export interface MetricClustersClient {
  queryKeyPrefix: readonly unknown[]
  getFailurePolicies(): Promise<MetricFailurePoliciesResponse>
  saveFailurePolicies(
    policies: Record<string, MetricFailurePolicy>,
  ): Promise<MetricFailurePoliciesResponse>
  listEligibleRows(options?: {
    limit?: number
    count_only?: boolean
  }): Promise<MetricClusterEligibleRowsResponse>
  generateClusters(options: {
    force?: boolean
    regenerate?: boolean
    provider?: string
    model?: string
    row_limit?: number
    failure_policies?: Record<string, MetricFailurePolicy>
  }): Promise<EvaluationMetricClustersState>
  cancelClusters(): Promise<EvaluationMetricClustersState>
  buildEvidenceHref(evidence: MetricClusterEvidence): string | null
}

function buildCallImportEvidenceHref(
  callImportId: string,
  evaluationId: string,
  evidence: MetricClusterEvidence,
): string | null {
  const conv = evidence.conversation_id?.trim()
  const rowId = evidence.evaluation_row_id?.trim()
  if (!conv && !rowId) return null
  const base = `/call-imports/${callImportId}/evaluations/${evaluationId}`
  if (conv) {
    return `${base}?conversation_id=${encodeURIComponent(conv)}`
  }
  return `${base}?row_id=${encodeURIComponent(rowId!)}`
}

export function createCallImportMetricClustersClient(
  callImportId: string,
  evaluationId: string,
  workspaceId: string | null | undefined,
): MetricClustersClient {
  const queryKeyPrefix = [
    'call-import-evaluation-metric-clusters',
    workspaceId,
    callImportId,
    evaluationId,
  ] as const

  return {
    queryKeyPrefix,
    getFailurePolicies: () =>
      apiClient.getCallImportEvaluationMetricClusterFailurePolicies(
        callImportId,
        evaluationId,
      ),
    saveFailurePolicies: (policies) =>
      apiClient.saveCallImportEvaluationMetricClusterFailurePolicies(
        callImportId,
        evaluationId,
        policies,
      ),
    listEligibleRows: (options) =>
      apiClient.listCallImportEvaluationMetricClusterEligibleRows(
        callImportId,
        evaluationId,
        options,
      ),
    generateClusters: (options) =>
      apiClient.generateCallImportEvaluationMetricClusters(
        callImportId,
        evaluationId,
        options,
      ),
    cancelClusters: () =>
      apiClient.cancelCallImportEvaluationMetricClusters(
        callImportId,
        evaluationId,
      ),
    buildEvidenceHref: (evidence) =>
      buildCallImportEvidenceHref(callImportId, evaluationId, evidence),
  }
}

export type EvaluatorResultClusterScope = {
  agentId: string
  scenarioIds?: string[]
  since?: string
  until?: string
  jobId?: string
  /** @deprecated Use jobId — scope_key contains characters that break URL parsing */
  scopeKey?: string
}

export function createEvaluatorResultsMetricClustersClient(
  scope: EvaluatorResultClusterScope,
  workspaceId: string | null | undefined,
): MetricClustersClient {
  const queryKeyPrefix = [
    'evaluator-results-metric-clusters',
    workspaceId,
    scope.jobId ?? '',
    scope.agentId,
    scope.scenarioIds?.join(',') ?? '',
    scope.since ?? '',
    scope.until ?? '',
  ] as const

  return {
    queryKeyPrefix,
    getFailurePolicies: () =>
      apiClient.getEvaluatorResultMetricClusterFailurePolicies(scope),
    saveFailurePolicies: (policies) =>
      apiClient.saveEvaluatorResultMetricClusterFailurePolicies(scope, policies),
    listEligibleRows: (options) =>
      apiClient.listEvaluatorResultMetricClusterEligibleRows(scope, options),
    generateClusters: (options) =>
      apiClient.generateEvaluatorResultMetricClusters(scope, options),
    cancelClusters: () => apiClient.cancelEvaluatorResultMetricClusters(scope),
    buildEvidenceHref: (evidence) => {
      const id = evidence.conversation_id?.trim()
      if (!id) return null
      return `/results/${id}`
    },
  }
}
