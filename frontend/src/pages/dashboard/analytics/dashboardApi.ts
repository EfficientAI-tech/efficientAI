import { apiClient } from '../../../lib/api'
import type { ListEvaluatorResultsParams } from '../../../types/api'
import { isMockDataEnabled, useMockDataStore } from './mockMode'
import { aggregateCalls } from './callMetrics'
import { GLOBAL_METRICS, type GlobalMetricId } from './globalMetrics'
import {
  mockAgents,
  mockAggregate,
  mockCallsHubSummary,
  mockClusters,
  mockEvaluatorResults,
  mockFailurePolicies,
  mockOptimizationRuns,
  mockOverview,
  mockSuites,
} from './mockData'
import { getMockCall, listMockCalls, type MockCall } from './mockCalls'
import type { DashboardSource } from './timeBuckets'

/**
 * Thin adapter the dashboard uses instead of calling `apiClient` directly.
 * When sample data is enabled every call resolves from the deterministic
 * mock generator; otherwise it proxies to the real API.
 */
export const dashboardApi = {
  async listAgents() {
    if (isMockDataEnabled()) return mockAgents()
    return apiClient.listAgents()
  },

  async getOverview(params?: { since?: string; until?: string }) {
    if (isMockDataEnabled()) return mockOverview(params)
    return apiClient.getEvaluatorResultsOverview(params)
  },

  async getAggregate(params: {
    agentId?: string
    scenarioId?: string
    suiteId?: string
    since?: string
    until?: string
  }) {
    if (isMockDataEnabled()) return mockAggregate(params)
    return apiClient.getEvaluatorResultsAggregate(params)
  },

  async getFailurePolicies(scope: { agentId: string; since?: string; until?: string }) {
    if (isMockDataEnabled()) return mockFailurePolicies()
    return apiClient.getEvaluatorResultMetricClusterFailurePolicies(scope)
  },

  async getClusters(scope: { agentId: string; since?: string; until?: string }) {
    if (isMockDataEnabled()) return mockClusters(scope.agentId)
    return apiClient.getEvaluatorResultMetricClusters(scope)
  },

  async listResults(params: ListEvaluatorResultsParams) {
    if (isMockDataEnabled()) return mockEvaluatorResults(params)
    return apiClient.listEvaluatorResults(params)
  },

  async listSuites() {
    if (isMockDataEnabled()) return mockSuites()
    return apiClient.listEvaluatorSuites()
  },

  async listOptimizationRuns(agentId?: string) {
    if (isMockDataEnabled()) return mockOptimizationRuns(agentId)
    return apiClient.listOptimizationRuns(agentId)
  },

  async listCallsHub() {
    if (isMockDataEnabled()) return mockCallsHubSummary()
    return apiClient.listCallsHub({ limit: 1 })
  },

  async listCalls(params: {
    agentId?: string | null
    source?: DashboardSource
    since?: string
    until?: string
  }): Promise<{ available: boolean; items: MockCall[] }> {
    if (isMockDataEnabled()) return { available: true, items: listMockCalls(params) }
    return { available: false, items: [] }
  },

  async getCall(id: string): Promise<MockCall | null> {
    if (isMockDataEnabled()) return getMockCall(id) ?? null
    return null
  },

  async getGlobalMetricSeries(params: {
    agentId?: string | null
    source: DashboardSource
    since: string
    until: string
  }): Promise<{
    available: boolean
    current: Record<GlobalMetricId, ReturnType<typeof aggregateCalls>>
  }> {
    if (!isMockDataEnabled()) {
      return { available: false, current: {} as Record<GlobalMetricId, ReturnType<typeof aggregateCalls>> }
    }
    const calls = listMockCalls(params)
    const current = Object.fromEntries(
      GLOBAL_METRICS.map((metric) => [metric.id, aggregateCalls(calls, metric.id, metric.failRule)]),
    ) as Record<GlobalMetricId, ReturnType<typeof aggregateCalls>>
    return { available: true, current }
  },
}

export type DataSourceKey = 'mock' | 'live'

/**
 * Reactive key for react-query so mock and real caches never mix and
 * queries refetch when the user toggles sample data.
 */
export function useDataSourceKey(): DataSourceKey {
  return useMockDataStore((s) => s.enabled) ? 'mock' : 'live'
}
