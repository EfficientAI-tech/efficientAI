import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { Link, useNavigate, useSearchParams } from 'react-router-dom'

import { keepPreviousData, useQuery, useQueryClient } from '@tanstack/react-query'

import { apiClient } from '../../../lib/api'

import { useLicenseStore } from '../../../store/licenseStore'

import { useWorkspaceStore } from '../../../store/workspaceStore'

import ResultsHierarchyNav from './ResultsHierarchyNav'

import ResultsRunsList from './ResultsRunsList'

import ResultsDrillPath, { type ResultsDrillCrumb } from './ResultsDrillPath'

import ResultsDateRangePicker from './ResultsDateRangePicker'

import MetricClustersPanel from '../../../components/metricClusters/MetricClustersPanel'

import ClusterScopeHistory from '../../../components/metricClusters/ClusterScopeHistory'

import type { ClusterReportView } from '../../../components/metricClusters/types'

import { generationScopeToClusterScope, clusterScopesMatch } from '../../../components/metricClusters/clusterScopeUtils'

import {

  createEvaluatorResultsMetricClustersClient,

  type EvaluatorResultClusterScope,

} from '../../../components/metricClusters/clients'

import { dateRangeToSinceUntil, isoToDateInput } from './resultsDateRange'

import type {
  EvaluatorResultsScenarioSummary,
  EvaluatorResultsSuiteSummary,
  ListEvaluatorResultsParams,
} from '../../../types/api'



type HubTab = 'runs' | 'clusters'

type StatusFilter = 'all' | 'completed' | 'failed' | 'in_progress'



const STATUS_FILTERS = new Set<StatusFilter>(['all', 'completed', 'failed', 'in_progress'])



export default function ResultsHub() {

  const navigate = useNavigate()

  const queryClient = useQueryClient()

  const [searchParams, setSearchParams] = useSearchParams()

  const activeWorkspaceId = useWorkspaceStore((s) => s.activeWorkspaceId)

  const { isFeatureEnabled, isLoaded: licenseLoaded } = useLicenseStore()

  const openGenerateModalRef = useRef<(() => void) | null>(null)

  const [generateModalOpen, setGenerateModalOpen] = useState(false)



  const agentId = searchParams.get('agent') ?? ''

  const suiteId = searchParams.get('suite') ?? ''

  const scenarioId = searchParams.get('scenario') ?? ''

  const startDate = searchParams.get('start')

  const endDate = searchParams.get('end')

  const clusterAgentId = searchParams.get('cluster_agent') ?? ''

  const clusterScenariosRaw = searchParams.get('cluster_scenarios')

  const clusterStart = searchParams.get('cluster_start')

  const clusterEnd = searchParams.get('cluster_end')

  const clusterJobId = searchParams.get('cluster_job_id') ?? ''

  const legacyClusterScopeKey = searchParams.get('cluster_scope_key') ?? ''

  const clusterViewParam = searchParams.get('cluster_view')

  const clusterView: ClusterReportView =
    clusterViewParam === 'visualization' ? 'visualization' : 'details'

  const statusParam = searchParams.get('status')

  const statusFilter: StatusFilter =

    statusParam && STATUS_FILTERS.has(statusParam as StatusFilter)

      ? (statusParam as StatusFilter)

      : 'all'

  const tabParam = searchParams.get('tab')

  const activeTab: HubTab =

    tabParam === 'clusters' && isFeatureEnabled('evaluation_clustering') ? 'clusters' : 'runs'



  const dateBounds = useMemo(() => {

    if (!startDate || !endDate) return undefined

    return dateRangeToSinceUntil(startDate, endDate)

  }, [startDate, endDate])



  const overviewParams = useMemo(

    () => ({

      ...(dateBounds ? { since: dateBounds.since, until: dateBounds.until } : {}),

    }),

    [dateBounds],

  )



  const { data: overview, isLoading: loadingOverview } = useQuery({

    queryKey: ['evaluator-results-overview', activeWorkspaceId, overviewParams],

    queryFn: () => apiClient.getEvaluatorResultsOverview(overviewParams),

    enabled: activeTab === 'runs' || generateModalOpen,

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



  const listParams = useMemo((): Omit<ListEvaluatorResultsParams, 'skip' | 'limit' | 'status'> => {

    const params: Omit<ListEvaluatorResultsParams, 'skip' | 'limit' | 'status'> = {}

    if (agentId) params.agentId = agentId

    if (suiteId) params.suiteId = suiteId

    if (scenarioId) params.scenarioId = scenarioId

    if (dateBounds) {

      params.since = dateBounds.since

      params.until = dateBounds.until

    }

    return params

  }, [agentId, suiteId, scenarioId, dateBounds])



  const showAggregate =

    Boolean(suiteId) || (Boolean(agentId) && Boolean(scenarioId))



  const { data: aggregate } = useQuery({

    queryKey: ['evaluator-results-aggregate', listParams],

    queryFn: () =>

      apiClient.getEvaluatorResultsAggregate({

        suiteId: suiteId || undefined,

        agentId: agentId || undefined,

        scenarioId: scenarioId || undefined,

        since: dateBounds?.since,

        until: dateBounds?.until,

      }),

    enabled: showAggregate,

  })



  const clusterScenarioIds = useMemo(

    () => (clusterScenariosRaw ? clusterScenariosRaw.split(',').filter(Boolean) : []),

    [clusterScenariosRaw],

  )



  const clusterScope = useMemo((): EvaluatorResultClusterScope | null => {

    if (!clusterAgentId) return null

    const scope: EvaluatorResultClusterScope = { agentId: clusterAgentId }

    if (clusterJobId) scope.jobId = clusterJobId

    if (clusterScenarioIds.length) scope.scenarioIds = clusterScenarioIds

    if (clusterStart && clusterEnd) {

      const bounds = dateRangeToSinceUntil(clusterStart, clusterEnd)

      scope.since = bounds.since

      scope.until = bounds.until

    }

    return scope

  }, [clusterAgentId, clusterEnd, clusterJobId, clusterScenarioIds, clusterStart])



  const clusterClient = useMemo(

    () =>

      createEvaluatorResultsMetricClustersClient(

        clusterScope ?? { agentId: clusterAgentId || 'pending' },

        activeWorkspaceId,

      ),

    [activeWorkspaceId, clusterAgentId, clusterScope],

  )



  const clustersEnabled = licenseLoaded && isFeatureEnabled('evaluation_clustering')



  const clusterScopesQuery = useQuery({

    queryKey: ['evaluator-results-metric-cluster-scopes', activeWorkspaceId],

    queryFn: () => apiClient.listEvaluatorResultMetricClusterScopes(),

    enabled: activeTab === 'clusters' && clustersEnabled,

    staleTime: 60_000,

    refetchInterval: (query) => {

      const hasRunning = query.state.data?.items.some((item) => item.status === 'running')

      return hasRunning ? 5000 : false

    },

  })



  const metricClustersQuery = useQuery({

    queryKey: clusterClient.queryKeyPrefix,

    queryFn: () => apiClient.getEvaluatorResultMetricClusters(clusterScope!),

    enabled:

      activeTab === 'clusters' &&

      clusterScope !== null &&

      clustersEnabled,

    staleTime: 60_000,

    placeholderData: keepPreviousData,

    refetchInterval: (query) => {

      const status = query.state.data?.status

      return status === 'running' ? 3000 : false

    },

  })



  const setParams = (updates: Record<string, string | null>) => {

    const next = new URLSearchParams(searchParams)

    for (const [key, value] of Object.entries(updates)) {

      if (!value) next.delete(key)

      else next.set(key, value)

    }

    setSearchParams(next)

  }



  const commitClusterScope = useCallback((scope: EvaluatorResultClusterScope) => {
    setSearchParams((current) => {
      const next = new URLSearchParams(current)
      next.set('cluster_agent', scope.agentId)
      if (scope.jobId) {
        next.set('cluster_job_id', scope.jobId)
      } else {
        next.delete('cluster_job_id')
      }
      next.delete('cluster_scope_key')
      if (scope.scenarioIds?.length) {
        next.set('cluster_scenarios', scope.scenarioIds.join(','))
      } else {
        next.delete('cluster_scenarios')
      }
      if (scope.since && scope.until) {
        next.set('cluster_start', isoToDateInput(scope.since))
        next.set('cluster_end', isoToDateInput(scope.until))
      } else {
        next.delete('cluster_start')
        next.delete('cluster_end')
      }
      return next
    })
  }, [setSearchParams])

  const setClusterView = useCallback(
    (view: ClusterReportView) => {
      setSearchParams((current) => {
        const next = new URLSearchParams(current)
        if (view === 'details') next.delete('cluster_view')
        else next.set('cluster_view', view)
        return next
      })
    },
    [setSearchParams],
  )



  useEffect(() => {

    if (

      activeTab !== 'clusters' ||

      clusterJobId ||

      !legacyClusterScopeKey ||

      !clusterScopesQuery.data?.items.length

    ) {

      return

    }

    const match = clusterScopesQuery.data.items.find(

      (item) => item.scope_key === legacyClusterScopeKey,

    )

    if (!match) return

    commitClusterScope(

      generationScopeToClusterScope(match.generation_scope, match.job_id),

    )

  }, [

    activeTab,

    clusterJobId,

    legacyClusterScopeKey,

    clusterScopesQuery.data,

    commitClusterScope,

  ])



  useEffect(() => {

    if (activeTab !== 'clusters' || clusterAgentId || !clusterScopesQuery.data?.items.length) {

      return

    }

    const items = clusterScopesQuery.data.items

    const pick =

      items.find((item) => item.status === 'completed' && item.has_results) ??

      items.find((item) => item.status === 'running') ??

      items[0]

    if (!pick) return

    commitClusterScope(
      generationScopeToClusterScope(pick.generation_scope, pick.job_id),
    )

  }, [

    activeTab,

    clusterAgentId,

    clusterScopesQuery.data,

    commitClusterScope,

  ])



  useEffect(() => {

    if (

      activeTab !== 'clusters' ||

      clusterJobId ||

      !clusterScope ||

      !clusterScopesQuery.data?.items.length

    ) {

      return

    }

    const match = clusterScopesQuery.data.items.find((item) =>

      clusterScopesMatch(

        clusterScope,

        generationScopeToClusterScope(item.generation_scope, item.job_id),

      ),

    )

    if (!match) return

    commitClusterScope(

      generationScopeToClusterScope(match.generation_scope, match.job_id),

    )

  }, [

    activeTab,

    clusterScope,

    clusterJobId,

    clusterScopesQuery.data,

    commitClusterScope,

  ])



  const setFilter = (key: 'agent' | 'suite' | 'scenario', value: string) => {

    if (key === 'agent') {

      setParams({

        agent: value || null,

        suite: null,

        scenario: null,

      })

      return

    }

    if (key === 'suite') {

      setParams({

        suite: value || null,

        scenario: null,

      })

      return

    }

    setParams({ scenario: value || null })

  }



  const setDateRange = (start: string | null, end: string | null) => {

    setParams({

      start,

      end,

    })

  }



  const setStatusFilter = (status: StatusFilter) => {

    setParams({ status: status === 'all' ? null : status })

  }



  const setTab = (tab: HubTab) => {

    setParams({ tab: tab === 'clusters' ? 'clusters' : null })

  }



  const selectedAgent = agents.find((agent) => agent.agent_id === agentId)

  const selectedSuite = suiteOptions.find((suite) => suite.suite_id === suiteId)

  const selectedScenario = scenarioOptions.find((scenario) => scenario.scenario_id === scenarioId)



  const drillCrumbs = useMemo((): ResultsDrillCrumb[] => {

    const crumbs: ResultsDrillCrumb[] = [

      {

        label: 'All results',

        onClick: agentId || suiteId || scenarioId

          ? () => setParams({ agent: null, suite: null, scenario: null })

          : undefined,

      },

    ]

    if (selectedAgent) {

      crumbs.push({

        label: selectedAgent.agent_name,

        onClick: suiteId || scenarioId

          ? () => setParams({ agent: agentId, suite: null, scenario: null })

          : undefined,

      })

    }

    if (selectedSuite) {

      crumbs.push({

        label: selectedSuite.suite_name || 'Evaluator suite',

        onClick: scenarioId

          ? () => setParams({ agent: agentId, suite: suiteId, scenario: null })

          : undefined,

      })

    }

    if (selectedScenario) {

      crumbs.push({

        label: selectedScenario.scenario_name,

      })

    }

    return crumbs

  }, [agentId, scenarioId, selectedAgent, selectedScenario, selectedSuite, suiteId])



  const drillLevelLabel = selectedScenario

    ? 'Scenario runs'

    : selectedSuite

      ? 'Suite runs'

      : selectedAgent

        ? 'Agent runs'

        : 'Workspace runs'



  const invalidateClusterScopes = () => {

    void queryClient.invalidateQueries({

      queryKey: ['evaluator-results-metric-cluster-scopes', activeWorkspaceId],

    })

  }



  return (

    <div className="space-y-6">

      <ResultsHierarchyNav crumbs={[{ label: 'Evaluation Results' }]} />



      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">

        <div>

          <h1 className="text-3xl font-bold text-gray-900">Evaluation Results</h1>

          <p className="mt-2 text-sm text-gray-600">

            Drill down by agent, suite, scenario, and when the call happened

          </p>

        </div>

        <Link

          to="/results/unassigned"

          className="text-sm font-medium text-primary-600 hover:text-primary-800 shrink-0"

        >

          Unassigned runs

        </Link>

      </div>



      {activeTab === 'runs' && (loadingOverview || !overview) ? (

        <p className="text-gray-500">Loading overview…</p>

      ) : overview && overview.unassigned.counts.total > 0 ? (

          <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">

            {overview.unassigned.counts.total} run(s) are not linked to an evaluator suite.{' '}

            <Link to="/results/unassigned" className="font-semibold underline">

              View unassigned

            </Link>

          </div>

      ) : null}



      {activeTab === 'runs' ? (

        <div className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm space-y-4">

          <ResultsDateRangePicker

            start={startDate}

            end={endDate}

            onApply={setDateRange}

          />



          <ResultsDrillPath crumbs={drillCrumbs} levelLabel={drillLevelLabel} />



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

      ) : null}



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

            statusFilter={statusFilter}

            onStatusFilterChange={setStatusFilter}

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

        <div className="space-y-4">

          <ClusterScopeHistory

            items={clusterScopesQuery.data?.items ?? []}

            activeScope={clusterScope}

            isLoading={clusterScopesQuery.isLoading}

            onSelectScope={(scope) => commitClusterScope(scope)}

            onDeleteScope={async (scope) => {
              await apiClient.deleteEvaluatorResultMetricClusters(scope)
              invalidateClusterScopes()
              queryClient.removeQueries({ queryKey: clusterClient.queryKeyPrefix })
              if (clusterScope?.jobId && clusterScope.jobId === scope.jobId) {
                setSearchParams((current) => {
                  const next = new URLSearchParams(current)
                  next.delete('cluster_agent')
                  next.delete('cluster_job_id')
                  next.delete('cluster_scope_key')
                  next.delete('cluster_scenarios')
                  next.delete('cluster_start')
                  next.delete('cluster_end')
                  return next
                })
              }
            }}

            onCreateNew={() => openGenerateModalRef.current?.()}
          />

          <MetricClustersPanel

            client={clusterClient}

            state={metricClustersQuery.data ?? null}

            isLoading={
              clusterScope !== null &&
              (metricClustersQuery.isLoading ||
                (metricClustersQuery.isFetching &&
                  !metricClustersQuery.isPlaceholderData))
            }

            activeView={clusterView}

            onViewChange={setClusterView}

            onGenerateModalOpenChange={setGenerateModalOpen}

            registerOpenGenerateModal={(open) => {

              openGenerateModalRef.current = open

            }}

            onGenerated={(nextState, scope) => {

              if (nextState && scope) {

                const seededClient = createEvaluatorResultsMetricClustersClient(

                  scope,

                  activeWorkspaceId,

                )

                queryClient.setQueryData(seededClient.queryKeyPrefix, nextState)

                commitClusterScope(scope)

              } else if (nextState && clusterScope) {

                queryClient.setQueryData(clusterClient.queryKeyPrefix, nextState)

              }

              invalidateClusterScopes()

              void metricClustersQuery.refetch()

            }}

            evaluatorScope={{

              agents,

              scope: clusterScope,

              onScopeCommit: commitClusterScope,

            }}

          />

        </div>

      ) : null}

    </div>

  )

}

