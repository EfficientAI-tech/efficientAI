import type { MetricClusterGenerationScope } from '../../types/api'
import type { EvaluatorResultClusterScope } from './clients'
import { formatResultsDateRange } from '../../pages/evaluators/results/resultsDateRange'

export function generationScopeToClusterScope(
  scope: MetricClusterGenerationScope,
  jobId?: string,
): EvaluatorResultClusterScope {
  return {
    agentId: scope.agent_id,
    scenarioIds: scope.scenario_ids?.length ? scope.scenario_ids : undefined,
    since: scope.since ?? undefined,
    until: scope.until ?? undefined,
    jobId,
  }
}

export function clusterScopesMatch(
  a: EvaluatorResultClusterScope | null,
  b: EvaluatorResultClusterScope | null,
): boolean {
  if (!a || !b) return false
  if (a.jobId && b.jobId) return a.jobId === b.jobId
  if (a.scopeKey && b.scopeKey) return a.scopeKey === b.scopeKey
  const scenarioA = a.scenarioIds?.slice().sort().join(',') ?? ''
  const scenarioB = b.scenarioIds?.slice().sort().join(',') ?? ''
  return (
    a.agentId === b.agentId &&
    scenarioA === scenarioB &&
    (a.since ?? '') === (b.since ?? '') &&
    (a.until ?? '') === (b.until ?? '')
  )
}

export function formatClusterScopeHistoryLabel(
  scope: MetricClusterGenerationScope,
): string {
  const agent = scope.agent_name ?? 'Agent'
  const scenarios =
    scope.scenario_names?.length
      ? scope.scenario_names.join(', ')
      : 'All scenarios'
  let dates = 'All time'
  if (scope.since && scope.until) {
    dates = formatResultsDateRange(
      scope.since.slice(0, 10),
      scope.until.slice(0, 10),
    )
  }
  return `${agent} · ${scenarios} · ${dates}`
}

export function clusterScopeStatusLabel(status: string): string {
  switch (status) {
    case 'running':
      return 'Generating'
    case 'completed':
      return 'Ready'
    case 'failed':
      return 'Failed'
    case 'cancelled':
      return 'Stopped'
    default:
      return 'Draft'
  }
}
