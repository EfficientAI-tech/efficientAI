import { createContext, useContext } from 'react'
import type { FailureKind } from './dashboardSection'
import type { MockCall } from './mockCalls'
import type { Currency } from './mockUsage'

export interface DashboardNav {
  calls: MockCall[]
  previousCalls: MockCall[]
  currency: Currency
  setCurrency: (currency: Currency) => void
  source: 'simulation' | 'live'
  openOverview: () => void
  openUsage: () => void
  openModel: (modelId: string) => void
  openToolCalls: () => void
  openTools: () => void
  openTool: (toolName: string) => void
  openFailures: (kind?: FailureKind | null) => void
  openAgent: (agentId: string) => void
  openMetric: (metricId: string, agentId?: string | null) => void
  openMetricCalls: (metricId: string, agentId?: string | null, scenarioId?: string | null) => void
  openCall: (callId: string) => void
  openTree: () => void
}

export const DashboardNavContext = createContext<DashboardNav | null>(null)

export function useDashboardNav(): DashboardNav {
  const value = useContext(DashboardNavContext)
  if (!value) {
    throw new Error('useDashboardNav must be used inside DashboardNavContext')
  }
  return value
}
