import { useQuery } from '@tanstack/react-query'
import { apiClient } from '../../../lib/api'
import ResultsRunsList from './ResultsRunsList'

export default function ResultsUnassigned() {
  const { data: overview } = useQuery({
    queryKey: ['evaluator-results-overview'],
    queryFn: () => apiClient.getEvaluatorResultsOverview(),
  })

  return (
    <ResultsRunsList
      title="Unassigned runs"
      subtitle="Legacy or manual evaluations not linked to an evaluator suite"
      crumbs={[
        { label: 'Evaluation Results', to: '/results' },
        { label: 'Unassigned' },
      ]}
      listParams={{ unassignedOnly: true }}
      counts={overview?.unassigned.counts}
      showAgentColumn
      showScenarioColumn
    />
  )
}
