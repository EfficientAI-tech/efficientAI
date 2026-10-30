import { useMemo } from 'react'
import { useQueries, useQuery } from '@tanstack/react-query'
import type { MetricFailurePolicy } from '../../../types/api'
import { buildScoredMetrics } from './buildScoredMetrics'
import { dashboardApi, useDataSourceKey } from './dashboardApi'
import { resolveDashboardWindow, type DashboardRange } from './timeBuckets'
import type { AgentMetricSeries, LiveMetricSeries } from './types'

export interface LiveMetricSeriesSource {
  useLiveSeries: (agentId: string | null, range: DashboardRange) => LiveMetricSeries
}

export const emptyLiveMetricSeriesSource: LiveMetricSeriesSource = {
  useLiveSeries: (agentId) => ({
    agentId: agentId ?? '',
    pointsByMetric: {},
    available: false,
  }),
}

const STALE_TIME = 5 * 60 * 1000

export function useAgentMetricSeries(
  agentId: string | null,
  range: DashboardRange,
  liveSource: LiveMetricSeriesSource = emptyLiveMetricSeriesSource,
  extra?: { since?: string | null; until?: string | null },
) {
  const window = useMemo(
    () => resolveDashboardWindow(range, extra?.since, extra?.until),
    [extra?.since, extra?.until, range],
  )
  const enabled = Boolean(agentId)
  const source = useDataSourceKey()

  const currentQuery = useQuery({
    queryKey: ['dashboard-agg', source, agentId, 'current', window.current.since, window.current.until],
    queryFn: () =>
      dashboardApi.getAggregate({
        agentId: agentId ?? undefined,
        since: window.current.since,
        until: window.current.until,
      }),
    enabled,
    staleTime: STALE_TIME,
  })

  const previousQuery = useQuery({
    queryKey: ['dashboard-agg', source, agentId, 'previous', window.previous.since, window.previous.until],
    queryFn: () =>
      dashboardApi.getAggregate({
        agentId: agentId ?? undefined,
        since: window.previous.since,
        until: window.previous.until,
      }),
    enabled,
    staleTime: STALE_TIME,
  })

  const policiesQuery = useQuery({
    queryKey: ['dashboard-policies', source, agentId, window.current.since, window.current.until],
    queryFn: () =>
      dashboardApi.getFailurePolicies({
        agentId: agentId as string,
        since: window.current.since,
        until: window.current.until,
      }),
    enabled,
    staleTime: STALE_TIME,
    retry: false,
  })

  const bucketQueries = useQueries({
    queries: window.buckets.map((bucket) => ({
      queryKey: ['dashboard-agg', source, agentId, 'bucket', bucket.since, bucket.until],
      queryFn: () =>
        dashboardApi.getAggregate({
          agentId: agentId ?? undefined,
          since: bucket.since,
          until: bucket.until,
        }),
      enabled,
      staleTime: STALE_TIME,
    })),
  })

  const live = liveSource.useLiveSeries(agentId, range)

  const policies = useMemo(() => {
    const map: Record<string, MetricFailurePolicy> = {}
    for (const [metricId, policy] of Object.entries(policiesQuery.data?.policies ?? {})) {
      map[metricId] = policy
    }
    return map
  }, [policiesQuery.data])

  const series = useMemo<AgentMetricSeries | null>(() => {
    if (!agentId || !currentQuery.data) return null
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
        return {
          label: bucket.label,
          value,
          count: bucketAgg?.count ?? 0,
        }
      })
    }
    return {
      agentId,
      current: window.current,
      previous: window.previous,
      buckets: window.buckets,
      metrics,
      totalRows: currentQuery.data.total_rows,
      completedRows: currentQuery.data.completed_rows,
      failedRows: currentQuery.data.failed_rows,
      pointsByMetric,
    }
  }, [
    agentId,
    bucketQueries,
    currentQuery.data,
    policies,
    previousQuery.data,
    window,
  ])

  const isLoading =
    enabled &&
    (currentQuery.isLoading ||
      previousQuery.isLoading ||
      bucketQueries.some((query) => query.isLoading))

  return {
    series,
    live,
    window,
    policies,
    isLoading,
    isError: currentQuery.isError,
  }
}
