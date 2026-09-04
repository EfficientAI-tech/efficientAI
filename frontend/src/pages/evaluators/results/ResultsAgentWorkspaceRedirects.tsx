import { Navigate, useParams } from 'react-router-dom'

/** Legacy nested routes → query-based results hub. */
export function RedirectAgentSuiteToWorkspace() {
  const { agentId, suiteId } = useParams<{ agentId: string; suiteId: string }>()
  return (
    <Navigate
      to={`/results?agent=${agentId}&suite=${suiteId}`}
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
      to={`/results?agent=${agentId}&suite=${suiteId}&scenario=${scenarioId}`}
      replace
    />
  )
}

export function RedirectAgentWorkspaceToHub() {
  const { agentId } = useParams<{ agentId: string }>()
  return <Navigate to={`/results?agent=${agentId}`} replace />
}
