import type { EvaluatorSuite } from '../../../lib/api'
import type { Agent } from '../../../store/agentStore'
import type {
  CallImportMetricAggregate,
  EvaluationMetricClustersState,
  EvaluatorResultRow,
  EvaluatorResultsAggregateResponse,
  EvaluatorResultsOverviewResponse,
  MetricFailurePoliciesResponse,
  MetricFailurePolicy,
} from '../../../types/api'
import {
  MOCK_AGENTS,
  MOCK_METRICS,
  SCENARIOS,
  type MockMetricDef,
} from './mockCatalog'
import { listMockCalls, type MockCall, type MockCallScore } from './mockCalls'

export {
  MOCK_AGENTS,
  MOCK_METRICS,
  SCENARIOS,
  clamp,
  daysBetween,
  hashString,
  mulberry32,
  primaryValueAt,
  scenarioAdjustment,
} from './mockCatalog'
export type { MockAgentDef, MockMetricDef } from './mockCatalog'

export function mockAgents(): Agent[] {
  return MOCK_AGENTS.map((agent, index) => ({
    id: agent.id,
    agent_id: `A${100 + index}`,
    name: agent.name,
    phone_number: agent.phone,
    language: agent.language,
    description: 'Sample agent',
    call_type: 'inbound',
    call_medium: 'voice',
    created_at: new Date(Date.now() - 40 * 86400000).toISOString(),
    updated_at: new Date().toISOString(),
  }))
}

function simulationCalls(params?: {
  agentId?: string
  scenarioId?: string
  since?: string
  until?: string
}): MockCall[] {
  return listMockCalls({
    agentId: params?.agentId,
    source: 'simulation',
    since: params?.since,
    until: params?.until,
  }).filter((call) => !params?.scenarioId || call.scenarioId === params.scenarioId)
}

export function mockOverview(params?: { since?: string; until?: string }): EvaluatorResultsOverviewResponse {
  const since = params?.since ?? new Date(Date.now() - 6 * 86400000).toISOString()
  const until = params?.until ?? new Date().toISOString()
  const calls = simulationCalls({ since, until })
  const agents = MOCK_AGENTS.map((agent) => {
    const rows = calls.filter((call) => call.agentId === agent.id)
    const failed = Math.round(rows.length * 0.04)
    const inProgress = agent.id === 'mock-agent-support-eu' ? 2 : 0
    return {
      agent_id: agent.id,
      agent_name: agent.name,
      counts: {
        total: rows.length + inProgress,
        completed: Math.max(0, rows.length - failed),
        failed,
        in_progress: inProgress,
        last_run_at: rows[0]?.startedAt ?? new Date().toISOString(),
      },
    }
  })
  const workspace = agents.reduce(
    (acc, item) => ({
      total: acc.total + item.counts.total,
      completed: acc.completed + item.counts.completed,
      failed: acc.failed + item.counts.failed,
      in_progress: acc.in_progress + item.counts.in_progress,
    }),
    { total: 0, completed: 0, failed: 0, in_progress: 0 },
  )
  return {
    workspace_counts: workspace,
    agents,
    unassigned: { counts: { total: 0, completed: 0, failed: 0, in_progress: 0 }, recent_result_ids: [] },
  }
}

function emptyAggregate(metric: MockMetricDef): CallImportMetricAggregate {
  return {
    metric_id: metric.id,
    metric_name: metric.name,
    metric_type: metric.kind,
    metric_category: metric.category,
    is_multi_label_parent: false,
    count: 0,
    skipped_count: 0,
    error_count: 0,
    mean: null,
    median: null,
    p25: null,
    p75: null,
    p95: null,
    min: null,
    max: null,
    stddev: null,
    histogram_buckets: [],
    value_counts: [],
  }
}

function aggregateFromScores(metric: MockMetricDef, scores: MockCallScore[]): CallImportMetricAggregate {
  const base = emptyAggregate(metric)
  if (scores.length === 0) return base
  if (metric.kind === 'rating' || metric.kind === 'number') {
    const values = scores
      .map((score) => (typeof score.value === 'number' ? score.value : Number(score.value)))
      .filter((value) => Number.isFinite(value))
      .sort((a, b) => a - b)
    if (values.length === 0) return base
    const mean = values.reduce((sum, value) => sum + value, 0) / values.length
    const at = (p: number) => values[Math.min(values.length - 1, Math.floor(p * (values.length - 1)))]
    const variance = values.reduce((sum, value) => sum + (value - mean) ** 2, 0) / values.length
    const buckets = 6
    const histogram_buckets = Array.from({ length: buckets }, (_, index) => {
      const x0 = index / buckets
      const x1 = (index + 1) / buckets
      return {
        x0,
        x1,
        count: values.filter((value) => value >= x0 && (index === buckets - 1 ? value <= x1 : value < x1)).length,
      }
    }).filter((bucket) => bucket.count > 0)
    return {
      ...base,
      count: values.length,
      mean: Number(mean.toFixed(3)),
      median: Number(at(0.5).toFixed(3)),
      p25: Number(at(0.25).toFixed(3)),
      p75: Number(at(0.75).toFixed(3)),
      p95: Number(at(0.95).toFixed(3)),
      min: Number(values[0].toFixed(3)),
      max: Number(values[values.length - 1].toFixed(3)),
      stddev: Number(Math.sqrt(variance).toFixed(3)),
      histogram_buckets,
    }
  }
  const counts = new Map<string, number>()
  for (const score of scores) {
    const label = String(score.value)
    counts.set(label, (counts.get(label) ?? 0) + 1)
  }
  return {
    ...base,
    count: scores.length,
    value_counts: [...counts.entries()]
      .map(([label, count]) => ({ label, count }))
      .sort((a, b) => b.count - a.count),
  }
}

export function mockAggregate(params: {
  agentId?: string
  scenarioId?: string
  suiteId?: string
  since?: string
  until?: string
}): EvaluatorResultsAggregateResponse {
  const since = params.since ?? new Date(Date.now() - 6 * 86400000).toISOString()
  const until = params.until ?? new Date().toISOString()
  const calls = simulationCalls({
    agentId: params.agentId,
    scenarioId: params.scenarioId,
    since,
    until,
  })
  const failed = Math.round(calls.length * 0.04)
  const metrics = MOCK_METRICS.map((metric) => {
    const scores = calls
      .map((call) => call.metric_scores[metric.id])
      .filter((score): score is MockCallScore => Boolean(score))
    return aggregateFromScores(metric, scores)
  })
  return {
    scope: params.scenarioId
      ? `${params.agentId ?? 'workspace'}:${params.scenarioId}`
      : (params.agentId ?? 'workspace'),
    agent_id: params.agentId ?? null,
    scenario_id: params.scenarioId ?? null,
    suite_id: params.suiteId ?? null,
    total_rows: calls.length,
    completed_rows: Math.max(0, calls.length - failed),
    failed_rows: failed,
    metrics,
  }
}

export function mockFailurePolicies(): MetricFailurePoliciesResponse {
  const policies: Record<string, MetricFailurePolicy> = {}
  for (const metric of MOCK_METRICS) {
    if (metric.policy) policies[metric.id] = metric.policy
  }
  return { previews: [], policies, source: 'user', updated_at: new Date().toISOString() }
}

export function mockClusters(agentId: string): EvaluationMetricClustersState | null {
  if (agentId !== 'mock-agent-support-eu') return null
  const evidence = {
    quote: 'Caller: "I already told the last agent this." Agent: "Per our policy, the refund window is 14 days."',
  }
  return {
    status: 'completed',
    generated_at: new Date(Date.now() - 86400000).toISOString(),
    generated_at_completed_rows: 61,
    llm_calls_used: 18,
    is_stale: false,
    overview: 'Most empathy failures happen when the caller repeats context and the agent restates policy instead of acknowledging.',
    discovered_problems: [],
    groups: [
      {
        metric_id: 'mock-metric-empathy',
        metric_name: 'Empathy',
        flagged_count: 23,
        clusters: [
          {
            id: 'c-empathy-1',
            label: 'Restates policy instead of acknowledging frustration',
            gap_label: 'UNDERSPEC',
            level: 1,
            count: 9,
            share_pct: 39,
            sub_clusters: [],
            observation: 'The prompt never tells the agent to acknowledge before explaining policy.',
            evidence,
            is_discovered: false,
          },
          {
            id: 'c-empathy-2',
            label: 'Does not offer a callback when stuck',
            gap_label: 'MISSING',
            level: 1,
            count: 6,
            share_pct: 26,
            sub_clusters: [],
            observation: 'No callback flow exists in the prompt.',
            evidence,
            is_discovered: false,
          },
        ],
      },
      {
        metric_id: 'mock-metric-resolution',
        metric_name: 'Problem Resolved',
        flagged_count: 19,
        clusters: [
          {
            id: 'c-res-1',
            label: 'Fails identity check and ends the call',
            gap_label: 'LOGIC_GAP',
            level: 1,
            count: 8,
            share_pct: 42,
            sub_clusters: [],
            observation: 'After two failed verifications the agent hangs up instead of offering an alternative.',
            evidence,
            is_discovered: false,
          },
        ],
      },
    ],
  } as EvaluationMetricClustersState
}

export function mockSuites(): EvaluatorSuite[] {
  return MOCK_AGENTS.map((agent, agentIndex) => ({
    id: `mock-suite-${agent.id}`,
    organization_id: 'mock-org',
    name: `${agent.name} regression suite`,
    agent_id: agent.id,
    persona_id: 'mock-persona-1',
    agent_name: agent.name,
    default_runs_per_combination: 2,
    round_robin_index: 0,
    is_active: true,
    agent_suite_count: 1,
    combination_count: SCENARIOS.length,
    combinations: SCENARIOS.map((scenario, index) => ({
      id: `mock-combo-${agentIndex}-${index}`,
      evaluator_id: `mock-evaluator-${agentIndex}-${index}`,
      persona_id: 'mock-persona-1',
      persona_name: 'Impatient repeat caller',
      scenario_id: scenario.id,
      scenario_name: scenario.name,
    })),
    created_at: new Date(Date.now() - 30 * 86400000).toISOString(),
    updated_at: new Date().toISOString(),
  }))
}

export function mockEvaluatorResults(params: {
  agentId?: string
  since?: string
  until?: string
  limit?: number
}): { items: EvaluatorResultRow[]; total: number } {
  const since = params.since ?? new Date(Date.now() - 6 * 86400000).toISOString()
  const until = params.until ?? new Date().toISOString()
  const calls = simulationCalls({ agentId: params.agentId, since, until })
    .slice()
    .sort((a, b) => +new Date(b.startedAt) - +new Date(a.startedAt))
  const limit = params.limit ?? 20
  const items = calls.slice(0, limit).map((call, index) => ({
    id: call.id,
    result_id: String(100000 + index),
    name: call.scenarioName ?? 'Live call',
    evaluator_id: call.scenarioId ? `mock-evaluator-${call.scenarioId}` : null,
    agent_id: call.agentId,
    scenario_id: call.scenarioId,
    timestamp: call.startedAt,
    duration_seconds: call.durationSeconds,
    status: 'completed' as EvaluatorResultRow['status'],
    metric_scores: Object.fromEntries(
      Object.entries(call.metric_scores).map(([id, score]) => [
        id,
        { value: score.value, type: score.type, metric_name: score.metric_name, rationale: score.rationale },
      ]),
    ),
    error_message: null,
    agent: { id: call.agentId, name: call.agentName },
    scenario: call.scenarioId && call.scenarioName ? { id: call.scenarioId, name: call.scenarioName } : null,
  }))
  return { items, total: calls.length }
}

export function mockOptimizationRuns(agentId?: string) {
  const runs = [
    {
      id: 'mock-opt-1',
      agent_id: 'mock-agent-sales-outbound',
      evaluator_id: 'mock-evaluator-0',
      status: 'completed',
      best_score: 0.86,
      created_at: new Date(Date.now() - 10 * 86400000).toISOString(),
    },
    {
      id: 'mock-opt-2',
      agent_id: 'mock-agent-support-eu',
      evaluator_id: 'mock-evaluator-1',
      status: 'completed',
      best_score: 0.79,
      created_at: new Date(Date.now() - 2 * 3600000).toISOString(),
    },
    {
      id: 'mock-opt-3',
      agent_id: 'mock-agent-billing',
      evaluator_id: null,
      status: 'running',
      best_score: null,
      created_at: new Date(Date.now() - 3600000).toISOString(),
    },
  ]
  return agentId ? runs.filter((run) => run.agent_id === agentId) : runs
}

export function mockCallsHubSummary() {
  const live = listMockCalls({
    source: 'live',
    since: new Date(Date.now() - 29 * 86400000).toISOString(),
  })
  return {
    items: [],
    total: live.length,
    page: 1,
    page_size: 1,
    page_count: live.length,
    summary: {
      total: live.length,
      obs_total: live.length,
      obs_live: 3,
      obs_ended: Math.max(0, live.length - 14),
      obs_started: 11,
      obs_other: 0,
      traces_open: 2,
      traces_closed: Math.round(live.length / 3),
    },
  }
}
