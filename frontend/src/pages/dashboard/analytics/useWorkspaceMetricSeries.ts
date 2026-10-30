import { useMemo } from 'react'
import { useQueries, useQuery } from '@tanstack/react-query'
import { buildScoredMetrics } from './buildScoredMetrics'
import { dashboardApi, useDataSourceKey } from './dashboardApi'
import { resolveDashboardWindow, type DashboardRange } from './timeBuckets'
import type { AgentMetricSeries } from './types'

const STALE_TIME = 5 * 60 * 1000

export function useWorkspaceMetricSeries(
  range: DashboardRange,
  agentId?: string | null,
  extra?: { since?: string | null; until?: string | null },
) {
  const window = useMemo(
    () => resolveDashboardWindow(range, extra?.since, extra?.until),
    [extra?.since, extra?.until, range],
  )
  const source = useDataSourceKey()

  const currentQuery = useQuery({
    queryKey: ['dashboard-agg', source, agentId ?? 'workspace', 'current', window.current.since, window.current.until],
    queryFn: () =>
      dashboardApi.getAggregate({
        agentId: agentId ?? undefined,
        since: window.current.since,
        until: window.current.until,
      }),
    staleTime: STALE_TIME,
  })
  const previousQuery = useQuery({
    queryKey: ['dashboard-agg', source, agentId ?? 'workspace', 'previous', window.previous.since, window.previous.until],
    queryFn: () =>
      dashboardApi.getAggregate({
        agentId: agentId ?? undefined,
        since: window.previous.since,
        until: window.previous.until,
      }),
    staleTime: STALE_TIME,
  })
  const policiesQuery = useQuery({
    queryKey: ['dashboard-policies', source, agentId ?? 'workspace', window.current.since],
    queryFn: () =>
      dashboardApi.getFailurePolicies({
        agentId: agentId ?? 'workspace',
        since: window.current.since,
        until: window.current.until,
      }),
    staleTime: STALE_TIME,
    retry: false,
  })
  const bucketQueries = useQueries({
    queries: window.buckets.map((bucket) => ({
      queryKey: ['dashboard-agg', source, agentId ?? 'workspace', 'bucket', bucket.since, bucket.until],
      queryFn: () =>
        dashboardApi.getAggregate({
          agentId: agentId ?? undefined,
          since: bucket.since,
          until: bucket.until,
        }),
      staleTime: STALE_TIME,
    })),
  })

  const series = useMemo<AgentMetricSeries | null>(() => {
    if (!currentQuery.data) return null
    const policies = policiesQuery.data?.policies ?? {}
    const metrics = buildScoredMetrics(
      currentQuery.data,
      previousQuery.data,
      policies,
      window.previousRangeLabel,
    )
    const pointsByMetric: AgentMetricSeries['pointsByMetric'] = {}
    for (const metric of metrics) {
      pointsByMetric[metric.agg.metric_id] = window.buckets.map((bucket, index) => {
        const bucketAgg = bucketQueries[index]?.data?.metrics.find(
          (item) => item.metric_id === metric.agg.metric_id,
        )
        const value = bucketAgg
          ? buildScoredMetrics(
              { ...currentQuery.data, metrics: [bucketAgg] },
              undefined,
              policies,
              window.previousRangeLabel,
            )[0]?.score.value ?? null
          : null
        return { label: bucket.label, value, count: bucketAgg?.count ?? 0 }
      })
    }
    return {
      agentId: agentId ?? 'workspace',
      current: window.current,
      previous: window.previous,
      buckets: window.buckets,
      metrics,
      totalRows: currentQuery.data.total_rows,
      completedRows: currentQuery.data.completed_rows,
      failedRows: currentQuery.data.failed_rows,
      pointsByMetric,
    }
  }, [agentId, bucketQueries, currentQuery.data, policiesQuery.data, previousQuery.data, window])

  return {
    series,
    window,
    isLoading: currentQuery.isLoading || bucketQueries.some((query) => query.isLoading),
  }
}
