import type { MetricFailurePolicy } from '../../../types/api'

export function hashString(value: string): number {
  let h = 1779033703 ^ value.length
  for (let i = 0; i < value.length; i += 1) {
    h = Math.imul(h ^ value.charCodeAt(i), 3432918353)
    h = (h << 13) | (h >>> 19)
  }
  return h >>> 0
}

export function mulberry32(seed: number): () => number {
  let a = seed >>> 0
  return () => {
    a = (a + 0x6d2b79f5) >>> 0
    let t = a
    t = Math.imul(t ^ (t >>> 15), t | 1)
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

export function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value))
}

export interface MockAgentDef {
  id: string
  name: string
  runsPerDay: number
  phone: string
  language: string
}

export const MOCK_AGENTS: MockAgentDef[] = [
  { id: 'mock-agent-support-eu', name: 'Support-EU', runsPerDay: 9, phone: '+44 20 7946 0101', language: 'en-GB' },
  { id: 'mock-agent-sales-outbound', name: 'Sales Outbound', runsPerDay: 6, phone: '+1 415 555 0142', language: 'en-US' },
  { id: 'mock-agent-billing', name: 'Billing Assistant', runsPerDay: 3, phone: '+91 80 4567 1200', language: 'en-IN' },
]

export type MockMetricKind = 'rating' | 'boolean' | 'number' | 'category'

export interface MockMetricDef {
  id: string
  name: string
  kind: MockMetricKind
  category: 'quality' | 'user_insight'
  labels?: string[]
  policy?: MetricFailurePolicy
}

export const MOCK_METRICS: MockMetricDef[] = [
  { id: 'mock-metric-empathy', name: 'Empathy', kind: 'rating', category: 'quality' },
  {
    id: 'mock-metric-resolution',
    name: 'Problem Resolved',
    kind: 'boolean',
    category: 'quality',
    policy: { metric_id: 'mock-metric-resolution', failure_values: ['false'] },
  },
  {
    id: 'mock-metric-compliance',
    name: 'Compliance Disclosure',
    kind: 'boolean',
    category: 'quality',
    policy: { metric_id: 'mock-metric-compliance', failure_values: ['false'] },
  },
  { id: 'mock-metric-accuracy', name: 'Answer Accuracy', kind: 'rating', category: 'quality' },
  {
    id: 'mock-metric-outcome',
    name: 'Call Outcome',
    kind: 'category',
    category: 'quality',
    labels: ['resolved', 'callback_scheduled', 'escalated', 'angry_hangup'],
    policy: { metric_id: 'mock-metric-outcome', failure_values: ['angry_hangup'] },
  },
  {
    id: 'mock-metric-intent',
    name: 'Customer Intent',
    kind: 'category',
    category: 'user_insight',
    labels: ['billing_question', 'cancel_request', 'technical_issue', 'upgrade_inquiry'],
  },
]

export const MOCK_TOOLS = [
  'lookup_order',
  'verify_identity',
  'process_refund',
  'schedule_callback',
  'create_ticket',
  'check_balance',
  'apply_discount',
  'transfer_call',
] as const

export type MockToolName = (typeof MOCK_TOOLS)[number]

export interface MockIntegrationDef {
  id: string
  name: string
  color: string
}

export const MOCK_INTEGRATIONS: MockIntegrationDef[] = [
  { id: 'postgres', name: 'Postgres', color: '#336791' },
  { id: 'notion', name: 'Notion', color: '#111111' },
  { id: 'slack', name: 'Slack', color: '#E01E5A' },
  { id: 'zendesk', name: 'Zendesk', color: '#17494D' },
  { id: 'stripe', name: 'Stripe', color: '#635BFF' },
  { id: 'hubspot', name: 'HubSpot', color: '#FF7A59' },
  { id: 'gmail', name: 'Gmail', color: '#EA4335' },
  { id: 'salesforce', name: 'Salesforce', color: '#00A1E0' },
]

export const USE_CASE_INTEGRATION: Record<MockToolName, string> = {
  lookup_order: 'postgres',
  verify_identity: 'postgres',
  process_refund: 'stripe',
  schedule_callback: 'gmail',
  create_ticket: 'zendesk',
  check_balance: 'stripe',
  apply_discount: 'hubspot',
  transfer_call: 'slack',
}

export function integrationById(id: string): MockIntegrationDef | undefined {
  return MOCK_INTEGRATIONS.find((item) => item.id === id)
}

export function integrationByNameOrId(key: string): MockIntegrationDef | undefined {
  const lower = key.toLowerCase()
  return MOCK_INTEGRATIONS.find((item) => item.id === key || item.name.toLowerCase() === lower)
}

export interface MockScenarioDef {
  id: string
  name: string
  agentId: string
  metricIds: string[]
}

export const SCENARIOS: MockScenarioDef[] = [
  {
    id: 'mock-scenario-refund',
    name: 'Refund request after failed delivery',
    agentId: 'mock-agent-support-eu',
    metricIds: ['mock-metric-empathy', 'mock-metric-resolution', 'mock-metric-outcome', 'mock-metric-compliance'],
  },
  {
    id: 'mock-scenario-angry',
    name: 'Frustrated caller, repeated issue',
    agentId: 'mock-agent-support-eu',
    metricIds: ['mock-metric-empathy', 'mock-metric-resolution', 'mock-metric-outcome'],
  },
  {
    id: 'mock-scenario-identity',
    name: 'Identity verification fails twice',
    agentId: 'mock-agent-support-eu',
    metricIds: ['mock-metric-accuracy', 'mock-metric-compliance', 'mock-metric-outcome'],
  },
  {
    id: 'mock-scenario-upgrade',
    name: 'Plan upgrade with discount question',
    agentId: 'mock-agent-sales-outbound',
    metricIds: ['mock-metric-empathy', 'mock-metric-accuracy', 'mock-metric-outcome'],
  },
  {
    id: 'mock-scenario-demo',
    name: 'Product demo follow-up',
    agentId: 'mock-agent-sales-outbound',
    metricIds: ['mock-metric-empathy', 'mock-metric-resolution', 'mock-metric-intent'],
  },
  {
    id: 'mock-scenario-invoice',
    name: 'Invoice dispute after double charge',
    agentId: 'mock-agent-billing',
    metricIds: ['mock-metric-resolution', 'mock-metric-compliance', 'mock-metric-intent'],
  },
  {
    id: 'mock-scenario-balance',
    name: 'Check remaining credits',
    agentId: 'mock-agent-billing',
    metricIds: ['mock-metric-accuracy', 'mock-metric-compliance'],
  },
]

export const SCENARIO_INTENT: Record<string, string> = {
  'mock-scenario-refund': 'billing_question',
  'mock-scenario-angry': 'cancel_request',
  'mock-scenario-upgrade': 'upgrade_inquiry',
  'mock-scenario-identity': 'technical_issue',
  'mock-scenario-demo': 'upgrade_inquiry',
  'mock-scenario-invoice': 'billing_question',
  'mock-scenario-balance': 'billing_question',
}

export const AGENT_METRICS: Record<string, string[]> = {
  'mock-agent-support-eu': [
    'mock-metric-empathy',
    'mock-metric-resolution',
    'mock-metric-compliance',
    'mock-metric-accuracy',
    'mock-metric-outcome',
    'mock-metric-intent',
  ],
  'mock-agent-sales-outbound': [
    'mock-metric-empathy',
    'mock-metric-resolution',
    'mock-metric-compliance',
    'mock-metric-accuracy',
    'mock-metric-outcome',
    'mock-metric-intent',
  ],
  'mock-agent-billing': [
    'mock-metric-empathy',
    'mock-metric-resolution',
    'mock-metric-compliance',
    'mock-metric-intent',
  ],
}

export type MetricLevel = 0 | 1 | 2 | 3

export interface MetricDependencyNode {
  id: string
  name: string
  level: MetricLevel
  drives: string[]
  kind?: 'metric' | 'scenario'
}

export const METRIC_LEVEL_COLORS: Record<MetricLevel, string> = {
  0: '#eab308',
  1: '#6366f1',
  2: '#14b8a6',
  3: '#f97316',
}

export const METRIC_DEPENDENCIES: MetricDependencyNode[] = [
  { id: 'north-star', name: 'North star', level: 0, drives: [] },
  { id: 'mock-metric-resolution', name: 'Problem Resolved', level: 1, drives: ['north-star'] },
  { id: 'mock-metric-outcome', name: 'Call Outcome', level: 1, drives: ['north-star'] },
  { id: 'closing_quality', name: 'Closing quality', level: 2, drives: ['mock-metric-resolution', 'mock-metric-outcome'] },
  { id: 'early_ending', name: 'Early ending', level: 2, drives: ['mock-metric-resolution', 'mock-metric-outcome'] },
  { id: 'mock-metric-empathy', name: 'Empathy', level: 2, drives: ['mock-metric-resolution'] },
  { id: 'mock-metric-accuracy', name: 'Answer Accuracy', level: 2, drives: ['mock-metric-resolution'] },
  { id: 'mock-metric-compliance', name: 'Compliance Disclosure', level: 2, drives: ['mock-metric-outcome', 'mock-metric-resolution'] },
  { id: 'mock-metric-intent', name: 'Customer Intent', level: 2, drives: ['mock-metric-outcome', 'mock-metric-resolution'] },
  { id: 'silence_duration', name: 'Silence duration', level: 3, drives: ['early_ending', 'closing_quality'] },
  { id: 'longest_pause', name: 'Longest pause', level: 3, drives: ['early_ending'] },
  { id: 'tool_call_failures', name: 'Tool call failures', level: 3, drives: ['mock-metric-accuracy', 'closing_quality'] },
  { id: 'rag_call_failures', name: 'RAG call failures', level: 3, drives: ['mock-metric-accuracy'] },
  { id: 'talk_ratio', name: 'Talk ratio', level: 3, drives: ['mock-metric-empathy'] },
  { id: 'avg_duration', name: 'Avg duration', level: 3, drives: ['closing_quality'] },
]

export function scenariosForAgent(agentId: string): MockScenarioDef[] {
  return SCENARIOS.filter((scenario) => scenario.agentId === agentId)
}

export function metricsForAgent(agentId: string): string[] {
  return AGENT_METRICS[agentId] ?? MOCK_METRICS.map((metric) => metric.id)
}

const GLOBAL_TREE_IDS = new Set([
  'north-star',
  'closing_quality',
  'early_ending',
  'silence_duration',
  'longest_pause',
  'tool_call_failures',
  'rag_call_failures',
  'talk_ratio',
  'avg_duration',
])

function isLocalMetric(id: string) {
  return id.startsWith('mock-metric-')
}

export function buildScopedMetricTree(agentId?: string | null, scenarioId?: string | null): MetricDependencyNode[] {
  const catalog = new Map(
    METRIC_DEPENDENCIES.map((node) => [node.id, { ...node, drives: [...node.drives], kind: node.kind ?? 'metric' }]),
  )
  const scenario = scenarioId ? SCENARIOS.find((item) => item.id === scenarioId) : undefined
  const scopedAgent = agentId ?? scenario?.agentId ?? null
  const agentMetrics = scopedAgent ? new Set(metricsForAgent(scopedAgent)) : null
  const scenarioMetrics = scenario ? new Set(scenario.metricIds) : null

  const allowedLocal = (id: string) => {
    if (!isLocalMetric(id)) return true
    if (scenarioMetrics) return scenarioMetrics.has(id)
    if (agentMetrics) return agentMetrics.has(id)
    return true
  }

  const visible = new Set<string>(['north-star'])
  const visitUp = (id: string) => {
    if (visible.has(id)) return
    const node = catalog.get(id)
    if (!node || !allowedLocal(id)) return
    visible.add(id)
    for (const parent of node.drives) visitUp(parent)
  }

  if (scenarioMetrics) {
    for (const id of scenarioMetrics) visitUp(id)
  } else if (agentMetrics) {
    for (const id of agentMetrics) visitUp(id)
    for (const id of GLOBAL_TREE_IDS) visitUp(id)
    let grew = true
    while (grew) {
      grew = false
      for (const node of catalog.values()) {
        if (visible.has(node.id) || !allowedLocal(node.id)) continue
        if (node.drives.some((target) => visible.has(target))) {
          visible.add(node.id)
          grew = true
        }
      }
    }
  } else {
    for (const id of catalog.keys()) visitUp(id)
  }

  const nodes: MetricDependencyNode[] = []
  for (const id of visible) {
    const node = catalog.get(id)
    if (!node) continue
    const drives = node.drives.filter((target) => visible.has(target))
    nodes.push({
      ...node,
      drives: node.id === 'north-star' ? [] : drives.length ? drives : ['north-star'],
    })
  }

  if (!scopedAgent) return nodes

  const scenarios = scenariosForAgent(scopedAgent).filter((item) => !scenarioId || item.id === scenarioId)
  for (const item of scenarios) {
    const outcomeIds = item.metricIds.filter((id) => catalog.get(id)?.level === 1 && visible.has(id))
    const drives = outcomeIds.length ? outcomeIds : ['north-star']
    nodes.push({
      id: item.id,
      name: item.name,
      level: 2,
      drives,
      kind: 'scenario',
    })
    for (const metricId of item.metricIds) {
      const metric = nodes.find((node) => node.id === metricId)
      if (metric && !metric.drives.includes(item.id)) metric.drives.push(item.id)
    }
  }

  return nodes
}

export function treeReachesNorthStar(nodes: MetricDependencyNode[]): boolean {
  const byId = new Map(nodes.map((node) => [node.id, node]))
  const walk = (id: string, seen: Set<string>): boolean => {
    if (id === 'north-star') return true
    if (seen.has(id)) return false
    seen.add(id)
    const node = byId.get(id)
    if (!node || node.drives.length === 0) return false
    return node.drives.some((target) => walk(target, seen))
  }
  return nodes.every((node) => node.id === 'north-star' || walk(node.id, new Set()))
}

interface Profile {
  base: number
  slope: number
  breakDaysAgo?: number
  breakDelta?: number
}

function profileFor(agentId: string, metricId: string): Profile {
  const table: Record<string, Profile> = {
    'mock-agent-support-eu:mock-metric-empathy': { base: 0.82, slope: 0, breakDaysAgo: 4, breakDelta: -0.13 },
    'mock-agent-support-eu:mock-metric-resolution': { base: 0.72, slope: -0.004 },
    'mock-agent-support-eu:mock-metric-compliance': { base: 0.93, slope: 0.001 },
    'mock-agent-support-eu:mock-metric-accuracy': { base: 0.84, slope: 0.0005 },
    'mock-agent-support-eu:mock-metric-outcome': { base: 0.26, slope: -0.003 },
    'mock-agent-sales-outbound:mock-metric-empathy': { base: 0.74, slope: 0.006 },
    'mock-agent-sales-outbound:mock-metric-resolution': { base: 0.85, slope: 0.003 },
    'mock-agent-sales-outbound:mock-metric-compliance': { base: 0.88, slope: 0.002 },
    'mock-agent-sales-outbound:mock-metric-accuracy': { base: 0.79, slope: 0.004 },
    'mock-agent-sales-outbound:mock-metric-outcome': { base: 0.12, slope: -0.002 },
    'mock-agent-billing:mock-metric-empathy': { base: 0.77, slope: 0 },
    'mock-agent-billing:mock-metric-resolution': { base: 0.8, slope: 0.0005 },
    'mock-agent-billing:mock-metric-compliance': { base: 0.97, slope: 0 },
    'mock-agent-billing:mock-metric-accuracy': { base: 0.88, slope: -0.0005 },
    'mock-agent-billing:mock-metric-outcome': { base: 0.09, slope: 0 },
  }
  return table[`${agentId}:${metricId}`] ?? { base: 0.8, slope: 0 }
}

export function primaryValueAt(agentId: string, metricId: string, daysAgo: number, rng: () => number): number {
  const profile = profileFor(agentId, metricId)
  let value = profile.base - profile.slope * daysAgo
  if (profile.breakDaysAgo != null && profile.breakDelta != null && daysAgo <= profile.breakDaysAgo) {
    value += profile.breakDelta
  }
  value += (rng() - 0.5) * 0.03
  return clamp(value, 0.02, 0.99)
}

export function scenarioAdjustment(scenarioId: string | undefined, metricId: string): number {
  if (!scenarioId) return 0
  const table: Record<string, number> = {
    'mock-scenario-angry': -0.14,
    'mock-scenario-identity': -0.08,
    'mock-scenario-refund': -0.02,
    'mock-scenario-upgrade': 0.05,
    'mock-scenario-demo': 0.04,
    'mock-scenario-invoice': -0.06,
    'mock-scenario-balance': 0.02,
  }
  const base = table[scenarioId] ?? 0
  return metricId === 'mock-metric-compliance' ? base / 3 : base
}

export function daysBetween(since: string, until: string): number {
  const ms = new Date(until).getTime() - new Date(since).getTime()
  return Math.max(1, Math.round(ms / (24 * 60 * 60 * 1000)))
}
