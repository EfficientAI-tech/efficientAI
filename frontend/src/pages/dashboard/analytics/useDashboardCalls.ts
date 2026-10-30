import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { dashboardApi, useDataSourceKey } from './dashboardApi'
import {
  resolveDashboardWindow,
  type DashboardRange,
  type DashboardSource,
} from './timeBuckets'
import type { MockCall } from './mockCalls'

const EMPTY_CALLS: MockCall[] = []

function inWindow(call: MockCall, since: string, until: string): boolean {
  const ts = new Date(call.startedAt).getTime()
  return ts >= new Date(since).getTime() && ts <= new Date(until).getTime()
}

export function useDashboardCalls(
  range: DashboardRange,
  source: DashboardSource,
  agentId?: string | null,
  extra?: {
    since?: string | null
    until?: string | null
    scenarioId?: string | null
  },
) {
  const window = useMemo(
    () => resolveDashboardWindow(range, extra?.since, extra?.until),
    [extra?.since, extra?.until, range],
  )
  const dataSource = useDataSourceKey()
  const query = useQuery({
    queryKey: [
      'dashboard-calls',
      dataSource,
      source,
      agentId ?? 'all',
      window.previous.since,
      window.current.until,
    ],
    queryFn: () =>
      dashboardApi.listCalls({
        agentId,
        source,
        since: window.previous.since,
        until: window.current.until,
      }),
    staleTime: 5 * 60 * 1000,
  })

  const items = query.data?.items ?? EMPTY_CALLS
  const scoped = useMemo(() => {
    if (!extra?.scenarioId) return items
    return items.filter((call) => call.scenarioId === extra.scenarioId)
  }, [extra?.scenarioId, items])
  const current = useMemo(
    () => scoped.filter((call) => inWindow(call, window.current.since, window.current.until)),
    [scoped, window],
  )
  const previous = useMemo(
    () => scoped.filter((call) => inWindow(call, window.previous.since, window.previous.until)),
    [scoped, window],
  )
  const unfilteredCurrent = useMemo(
    () => items.filter((call) => inWindow(call, window.current.since, window.current.until)),
    [items, window],
  )
  const buckets = useMemo(
    () =>
      window.buckets.map((bucket) => ({
        ...bucket,
        calls: scoped.filter((call) => inWindow(call, bucket.since, bucket.until)),
      })),
    [scoped, window],
  )

  return {
    available: query.data?.available ?? false,
    all: scoped,
    current,
    previous,
    unfilteredCurrent,
    buckets,
    window,
    isLoading: query.isLoading,
  }
}
