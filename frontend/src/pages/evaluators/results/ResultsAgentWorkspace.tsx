import { useEffect, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useParams, useSearchParams } from 'react-router-dom'
import { apiClient } from '../../../lib/api'
import ResultsHierarchyNav from './ResultsHierarchyNav'
import ResultsCountCards from './ResultsCountCards'
import ResultsRunsList from './ResultsRunsList'
import EvaluatorResultDetailPage from './EvaluatorResultDetail'
import { ChevronDown, ChevronRight, FolderKanban, FileText } from 'lucide-react'
import type {
  EvaluatorResultsScenarioSummary,
  EvaluatorResultsSuiteSummary,
} from '../../../types/api'

export default function ResultsAgentWorkspace() {
  const { agentId } = useParams<{ agentId: string }>()
  const [searchParams, setSearchParams] = useSearchParams()
  const selectedSuiteId = searchParams.get('suite') ?? ''
  const selectedScenarioId = searchParams.get('scenario') ?? ''
  const selectedResultId = searchParams.get('result') ?? ''

  const { data: agentOverview, isLoading: loadingAgent } = useQuery({
    queryKey: ['evaluator-results-overview', 'agent', agentId],
    queryFn: () => apiClient.getEvaluatorResultsOverview({ agentId }),
    enabled: Boolean(agentId),
  })

  const agent = agentOverview?.agents[0]
  const suites = agent?.suites ?? []

  const { data: suiteOverview } = useQuery({
    queryKey: ['evaluator-results-overview', 'suite', selectedSuiteId],
    queryFn: () => apiClient.getEvaluatorResultsOverview({ suiteId: selectedSuiteId }),
    enabled: Boolean(selectedSuiteId),
  })

  const { data: aggregate } = useQuery({
    queryKey: ['evaluator-results-aggregate', selectedSuiteId],
    queryFn: () => apiClient.getEvaluatorResultsAggregate({ suiteId: selectedSuiteId }),
    enabled: Boolean(selectedSuiteId) && !selectedScenarioId && !selectedResultId,
  })

  const selectedSuiteFromAgent = suites.find((s) => s.suite_id === selectedSuiteId)
  const suiteDetail = suiteOverview?.agents[0]?.suites?.[0]
  const scenarios: EvaluatorResultsScenarioSummary[] = suiteDetail?.scenarios ?? []

  const selectedScenario = scenarios.find((s) => s.scenario_id === selectedScenarioId)

  useEffect(() => {
    if (loadingAgent || !agentId || !agent || selectedSuiteId) return
    if (suites.length > 0) {
      setSearchParams({ suite: suites[0].suite_id }, { replace: true })
    }
  }, [loadingAgent, agentId, agent, selectedSuiteId, suites, setSearchParams])

  useEffect(() => {
    if (!selectedScenarioId || !selectedSuiteId) return
    if (scenarios.length > 0 && !selectedScenario) {
      const next = new URLSearchParams(searchParams)
      next.delete('scenario')
      setSearchParams(next, { replace: true })
    }
  }, [selectedScenarioId, selectedSuiteId, scenarios, selectedScenario, searchParams, setSearchParams])

  const selectSuite = (suiteId: string) => {
    setSearchParams({ suite: suiteId })
  }

  const selectScenario = (suiteId: string, scenarioId: string) => {
    setSearchParams({ suite: suiteId, scenario: scenarioId })
  }

  const openResult = (resultId: string) => {
    const next = new URLSearchParams(searchParams)
    next.set('result', resultId)
    setSearchParams(next)
  }

  const clearResult = () => {
    const next = new URLSearchParams(searchParams)
    next.delete('result')
    setSearchParams(next)
  }

  const sidebarSuites = useMemo(() => suites, [suites])

  return (
    <div className="space-y-4">
      <ResultsHierarchyNav
        crumbs={[
          { label: 'Evaluation Results', to: '/results' },
          { label: agent?.agent_name ?? 'Agent' },
        ]}
      />

      <div className="flex flex-col lg:flex-row gap-6 min-h-[calc(100vh-12rem)]">
        <aside className="w-full lg:w-72 shrink-0 rounded-xl border border-gray-200 bg-white shadow-sm overflow-hidden">
          <div className="px-4 py-3 border-b border-gray-100 bg-gray-50">
            <h2 className="text-sm font-semibold text-gray-900 truncate">
              {agent?.agent_name ?? 'Agent'}
            </h2>
            {agent && (
              <p className="text-xs text-gray-500 mt-0.5">
                {agent.counts.total} run(s) · {sidebarSuites.length} suite(s)
              </p>
            )}
          </div>
          <nav className="p-2 max-h-[70vh] overflow-y-auto" aria-label="Suites and scenarios">
            {loadingAgent && <p className="px-2 py-4 text-sm text-gray-500">Loading…</p>}
            {!loadingAgent && sidebarSuites.length === 0 && (
              <p className="px-2 py-4 text-sm text-gray-500">No suites with runs.</p>
            )}
            {sidebarSuites.map((suite: EvaluatorResultsSuiteSummary) => {
              const isSuiteActive = suite.suite_id === selectedSuiteId
              const showScenarios = isSuiteActive && scenarios.length > 0
              return (
                <div key={suite.suite_id} className="mb-1">
                  <button
                    type="button"
                    onClick={() => selectSuite(suite.suite_id)}
                    className={`w-full flex items-start gap-2 rounded-lg px-2 py-2 text-left text-sm transition-colors ${
                      isSuiteActive
                        ? 'bg-primary-50 text-primary-900 border border-primary-200'
                        : 'hover:bg-gray-50 text-gray-800'
                    }`}
                  >
                    {isSuiteActive ? (
                      <ChevronDown className="w-4 h-4 mt-0.5 shrink-0 text-primary-600" />
                    ) : (
                      <ChevronRight className="w-4 h-4 mt-0.5 shrink-0 text-gray-400" />
                    )}
                    <FolderKanban className="w-4 h-4 mt-0.5 shrink-0 text-indigo-600" />
                    <span className="min-w-0 flex-1">
                      <span className="font-medium block truncate">
                        {suite.suite_name || 'Evaluator suite'}
                      </span>
                      <span className="text-xs text-gray-500">{suite.counts.total} runs</span>
                    </span>
                  </button>
                  {showScenarios && (
                    <ul className="ml-6 mt-1 space-y-0.5 border-l border-gray-200 pl-2">
                      {scenarios.map((scenario) => {
                        const isScenarioActive = scenario.scenario_id === selectedScenarioId
                        return (
                          <li key={scenario.scenario_id}>
                            <button
                              type="button"
                              onClick={() => selectScenario(suite.suite_id, scenario.scenario_id)}
                              className={`w-full flex items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm ${
                                isScenarioActive
                                  ? 'bg-primary-100 text-primary-900 font-medium'
                                  : 'text-gray-700 hover:bg-gray-50'
                              }`}
                            >
                              <FileText className="w-3.5 h-3.5 shrink-0 text-gray-400" />
                              <span className="truncate flex-1">{scenario.scenario_name}</span>
                              <span className="text-xs text-gray-400 tabular-nums">
                                {scenario.counts.total}
                              </span>
                            </button>
                          </li>
                        )
                      })}
                    </ul>
                  )}
                </div>
              )
            })}
          </nav>
        </aside>

        <main className="flex-1 min-w-0 max-h-[calc(100vh-10rem)] overflow-y-auto">
          {selectedResultId && agentId ? (
            <EvaluatorResultDetailPage
              resultIdOverride={selectedResultId}
              embedded
              onEmbeddedBack={clearResult}
            />
          ) : selectedScenarioId && selectedSuiteId && agentId && selectedScenario ? (
            <ResultsRunsList
              embedded
              title={selectedScenario.scenario_name}
              subtitle={
                selectedSuiteFromAgent?.suite_name
                  ? `Suite: ${selectedSuiteFromAgent.suite_name}`
                  : undefined
              }
              listParams={{
                suiteId: selectedSuiteId,
                scenarioId: selectedScenarioId,
              }}
              counts={selectedScenario.counts}
              onResultClick={openResult}
            />
          ) : selectedSuiteId && selectedSuiteFromAgent ? (
            <div className="space-y-6">
              <div>
                <h1 className="text-2xl font-bold text-gray-900">
                  {selectedSuiteFromAgent.suite_name || 'Evaluator suite'}
                </h1>
                <p className="text-sm text-gray-600 mt-1">
                  Bird&apos;s-eye view — pick a scenario on the left to see individual runs.
                </p>
              </div>
              <ResultsCountCards counts={selectedSuiteFromAgent.counts} />
              {aggregate && aggregate.metrics.length > 0 && (
                <div className="rounded-xl border border-gray-200 bg-white p-4">
                  <h3 className="text-sm font-semibold text-gray-900 mb-3">Quality snapshot</h3>
                  <div className="flex flex-wrap gap-4">
                    {aggregate.metrics.slice(0, 8).map((m) => (
                      <div key={m.metric_id} className="text-sm">
                        <span className="text-gray-500">{m.metric_name}: </span>
                        <span className="font-medium text-gray-900">
                          {m.mean != null ? m.mean.toFixed(2) : m.value_counts[0]?.label ?? '—'}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
              {scenarios.length > 0 && (
                <div className="rounded-xl border border-gray-200 bg-white divide-y divide-gray-100">
                  <div className="px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide">
                    Scenarios in this suite
                  </div>
                  {scenarios.map((scenario) => (
                    <button
                      key={scenario.scenario_id}
                      type="button"
                      onClick={() => selectScenario(selectedSuiteId, scenario.scenario_id)}
                      className="w-full flex items-center justify-between px-4 py-3 text-left hover:bg-gray-50"
                    >
                      <span className="font-medium text-gray-900">{scenario.scenario_name}</span>
                      <span className="text-sm text-gray-500">{scenario.counts.total} run(s)</span>
                    </button>
                  ))}
                </div>
              )}
            </div>
          ) : (
            <div className="rounded-xl border border-dashed border-gray-300 bg-gray-50 p-12 text-center">
              {agent ? (
                <>
                  <ResultsCountCards counts={agent.counts} />
                  <p className="text-sm text-gray-600 mt-6">
                    Select an evaluator suite in the sidebar to explore scenarios and runs.
                  </p>
                </>
              ) : (
                <p className="text-gray-500">Loading agent…</p>
              )}
            </div>
          )}
        </main>
      </div>
    </div>
  )
}
