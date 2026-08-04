import { Navigate, useParams } from 'react-router-dom'

/** Legacy nested routes → query-based agent workspace. */
export function RedirectAgentSuiteToWorkspace() {
  const { agentId, suiteId } = useParams<{ agentId: string; suiteId: string }>()
  return (
    <Navigate
      to={`/results/agents/${agentId}?suite=${suiteId}`}
      replace
    />
  )
}

export function RedirectAgentScenarioToWorkspace() {
  const { agentId, suiteId, scenarioId } = useParams<{
    agentId: string
    suiteId: string
    scenarioId: string
  }>()
  return (
    <Navigate
      to={`/results/agents/${agentId}?suite=${suiteId}&scenario=${scenarioId}`}
      replace
    />
  )
}
