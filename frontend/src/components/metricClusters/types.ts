import type { EvaluationMetricClustersState } from '../../types/api'
import type { MetricClustersClient } from './clients'

export type {
  EvaluationMetricClustersState,
  MetricClusterEvidence,
  MetricClustersRcaSummary,
  MetricFailurePolicy,
  MetricFailurePolicyMetricPreview,
} from '../../types/api'

export interface MetricClustersPanelProps {
  client: MetricClustersClient
  defaultProvider?: string
  defaultModel?: string
  state: EvaluationMetricClustersState | null
  isLoading: boolean
  onGenerated: () => void
}
