import { useMemo, useState } from 'react'
import { useQueries, useQuery } from '@tanstack/react-query'
import type { EvaluatorResultsAgentSummary } from '../../../types/api'
import { buildScoredMetrics } from './buildScoredMetrics'
import { dashboardApi, useDataSourceKey } from './dashboardApi'
import { resolveDashboardWindow, type DashboardRange } from './timeBuckets'
import type { ScoredMetric } from './types'

const INITIAL_AGENT_LIMIT = 8
const STALE_TIME = 5 * 60 * 1000

export interface AgentScorecard {
  agent: EvaluatorResultsAgentSummary
  metrics: ScoredMetric[]
  totalRows: number
  completedRows: number
}

export function useWorkspaceScorecards(
  range: DashboardRange,
  extra?: { since?: string | null; until?: string | null },
) {
  const [showAll, setShowAll] = useState(false)
  const window = useMemo(
    () => resolveDashboardWindow(range, extra?.since, extra?.until),
    [extra?.since, extra?.until, range],
  )
  const source = useDataSourceKey()

  const overviewQuery = useQuery({
    queryKey: ['evaluator-results-overview', source, window.current.since, window.current.until],
    queryFn: () =>
      dashboardApi.getOverview({
        since: window.current.since,
        until: window.current.until,
      }),
    staleTime: STALE_TIME,
  })

  const rankedAgents = useMemo(() => {
    return [...(overviewQuery.data?.agents ?? [])].sort(
      (a, b) => b.counts.total - a.counts.total,
    )
  }, [overviewQuery.data])

  const visibleAgents = showAll ? rankedAgents : rankedAgents.slice(0, INITIAL_AGENT_LIMIT)

  const aggregateQueries = useQueries({
    queries: visibleAgents.flatMap((agent) => [
      {
        queryKey: [
          'dashboard-agg',
          source,
          agent.agent_id,
          'current',
          window.current.since,
          window.current.until,
        ],
        queryFn: () =>
          dashboardApi.getAggregate({
            agentId: agent.agent_id,
            since: window.current.since,
            until: window.current.until,
          }),
        staleTime: STALE_TIME,
      },
      {
        queryKey: [
          'dashboard-agg',
          source,
          agent.agent_id,
          'previous',
          window.previous.since,
          window.previous.until,
        ],
        queryFn: () =>
          dashboardApi.getAggregate({
            agentId: agent.agent_id,
            since: window.previous.since,
            until: window.previous.until,
          }),
        staleTime: STALE_TIME,
      },
    ]),
  })

  const scorecards = useMemo<AgentScorecard[]>(() => {
    return visibleAgents.map((agent, index) => {
      const current = aggregateQueries[index * 2]?.data
      const previous = aggregateQueries[index * 2 + 1]?.data
      return {
        agent,
        metrics: buildScoredMetrics(current, previous, undefined, window.previousRangeLabel),
        totalRows: current?.total_rows ?? agent.counts.total,
        completedRows: current?.completed_rows ?? agent.counts.completed,
      }
    })
  }, [aggregateQueries, visibleAgents, window.previousRangeLabel])

  return {
    overview: overviewQuery.data,
    rankedAgents,
    scorecards,
    window,
    showAll,
    setShowAll,
    canShowMore: rankedAgents.length > INITIAL_AGENT_LIMIT && !showAll,
    isLoading: overviewQuery.isLoading || aggregateQueries.some((query) => query.isLoading),
  }
}
