import ClusterScopeInfo from './ClusterScopeInfo'
import ClusterHierarchyExplorer from './ClusterHierarchyExplorer'
import type { MetricClustersClient } from './clients'
import type {
  EvaluationMetricClustersState,
  EvaluatorResultsAgentSummary,
} from './types'
import type { EvaluatorResultClusterScope } from './clients'

export default function ClusterReportDetailsTab({
  state,
  client,
  agents = [],
  urlScope = null,
}: {
  state: EvaluationMetricClustersState
  client: MetricClustersClient
  agents?: EvaluatorResultsAgentSummary[]
  urlScope?: EvaluatorResultClusterScope | null
}) {
  return (
    <div className="space-y-4">
      <ClusterScopeInfo state={state} agents={agents} urlScope={urlScope} />
      <ClusterHierarchyExplorer state={state} client={client} />
    </div>
  )
}
