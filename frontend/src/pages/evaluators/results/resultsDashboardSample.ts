import type {
  CallImportMetricAggregate,
  EvaluatorResultRow,
  EvaluatorResultsAgentSummary,
  EvaluatorResultsDashboardOpsResponse,
} from '../../../types/api'

/** Temporary sample so every dashboard chart can be reviewed. Delete this module to remove it. */

const AGENTS = [
  { id: 'sample-support', name: 'Support' },
  { id: 'sample-sales', name: 'Sales' },
  { id: 'sample-billing', name: 'Billing' },
] as const

const METRICS = {
  closing: 'sample-closing',
  accuracy: 'sample-accuracy',
  empathy: 'sample-empathy',
  outcome: 'sample-outcome',
} as const

function recentDays(count = 7): string[] {
  const days: string[] = []
  const today = new Date()
  for (let offset = count - 1; offset >= 0; offset -= 1) {
    const date = new Date(today)
    date.setDate(today.getDate() - offset)
    const month = String(date.getMonth() + 1).padStart(2, '0')
    const day = String(date.getDate()).padStart(2, '0')
    days.push(`${date.getFullYear()}-${month}-${day}`)
  }
  return days
}

const DAYS = recentDays()

function wave(index: number, base: number, swing: number): number {
  return Math.round((base + Math.sin(index / 1.7) * swing) * 100) / 100
}

export const SAMPLE_OPS: EvaluatorResultsDashboardOpsResponse = {
  cost_by_agent: AGENTS.map((agent, index) => ({
    agent_id: agent.id,
    agent_name: agent.name,
    llm_usd: wave(index, 1.4, 0.4),
    stt_usd: wave(index + 1, 0.35, 0.1),
    tts_usd: wave(index + 2, 0.22, 0.08),
    total_usd: 0,
    agent_usd: wave(index, 1.1, 0.3),
    simulator_usd: 0.18 + index * 0.04,
    judge_usd: 0.12 + index * 0.03,
    models: [
      { model: 'whisper', role: 'agent', cost_usd: [60.48, 9, 15.25][index] ?? 10 },
      { model: 'nova-2', role: 'agent', cost_usd: [22, 31, 8][index] ?? 10 },
      { model: 'eleven-flash', role: 'agent', cost_usd: [28, 14, 19][index] ?? 10 },
      { model: 'cartesia', role: 'agent', cost_usd: [11, 24, 16][index] ?? 8 },
      { model: 'gpt-4.1', role: 'agent', cost_usd: [48, 21, 17][index] ?? 12 },
      { model: 'gpt-4o-mini', role: 'agent', cost_usd: [18, 36, 9][index] ?? 8 },
      { model: 'gpt-4o-realtime', role: 'agent', cost_usd: [6, 27, 4][index] ?? 5 },
    ],
  })).map((row) => ({
    ...row,
    total_usd: Math.round((row.llm_usd + row.stt_usd + row.tts_usd) * 100) / 100,
  })),
  cost_by_model_day: DAYS.flatMap((day, index) => [
    { day, model: 'gpt-4.1', cost_usd: wave(index, 0.42, 0.12) },
    { day, model: 'gpt-4o-mini', cost_usd: wave(index + 1, 0.16, 0.05) },
    { day, model: 'whisper', cost_usd: wave(index + 2, 0.08, 0.03) },
  ]),
  cost_by_agent_day: DAYS.flatMap((day, index) =>
    AGENTS.flatMap((agent, agentIndex) => [
      {
        day,
        agent_id: agent.id,
        role: 'agent',
        llm_usd: wave(index + agentIndex, 0.28, 0.08),
        stt_usd: wave(index, 0.06, 0.02),
        tts_usd: wave(index, 0.04, 0.01),
      },
      {
        day,
        agent_id: agent.id,
        role: 'simulator',
        llm_usd: 0.05,
        stt_usd: 0,
        tts_usd: 0.02,
      },
      {
        day,
        agent_id: agent.id,
        role: 'judge',
        llm_usd: 0.04,
        stt_usd: 0,
        tts_usd: 0,
      },
    ]),
  ),
  model_layers: [
    { model: 'whisper', usage_kind: 'stt', cost_usd: 0.82, usd_per_minute: 0.006, usd_per_million_tokens: null },
    { model: 'nova-2', usage_kind: 'stt', cost_usd: 0.31, usd_per_minute: 0.0043, usd_per_million_tokens: null },
    { model: 'eleven-flash', usage_kind: 'tts', cost_usd: 0.94, usd_per_minute: 0.12, usd_per_million_tokens: null },
    { model: 'cartesia', usage_kind: 'tts', cost_usd: 0.27, usd_per_minute: 0.05, usd_per_million_tokens: null },
    { model: 'gpt-4.1', usage_kind: 'llm', cost_usd: 2.4, usd_per_minute: null, usd_per_million_tokens: 2 },
    { model: 'gpt-4o-mini', usage_kind: 'llm', cost_usd: 0.24, usd_per_minute: null, usd_per_million_tokens: 0.15 },
    { model: 'gpt-4o-realtime', usage_kind: 's2s', cost_usd: 1.15, usd_per_minute: 0.06, usd_per_million_tokens: 5 },
  ],
  price_by_day: DAYS.flatMap((day, index) => [
    { day, model: 'whisper', usd_per_minute: wave(index, 0.006, 0.001), usd_per_million_tokens: null },
    { day, model: 'nova-2', usd_per_minute: wave(index + 1, 0.004, 0.0008), usd_per_million_tokens: null },
    { day, model: 'eleven-flash', usd_per_minute: wave(index + 2, 0.12, 0.01), usd_per_million_tokens: null },
    { day, model: 'gpt-4.1', usd_per_minute: null, usd_per_million_tokens: wave(index, 2, 0.15) },
    { day, model: 'gpt-4o-mini', usd_per_minute: null, usd_per_million_tokens: wave(index + 1, 0.15, 0.02) },
    { day, model: 'gpt-4o-realtime', usd_per_minute: wave(index + 3, 0.06, 0.008), usd_per_million_tokens: wave(index + 2, 5, 0.2) },
  ]),
  tool_calls_by_agent_day: DAYS.flatMap((day, index) =>
    AGENTS.map((agent, agentIndex) => ({
      day,
      agent_id: agent.id,
      agent_name: agent.name,
      calls: Math.round(wave(index + agentIndex, 8 + agentIndex * 3, 3)),
      errors: index % 3 === 0 ? 1 : 0,
    })),
  ),
  tool_calls_by_tool: [
    { agent_id: 'sample-support', agent_name: 'Support', tool: 'lookup_order', calls: 42, errors: 2 },
    { agent_id: 'sample-support', agent_name: 'Support', tool: 'process_refund', calls: 18, errors: 1 },
    { agent_id: 'sample-sales', agent_name: 'Sales', tool: 'verify_identity', calls: 27, errors: 0 },
    { agent_id: 'sample-sales', agent_name: 'Sales', tool: 'schedule_callback', calls: 14, errors: 1 },
    { agent_id: 'sample-billing', agent_name: 'Billing', tool: 'check_balance', calls: 23, errors: 0 },
    { agent_id: 'sample-billing', agent_name: 'Billing', tool: 'apply_discount', calls: 9, errors: 2 },
  ],
  tool_calls_per_run: [
    { agent_id: 'sample-support', agent_name: 'Support', runs: 18, calls: 60, avg_per_run: 3.33 },
    { agent_id: 'sample-sales', agent_name: 'Sales', runs: 16, calls: 41, avg_per_run: 2.56 },
    { agent_id: 'sample-billing', agent_name: 'Billing', runs: 14, calls: 32, avg_per_run: 2.29 },
  ],
  providers: [
    { provider: 'postgres', calls: 48 },
    { provider: 'stripe', calls: 31 },
    { provider: 'zendesk', calls: 22 },
    { provider: 'slack', calls: 14 },
  ],
  provider_by_day: DAYS.flatMap((day, index) => [
    { day, provider: 'postgres', calls: Math.round(wave(index, 7, 2)) },
    { day, provider: 'stripe', calls: Math.round(wave(index + 1, 4, 1.5)) },
    { day, provider: 'zendesk', calls: Math.round(wave(index + 2, 3, 1)) },
    { day, provider: 'slack', calls: Math.round(wave(index + 3, 2, 0.8)) },
  ]),
  provider_by_agent: [
    { agent_id: 'sample-support', agent_name: 'Support', provider: 'postgres', calls: 28 },
    { agent_id: 'sample-support', agent_name: 'Support', provider: 'zendesk', calls: 16 },
    { agent_id: 'sample-sales', agent_name: 'Sales', provider: 'postgres', calls: 12 },
    { agent_id: 'sample-sales', agent_name: 'Sales', provider: 'slack', calls: 11 },
    { agent_id: 'sample-billing', agent_name: 'Billing', provider: 'stripe', calls: 24 },
    { agent_id: 'sample-billing', agent_name: 'Billing', provider: 'postgres', calls: 8 },
  ],
  calls_with_no_tools: 6,
}

const OUTCOMES = ['Resolved', 'Escalated', 'Abandoned']

export const SAMPLE_RESULTS: EvaluatorResultRow[] = DAYS.flatMap((day, dayIndex) =>
  AGENTS.map((agent, agentIndex) => {
    const failed = dayIndex === 2 && agentIndex === 2
    const outcome = OUTCOMES[(dayIndex + agentIndex) % OUTCOMES.length]
    return {
      id: `sample-${day}-${agent.id}`,
      result_id: `R${dayIndex}${agentIndex}`,
      name: `${agent.name} ${day.slice(5)}`,
      evaluator_id: 'sample-evaluator',
      agent_id: agent.id,
      timestamp: `${day}T12:00:00.000Z`,
      duration_seconds: 70 + dayIndex * 8 + agentIndex * 15,
      status: failed ? 'failed' : 'completed',
      error_message: null,
      metric_scores: (failed
        ? null
        : {
          [METRICS.closing]: { value: Number(wave(dayIndex + agentIndex, 4.1, 0.4).toFixed(2)), type: 'number', metric_name: 'Closing quality' },
          [METRICS.accuracy]: { value: Number(wave(dayIndex, 0.82, 0.08).toFixed(2)), type: 'number', metric_name: 'Answer accuracy' },
          [METRICS.empathy]: { value: Number(wave(dayIndex + 2, 3.1, 0.5).toFixed(2)), type: 'rating', metric_name: 'Empathy' },
          [METRICS.outcome]: { value: outcome, type: 'classification', metric_name: 'Call outcome', chosen_child_name: outcome },
        }) as EvaluatorResultRow['metric_scores'],
      agent: { id: agent.id, name: agent.name },
      scenario: {
        id: `${agent.id}-scenario`,
        name: ['Refund request after failed delivery', 'Identity verification fails twice', 'Product demo follow-up', 'Plan upgrade with discount question', 'Frustrated caller, repeated issue'][(dayIndex + agentIndex) % 5],
      },
    }
  }),
)

function numericMetric(
  id: string,
  name: string,
  mean: number,
  count: number,
): CallImportMetricAggregate {
  return {
    metric_id: id,
    metric_name: name,
    metric_type: 'number',
    count,
    skipped_count: 2,
    error_count: 0,
    mean,
    median: mean - 0.1,
    p25: mean - 0.4,
    p75: mean + 0.3,
    p95: mean + 0.6,
    min: mean - 0.8,
    max: mean + 0.9,
    stddev: 0.35,
    histogram_buckets: [
      { x0: mean - 0.8, x1: mean - 0.3, count: 4 },
      { x0: mean - 0.3, x1: mean + 0.2, count: 9 },
      { x0: mean + 0.2, x1: mean + 0.8, count: 5 },
    ],
    value_counts: [],
  }
}

export const SAMPLE_METRICS: CallImportMetricAggregate[] = [
  numericMetric(METRICS.closing, 'Closing quality', 4.2, 18),
  numericMetric(METRICS.accuracy, 'Answer accuracy', 0.81, 16),
  numericMetric(METRICS.empathy, 'Empathy', 3.05, 11),
  {
    metric_id: METRICS.outcome,
    metric_name: 'Call outcome',
    metric_type: 'classification',
    count: 18,
    skipped_count: 1,
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
    value_counts: [
      { label: 'Resolved', count: 9 },
      { label: 'Escalated', count: 6 },
      { label: 'Abandoned', count: 3 },
    ],
  },
]

export const SAMPLE_AGENTS: EvaluatorResultsAgentSummary[] = [
  {
    agent_id: 'sample-support',
    agent_name: 'Support',
    counts: { total: 18, completed: 16, failed: 2, in_progress: 0 },
    suites: [
      {
        suite_id: 'sample-suite-support',
        suite_name: 'Support suite',
        agent_id: 'sample-support',
        counts: { total: 18, completed: 16, failed: 2, in_progress: 0 },
        scenarios: [
          { scenario_id: 'sample-refund', scenario_name: 'Refund request', counts: { total: 11, completed: 10, failed: 1, in_progress: 0 } },
          { scenario_id: 'sample-order', scenario_name: 'Order status', counts: { total: 7, completed: 6, failed: 1, in_progress: 0 } },
        ],
      },
    ],
  },
  {
    agent_id: 'sample-sales',
    agent_name: 'Sales',
    counts: { total: 16, completed: 15, failed: 1, in_progress: 0 },
    suites: [
      {
        suite_id: 'sample-suite-sales',
        suite_name: 'Sales suite',
        agent_id: 'sample-sales',
        counts: { total: 16, completed: 15, failed: 1, in_progress: 0 },
        scenarios: [
          { scenario_id: 'sample-pitch', scenario_name: 'Outbound pitch', counts: { total: 10, completed: 9, failed: 1, in_progress: 0 } },
          { scenario_id: 'sample-followup', scenario_name: 'Follow up', counts: { total: 6, completed: 6, failed: 0, in_progress: 0 } },
        ],
      },
    ],
  },
  {
    agent_id: 'sample-billing',
    agent_name: 'Billing',
    counts: { total: 14, completed: 12, failed: 2, in_progress: 0 },
    suites: [
      {
        suite_id: 'sample-suite-billing',
        suite_name: 'Billing suite',
        agent_id: 'sample-billing',
        counts: { total: 14, completed: 12, failed: 2, in_progress: 0 },
        scenarios: [
          { scenario_id: 'sample-invoice', scenario_name: 'Invoice question', counts: { total: 8, completed: 7, failed: 1, in_progress: 0 } },
          { scenario_id: 'sample-dispute', scenario_name: 'Dispute', counts: { total: 6, completed: 5, failed: 1, in_progress: 0 } },
        ],
      },
    ],
  },
]

export const SAMPLE_COMPLETED = SAMPLE_RESULTS.filter((row) => row.status === 'completed').length

const CALL_TITLES = [
  'Plan upgrade with discount question',
  'Identity verification fails twice',
  'Frustrated caller, repeated issue',
  'Product demo follow-up',
  'Refund request after failed delivery',
]

export type DashboardDrillCall = {
  at: string
  agent: string
  title: string
  durationSeconds: number
  costUsd: number
  tokens: number
  model: string
  tool: string
  provider: string
  uses?: Array<{ tool: string; provider: string; failed: boolean }>
  resultId?: string
}

export const SAMPLE_DRILL_CALLS: DashboardDrillCall[] = DAYS.flatMap((day, dayIndex) =>
  AGENTS.map((agent, agentIndex) => {
    const models = ['whisper', 'nova-2', 'eleven-flash', 'gpt-4.1', 'gpt-4o-mini', 'gpt-4o-realtime']
    const tools = ['lookup_order', 'process_refund', 'verify_identity', 'check_balance', 'schedule_callback', 'apply_discount']
    const providers = ['postgres', 'stripe', 'zendesk', 'slack']
    const tokens = 5500 - dayIndex * 280 - agentIndex * 420
    const provider = providers[(dayIndex + agentIndex * 2) % providers.length]
    const tool = tools[(dayIndex + agentIndex) % tools.length]
    const uses = [0, 1, 2].slice(0, 1 + ((dayIndex + agentIndex) % 3)).map((offset) => ({
      tool: tools[(dayIndex + agentIndex + offset) % tools.length],
      provider: offset === 0 ? provider : providers[(dayIndex + offset) % providers.length],
      failed: offset === 2 && dayIndex % 2 === 0,
    }))
    return {
      at: `${day}T${String(8 + agentIndex).padStart(2, '0')}:${String((dayIndex * 7) % 60).padStart(2, '0')}:00.000Z`,
      agent: agent.name,
      title: CALL_TITLES[(dayIndex + agentIndex) % CALL_TITLES.length],
      durationSeconds: 130 + dayIndex * 6 + agentIndex * 11,
      costUsd: Math.round((0.08 + (tokens / 20000)) * 1000) / 1000,
      tokens,
      model: models[(dayIndex + agentIndex) % models.length],
      tool,
      provider,
      uses,
    }
  }),
)
