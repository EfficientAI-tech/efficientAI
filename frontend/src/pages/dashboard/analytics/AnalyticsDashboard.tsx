import { useMemo } from 'react'
import AgentDashboardSection from './AgentDashboardSection'
import CallDetailDrawer from './CallDetailDrawer'
import DashboardCanvas from './DashboardCanvas'
import DashboardFilterBar from './DashboardFilterBar'
import { DashboardNavContext, type DashboardNav } from './dashboardNav'
import { useDashboardLayout } from './dashboardLayout'
import FailuresSection from './FailuresSection'
import LiveSourceNotice from './LiveSourceNotice'
import MetricAgentCallsPage from './MetricAgentCallsPage'
import MetricPage from './MetricPage'
import MetricTreePage from './MetricTreePage'
import ModelDetailSection from './ModelDetailSection'
import SampleDataBanner from './SampleDataBanner'
import ToolCallsSection from './ToolCallsSection'
import ToolDetailSection from './ToolDetailSection'
import ToolsSection from './ToolsSection'
import UsageSection from './UsageSection'
import { useDashboardCalls } from './useDashboardCalls'
import { useDashboardFilters } from './useDashboardFilters'
import { emptyLiveMetricSeriesSource, useAgentMetricSeries } from './useAgentMetricSeries'
import { useWorkspaceMetricSeries } from './useWorkspaceMetricSeries'

export default function AnalyticsDashboard() {
  const filters = useDashboardFilters()
  const currency = useDashboardLayout((s) => s.currency)
  const setCurrency = useDashboardLayout((s) => s.setCurrency)
  const extraWindow = { since: filters.since, until: filters.until }
  const extraCalls = { ...extraWindow, scenarioId: filters.scenarioId }

  const calls = useDashboardCalls(filters.range, filters.source, null, extraCalls)
  const workspaceSeries = useWorkspaceMetricSeries(filters.range, filters.agentId, extraWindow)
  const agentSeries = useAgentMetricSeries(
    filters.agentId,
    filters.range,
    emptyLiveMetricSeriesSource,
    extraWindow,
  )

  const currentCalls = calls.current
  const previousCalls = calls.previous
  const nav = useMemo<DashboardNav>(
    () => ({
      calls: currentCalls,
      previousCalls,
      currency,
      setCurrency,
      source: filters.source,
      openOverview: () =>
        filters.setParams({
          section: 'overview',
          model: null,
          tool: null,
          fail: null,
          agent: null,
          metric: null,
          call: null,
        }),
      openUsage: () => filters.setParams({ section: 'usage', metric: null, call: null, model: null }),
      openModel: (modelId) => filters.setParams({ section: 'model', model: modelId, metric: null, call: null }),
      openToolCalls: () => filters.setParams({ section: 'tool-calls', metric: null, call: null }),
      openTools: () => filters.setParams({ section: 'tools', metric: null, call: null }),
      openTool: (toolName) => filters.setParams({ section: 'tool', tool: toolName, metric: null, call: null }),
      openFailures: (kind) => filters.setParams({ section: 'failures', fail: kind ?? null, metric: null, call: null }),
      openAgent: (agentId) => filters.setParams({ section: 'agent', agent: agentId, metric: null, call: null }),
      openMetric: (metricId, agentId) =>
        filters.setParams({
          metric: metricId,
          call: null,
          ...(agentId !== undefined ? { agent: agentId } : {}),
        }),
      openMetricCalls: (metricId, agentId, scenarioId) =>
        filters.setParams({
          section: 'tree',
          metric: metricId,
          agent: agentId ?? null,
          scenario: scenarioId ?? null,
          call: null,
        }),
      openCall: (callId) => filters.setParams({ call: callId, metric: filters.metricId ?? 'avg_duration' }),
      openTree: () => filters.setParams({ section: 'tree', metric: null, call: null, model: null, tool: null, fail: null }),
    }),
    [currentCalls, previousCalls, currency, filters, setCurrency],
  )

  const fromTree = filters.section === 'tree'
  const body = filters.metricId && (filters.agentId || fromTree) ? (
    <MetricAgentCallsPage
      metricId={filters.metricId}
      agentId={filters.agentId}
      range={filters.range}
      source={filters.source}
      extra={extraCalls}
      failingOnly={false}
      backLabel={fromTree ? 'Metric tree' : 'Metrics'}
      onBack={() =>
        fromTree
          ? filters.setParams({ metric: null, call: null, section: 'tree' })
          : filters.setParams({ metric: null, agent: 'all', call: null, section: 'overview' })
      }
      onBackMetric={() =>
        fromTree
          ? filters.setParams({ metric: null, call: null, section: 'tree' })
          : filters.setParams({ agent: 'all', call: null })
      }
      onOpenCall={(callId) => filters.setParams({ call: callId })}
    />
  ) : filters.metricId ? (
    <MetricPage
      metricId={filters.metricId}
      agentId={filters.agentId}
      range={filters.range}
      source={filters.source}
      series={workspaceSeries.series ?? agentSeries.series}
      onBack={() => filters.setParams({ metric: null, call: null, label: null, point: null })}
      onOpenAgent={(agentId) => filters.setParams({ agent: agentId, call: null })}
    />
  ) : filters.section === 'usage' ? (
    <UsageSection />
  ) : filters.section === 'model' ? (
    <ModelDetailSection />
  ) : filters.section === 'tool-calls' ? (
    <ToolCallsSection />
  ) : filters.section === 'tools' ? (
    <ToolsSection />
  ) : filters.section === 'tool' ? (
    <ToolDetailSection />
  ) : filters.section === 'failures' ? (
    <FailuresSection />
  ) : filters.section === 'agent' ? (
    <AgentDashboardSection />
  ) : filters.section === 'tree' ? (
    <MetricTreePage />
  ) : (
    <DashboardCanvas />
  )

  return (
    <DashboardNavContext.Provider value={nav}>
      <div className="space-y-5">
        <SampleDataBanner />
        <DashboardFilterBar
          range={filters.range}
          source={filters.source}
          since={filters.since}
          until={filters.until}
          onRange={(range) => filters.setParams({ range })}
          onSource={(source) => filters.setParams({ source })}
          onDates={(since, until) =>
            filters.setParams({
              since: since && until ? since : null,
              until: since && until ? until : null,
              point: null,
            })
          }
        />
        {filters.source === 'live' && <LiveSourceNotice liveCalls={calls.current.length} compact />}
        {body}
        {filters.callId && filters.metricId && (
          <CallDetailDrawer
            callId={filters.callId}
            metricId={filters.metricId}
            onClose={() => filters.openCall(null)}
          />
        )}
      </div>
    </DashboardNavContext.Provider>
  )
}
