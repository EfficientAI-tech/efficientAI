import { useEffect, useMemo } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { apiClient } from '../../../lib/api'
import { useLicenseStore } from '../../../store/licenseStore'
import { useWorkspaceStore } from '../../../store/workspaceStore'
import ResultsHierarchyNav from './ResultsHierarchyNav'
import ResultsCountCards from './ResultsCountCards'
import ResultsRunsList from './ResultsRunsList'
import MetricClustersPanel from '../../../components/metricClusters/MetricClustersPanel'
import { createEvaluatorResultsMetricClustersClient } from '../../../components/metricClusters/clients'
import type {
  EvaluatorResultsAgentSummary,
  EvaluatorResultsScenarioSummary,
  EvaluatorResultsSuiteSummary,
} from '../../../types/api'

type HubTab = 'runs' | 'clusters'

function filterCountsForScope(
  overview: {
    workspace_counts: {
      total: number
      completed: number
      failed: number
      in_progress: number
      last_run_at?: string | null
    }
  },
  agentId: string,
  suiteId: string,
  scenarioId: string,
  agents: EvaluatorResultsAgentSummary[],
) {
  if (scenarioId) {
    for (const agent of agents) {
      if (agent.agent_id !== agentId) continue
      for (const suite of agent.suites ?? []) {
        if (suite.suite_id !== suiteId) continue
        const scenario = suite.scenarios?.find((s) => s.scenario_id === scenarioId)
        if (scenario) return scenario.counts
      }
    }
  }
  if (suiteId) {
    for (const agent of agents) {
      if (agent.agent_id !== agentId) continue
      const suite = agent.suites?.find((s) => s.suite_id === suiteId)
      if (suite) return suite.counts
    }
  }
  if (agentId) {
    const agent = agents.find((a) => a.agent_id === agentId)
    if (agent) return agent.counts
  }
  return overview.workspace_counts
}

export default function ResultsHub() {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const activeWorkspaceId = useWorkspaceStore((s) => s.activeWorkspaceId)
  const { isFeatureEnabled, isLoaded: licenseLoaded } = useLicenseStore()

  const agentId = searchParams.get('agent') ?? ''
  const suiteId = searchParams.get('suite') ?? ''
  const scenarioId = searchParams.get('scenario') ?? ''
  const tabParam = searchParams.get('tab')
  const activeTab: HubTab =
    tabParam === 'clusters' && isFeatureEnabled('evaluation_clustering') ? 'clusters' : 'runs'

  const { data: overview, isLoading: loadingOverview } = useQuery({
    queryKey: ['evaluator-results-overview', activeWorkspaceId],
    queryFn: () => apiClient.getEvaluatorResultsOverview(),
  })

  const agents = overview?.agents ?? []

  const suiteOptions = useMemo(() => {
    const out: EvaluatorResultsSuiteSummary[] = []
    for (const agent of agents) {
      if (agentId && agent.agent_id !== agentId) continue
      for (const suite of agent.suites ?? []) {
        out.push(suite)
      }
    }
    return out.sort((a, b) => (a.suite_name || '').localeCompare(b.suite_name || ''))
  }, [agents, agentId])

  const scenarioOptions = useMemo(() => {
    if (!suiteId) return [] as EvaluatorResultsScenarioSummary[]
    const suite = suiteOptions.find((s) => s.suite_id === suiteId)
    return suite?.scenarios ?? []
  }, [suiteOptions, suiteId])

  useEffect(() => {
    if (!suiteId || !scenarioId || scenarioOptions.length === 0) return
    if (!scenarioOptions.some((s) => s.scenario_id === scenarioId)) {
      const next = new URLSearchParams(searchParams)
      next.delete('scenario')
      setSearchParams(next, { replace: true })
    }
  }, [suiteId, scenarioId, scenarioOptions, searchParams, setSearchParams])

  useEffect(() => {
    if (!agentId || !suiteId || suiteOptions.length === 0) return
    if (!suiteOptions.some((s) => s.suite_id === suiteId)) {
      const next = new URLSearchParams(searchParams)
      next.delete('suite')
      next.delete('scenario')
      setSearchParams(next, { replace: true })
    }
  }, [agentId, suiteId, suiteOptions, searchParams, setSearchParams])

  const listParams = useMemo(
    () => ({
      ...(agentId ? { agentId } : {}),
      ...(suiteId ? { suiteId } : {}),
      ...(scenarioId ? { scenarioId } : {}),
    }),
    [agentId, suiteId, scenarioId],
  )

  const counts = overview
    ? filterCountsForScope(overview, agentId, suiteId, scenarioId, agents)
    : undefined

  const showAggregate =
    Boolean(suiteId) || (Boolean(agentId) && Boolean(scenarioId))

  const { data: aggregate } = useQuery({
    queryKey: ['evaluator-results-aggregate', listParams],
    queryFn: () =>
      apiClient.getEvaluatorResultsAggregate({
        suiteId: suiteId || undefined,
        agentId: agentId || undefined,
        scenarioId: scenarioId || undefined,
      }),
    enabled: showAggregate,
  })

  const clusterScope = useMemo(
    () => ({
      agentId: agentId || undefined,
      suiteId: suiteId || undefined,
      scenarioId: scenarioId || undefined,
    }),
    [agentId, suiteId, scenarioId],
  )

  const clusterClient = useMemo(
    () => createEvaluatorResultsMetricClustersClient(clusterScope, activeWorkspaceId),
    [clusterScope, activeWorkspaceId],
  )

  const metricClustersQuery = useQuery({
    queryKey: clusterClient.queryKeyPrefix,
    queryFn: () => apiClient.getEvaluatorResultMetricClusters(clusterScope),
    enabled: activeTab === 'clusters' && licenseLoaded && isFeatureEnabled('evaluation_clustering'),
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status === 'running' ? 3000 : false
    },
  })

  const setFilter = (key: 'agent' | 'suite' | 'scenario', value: string) => {
    const next = new URLSearchParams(searchParams)
    if (key === 'agent') {
      if (value) next.set('agent', value)
      else next.delete('agent')
      next.delete('suite')
      next.delete('scenario')
    } else if (key === 'suite') {
      if (value) next.set('suite', value)
      else next.delete('suite')
      next.delete('scenario')
    } else {
      if (value) next.set('scenario', value)
      else next.delete('scenario')
    }
    setSearchParams(next)
  }

  const setTab = (tab: HubTab) => {
    const next = new URLSearchParams(searchParams)
    if (tab === 'clusters') next.set('tab', 'clusters')
    else next.delete('tab')
    setSearchParams(next)
  }

  const clustersEnabled = licenseLoaded && isFeatureEnabled('evaluation_clustering')

  return (
    <div className="space-y-6">
      <ResultsHierarchyNav crumbs={[{ label: 'Evaluation Results' }]} />

      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">Evaluation Results</h1>
          <p className="mt-2 text-sm text-gray-600">
            All runs newest first — filter by agent, suite, and scenario
          </p>
        </div>
        <Link
          to="/results/unassigned"
          className="text-sm font-medium text-primary-600 hover:text-primary-800 shrink-0"
        >
          Unassigned runs
        </Link>
      </div>

      <div className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm">
        <div className="grid gap-4 md:grid-cols-3">
          <label className="block text-sm">
            <span className="text-xs font-medium text-gray-500 uppercase tracking-wide">Agent</span>
            <select
              className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
              value={agentId}
              onChange={(e) => setFilter('agent', e.target.value)}
            >
              <option value="">All agents</option>
              {agents.map((agent) => (
                <option key={agent.agent_id} value={agent.agent_id}>
                  {agent.agent_name} ({agent.counts.total})
                </option>
              ))}
            </select>
          </label>
          <label className="block text-sm">
            <span className="text-xs font-medium text-gray-500 uppercase tracking-wide">Suite</span>
            <select
              className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm disabled:bg-gray-50"
              value={suiteId}
              onChange={(e) => setFilter('suite', e.target.value)}
              disabled={suiteOptions.length === 0}
            >
              <option value="">All suites</option>
              {suiteOptions.map((suite) => (
                <option key={suite.suite_id} value={suite.suite_id}>
                  {suite.suite_name || 'Evaluator suite'} ({suite.counts.total})
                </option>
              ))}
            </select>
          </label>
          <label className="block text-sm">
            <span className="text-xs font-medium text-gray-500 uppercase tracking-wide">Scenario</span>
            <select
              className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm disabled:bg-gray-50"
              value={scenarioId}
              onChange={(e) => setFilter('scenario', e.target.value)}
              disabled={!suiteId || scenarioOptions.length === 0}
            >
              <option value="">All scenarios</option>
              {scenarioOptions.map((scenario) => (
                <option key={scenario.scenario_id} value={scenario.scenario_id}>
                  {scenario.scenario_name} ({scenario.counts.total})
                </option>
              ))}
            </select>
          </label>
        </div>
      </div>

      {loadingOverview || !overview ? (
        <p className="text-gray-500">Loading overview…</p>
      ) : (
        <>
          <ResultsCountCards counts={counts ?? overview.workspace_counts} />
          {overview.unassigned.counts.total > 0 && (
            <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
              {overview.unassigned.counts.total} run(s) are not linked to an evaluator suite.{' '}
              <Link to="/results/unassigned" className="font-semibold underline">
                View unassigned
              </Link>
            </div>
          )}
        </>
      )}

      <div className="flex gap-1 border-b border-gray-200">
        <button
          type="button"
          onClick={() => setTab('runs')}
          className={`px-4 py-2 text-sm font-medium border-b-2 -mb-px ${
            activeTab === 'runs'
              ? 'border-primary-600 text-primary-700'
              : 'border-transparent text-gray-600 hover:text-gray-900'
          }`}
        >
          Runs
        </button>
        {clustersEnabled && (
          <button
            type="button"
            onClick={() => setTab('clusters')}
            className={`px-4 py-2 text-sm font-medium border-b-2 -mb-px ${
              activeTab === 'clusters'
                ? 'border-primary-600 text-primary-700'
                : 'border-transparent text-gray-600 hover:text-gray-900'
            }`}
          >
            Clusters
          </button>
        )}
      </div>

      {activeTab === 'runs' ? (
        <div className="space-y-6">
          {showAggregate && aggregate && aggregate.metrics.length > 0 && (
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
          <ResultsRunsList
            embedded
            title="Evaluation runs"
            subtitle="Newest first across the current filter"
            listParams={listParams}
            showAgentColumn={!agentId}
            showPersonaColumn={Boolean(suiteId || scenarioId)}
            showScenarioColumn={!scenarioId}
            onResultClick={(resultId) => {
              const qs = searchParams.toString()
              navigate(`/results/${resultId}${qs ? `?from=${encodeURIComponent(`/results?${qs}`)}` : ''}`)
            }}
          />
        </div>
      ) : clustersEnabled ? (
        <MetricClustersPanel
          client={clusterClient}
          state={metricClustersQuery.data ?? null}
          isLoading={metricClustersQuery.isLoading}
          onGenerated={() => metricClustersQuery.refetch()}
        />
      ) : null}
    </div>
  )
}
