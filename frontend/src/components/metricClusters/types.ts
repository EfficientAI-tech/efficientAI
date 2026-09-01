import type {
  EvaluationMetricClustersState,
  EvaluatorResultsAgentSummary,
} from '../../types/api'
import type { EvaluatorResultClusterScope, MetricClustersClient } from './clients'

export type {
  EvaluationMetricClustersState,
  EvaluatorResultsAgentSummary,
  MetricClusterEvidence,
  MetricClusterGenerationScope,
  MetricClustersRcaSummary,
  MetricFailurePolicy,
  MetricFailurePolicyMetricPreview,
} from '../../types/api'

export interface EvaluatorClusterScopeConfig {
  agents: EvaluatorResultsAgentSummary[]
  scope: EvaluatorResultClusterScope | null
  onScopeCommit: (scope: EvaluatorResultClusterScope) => void
}

export type ClusterReportView = 'details' | 'visualization'

export interface MetricClustersPanelProps {
  client: MetricClustersClient
  defaultProvider?: string
  defaultModel?: string
  state: EvaluationMetricClustersState | null
  isLoading: boolean
  onGenerated: (state?: EvaluationMetricClustersState, scope?: EvaluatorResultClusterScope) => void
  evaluatorScope?: EvaluatorClusterScopeConfig
  registerOpenGenerateModal?: (open: () => void) => void
  onGenerateModalOpenChange?: (open: boolean) => void
  activeView?: ClusterReportView
  onViewChange?: (view: ClusterReportView) => void
}
