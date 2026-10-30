import { describe, expect, it } from 'vitest'
import { DEFAULT_LAYOUT, locateWidget, makeWidget } from './dashboardLayout'
import {
  costSummary,
  distinctToolsUsed,
  failureSummary,
  metricTreeValues,
  toolCallTotal,
  toolsOnCall,
} from './dashboardSelectors'
import {
  AGENT_METRICS,
  METRIC_DEPENDENCIES,
  MOCK_INTEGRATIONS,
  MOCK_TOOLS,
  buildScopedMetricTree,
  scenariosForAgent,
  treeReachesNorthStar,
} from './mockCatalog'
import { getMockCorpus } from './mockCalls'
import { USD_TO_INR, convertUsd } from './mockUsage'

describe('dashboard v2 mock corpus', () => {
  const calls = getMockCorpus(Date.parse('2026-10-28T12:00:00.000Z')).filter((call) => {
    const ts = new Date(call.startedAt).getTime()
    return ts >= Date.parse('2026-10-21T00:00:00.000Z')
  })

  it('attaches usage, cost, and multiple tools', () => {
    expect(calls.length).toBeGreaterThan(20)
    expect(calls.every((call) => call.usage && call.usage.costUsd >= 0)).toBe(true)
    expect(costSummary(calls).totalUsd).toBeGreaterThan(0)
    expect(toolCallTotal(calls)).toBeGreaterThan(0)
    expect(distinctToolsUsed(calls)).toBeGreaterThan(3)
    expect(MOCK_TOOLS).toHaveLength(8)
    expect(calls.some((call) => toolsOnCall(call).length === 0)).toBe(true)
    expect(calls.some((call) => toolsOnCall(call).length > 1)).toBe(true)
    expect(MOCK_INTEGRATIONS.length).toBeGreaterThan(3)
    expect(calls.some((call) => toolsOnCall(call).some((tool) => Boolean(tool.integration)))).toBe(true)
  })

  it('keeps scenarios and metrics per agent', () => {
    expect(scenariosForAgent('mock-agent-support-eu').length).toBeGreaterThan(1)
    expect(scenariosForAgent('mock-agent-billing').every((scenario) => scenario.agentId === 'mock-agent-billing')).toBe(
      true,
    )
    expect(AGENT_METRICS['mock-agent-billing']).not.toContain('mock-metric-outcome')
  })

  it('converts USD to INR at the mock rate', () => {
    expect(convertUsd(2, 'INR')).toBe(2 * USD_TO_INR)
  })

  it('has L1/L2/L3 dependencies with values', () => {
    expect(METRIC_DEPENDENCIES.filter((node) => node.level === 1).length).toBe(2)
    expect(METRIC_DEPENDENCIES.filter((node) => node.level === 3).length).toBeGreaterThan(3)
    const values = metricTreeValues(calls)
    expect(values['mock-metric-resolution']?.display).toBeTruthy()
    expect(values['north-star']?.display).toBeTruthy()
    expect(METRIC_DEPENDENCIES.some((node) => node.id === 'north-star' && node.level === 0)).toBe(true)
    expect(failureSummary(calls).toolFailures).toBeGreaterThanOrEqual(0)
  })

  it('scopes the metric tree by agent and scenario, always up to north star', () => {
    const billing = buildScopedMetricTree('mock-agent-billing')
    expect(billing.some((node) => node.id === 'north-star')).toBe(true)
    expect(billing.some((node) => node.id === 'mock-metric-outcome')).toBe(false)
    expect(billing.some((node) => node.id === 'mock-metric-accuracy')).toBe(false)
    expect(billing.some((node) => node.id === 'mock-metric-intent')).toBe(true)
    expect(billing.some((node) => node.kind === 'scenario')).toBe(true)
    expect(treeReachesNorthStar(billing)).toBe(true)

    const refund = buildScopedMetricTree('mock-agent-support-eu', 'mock-scenario-refund')
    const refundIds = refund.map((node) => node.id)
    expect(refundIds).toEqual(expect.arrayContaining(['north-star', 'mock-metric-resolution', 'mock-metric-empathy', 'mock-scenario-refund']))
    expect(refundIds).not.toContain('mock-metric-accuracy')
    expect(treeReachesNorthStar(refund)).toBe(true)
  })
})

describe('dashboard v2 layout', () => {
  it('starts with four top-bar tiles and max-3 rows', () => {
    expect(DEFAULT_LAYOUT.topBar.map((item) => item.type)).toEqual(['cost', 'tool_calls', 'tool_use', 'failures'])
    expect(DEFAULT_LAYOUT.rows.every((row) => row.length <= 3)).toBe(true)
    expect(DEFAULT_LAYOUT.currency).toBe('USD')
    const cost = locateWidget(DEFAULT_LAYOUT, 'cost')
    expect(cost?.zone).toBe('topBar')
    const extra = makeWidget('total_calls')
    expect(extra.id).not.toBe('total_calls')
  })
})
