import type {
  CallImportMetricAggregate,
  EvaluatorResultRow,
  EvaluatorResultsAgentSummary,
  EvaluatorResultsDashboardOpsResponse,
} from '../../../types/api'

/** Local dev fixtures (not wired in prod). Import manually when testing the dashboard UI offline. */

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

const SAMPLE_LAYERS = [
  { model: 'whisper', usage_kind: 'stt', cost_usd: 0.82, usd_per_minute: 0.006, usd_per_million_tokens: null },
  { model: 'nova-2', usage_kind: 'stt', cost_usd: 0.31, usd_per_minute: 0.0043, usd_per_million_tokens: null },
  { model: 'eleven-flash', usage_kind: 'tts', cost_usd: 0.94, usd_per_minute: 0.12, usd_per_million_tokens: null },
  { model: 'cartesia', usage_kind: 'tts', cost_usd: 0.27, usd_per_minute: 0.05, usd_per_million_tokens: null },
  { model: 'gpt-4.1', usage_kind: 'llm', cost_usd: 2.4, usd_per_minute: null, usd_per_million_tokens: 2 },
  { model: 'gpt-4o-mini', usage_kind: 'llm', cost_usd: 0.24, usd_per_minute: null, usd_per_million_tokens: 0.15 },
  { model: 'gpt-4o-realtime', usage_kind: 's2s', cost_usd: 1.15, usd_per_minute: 0.06, usd_per_million_tokens: 5 },
] as const

const AGENT_WEIGHTS = [0.55, 0.3, 0.15]

function money(value: number): number {
  return Math.round(value * 10000) / 10000
}

function spreadAcrossDays(total: number): number[] {
  const raw = DAYS.map((_, index) => 1 + Math.sin(index / 1.7) * 0.35)
  const scale = total / raw.reduce((sum, value) => sum + value, 0)
  const amounts = raw.map((value) => money(value * scale))
  const drift = money(total - amounts.reduce((sum, value) => sum + value, 0))
  amounts[amounts.length - 1] = money(amounts[amounts.length - 1] + drift)
  return amounts
}

export const SAMPLE_OPS: EvaluatorResultsDashboardOpsResponse = {
  cost_by_agent: AGENTS.map((agent, index) => {
    const models = SAMPLE_LAYERS.map((layer) => ({
      model: layer.model,
      role: 'agent' as const,
      cost_usd: index === AGENTS.length - 1
        ? money(layer.cost_usd - money(layer.cost_usd * AGENT_WEIGHTS[0]) - money(layer.cost_usd * AGENT_WEIGHTS[1]))
        : money(layer.cost_usd * AGENT_WEIGHTS[index]),
    }))
    const spend = (kind: string) => money(models
      .filter((item) => SAMPLE_LAYERS.find((layer) => layer.model === item.model)?.usage_kind === kind)
      .reduce((sum, item) => sum + item.cost_usd, 0))
    const total = money(models.reduce((sum, item) => sum + item.cost_usd, 0))
    return {
      agent_id: agent.id,
      agent_name: agent.name,
      llm_usd: spend('llm'),
      stt_usd: spend('stt'),
      tts_usd: spend('tts'),
      total_usd: total,
      agent_usd: total,
      simulator_usd: 0,
      judge_usd: 0,
      models,
    }
  }),
  cost_by_model_day: SAMPLE_LAYERS.flatMap((layer) => (
    spreadAcrossDays(layer.cost_usd).map((cost, index) => ({
      day: DAYS[index],
      model: layer.model,
      cost_usd: cost,
    }))
  )),
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
  model_layers: SAMPLE_LAYERS.map((layer) => ({ ...layer })),
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
  run_days: DAYS.map((day, index) => ({
    day,
    calls: AGENTS.length,
    completed: index === 2 ? AGENTS.length - 1 : AGENTS.length,
    failed: index === 2 ? 1 : 0,
    duration_seconds: 240 + index * 30,
    duration_count: AGENTS.length,
  })),
}

const OUTCOMES = ['Resolved', 'Escalated', 'Abandoned']

const AGENT_SCENARIOS: Record<string, Array<{ id: string; name: string }>> = {
  'sample-support': [
    { id: 'sample-refund', name: 'Refund request' },
    { id: 'sample-order', name: 'Order status' },
  ],
  'sample-sales': [
    { id: 'sample-pitch', name: 'Outbound pitch' },
    { id: 'sample-followup', name: 'Follow up' },
  ],
  'sample-billing': [
    { id: 'sample-invoice', name: 'Invoice question' },
    { id: 'sample-dispute', name: 'Dispute' },
  ],
}

export const SAMPLE_RESULTS: EvaluatorResultRow[] = DAYS.flatMap((day, dayIndex) =>
  AGENTS.map((agent, agentIndex) => {
    const failed = dayIndex === 2 && agentIndex === 2
    const outcome = OUTCOMES[(dayIndex + agentIndex) % OUTCOMES.length]
    const scenario = AGENT_SCENARIOS[agent.id][dayIndex % 2]
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
      scenario: { id: scenario.id, name: scenario.name },
    }
  }),
)

function buildSampleScoreDays() {
  const buckets = new Map<string, { sum: number; count: number }>()
  for (const row of SAMPLE_RESULTS) {
    if (!row.metric_scores) continue
    const day = row.timestamp.slice(0, 10)
    for (const [metricId, score] of Object.entries(row.metric_scores)) {
      if (typeof score.value !== 'number') continue
      const key = `${day}\0${metricId}`
      const cur = buckets.get(key) ?? { sum: 0, count: 0 }
      cur.sum += score.value
      cur.count += 1
      buckets.set(key, cur)
    }
  }
  return Array.from(buckets.entries()).map(([key, value]) => {
    const [day, metric_id] = key.split('\0')
    return { day, metric_id, score_sum: value.sum, score_count: value.count }
  })
}

SAMPLE_OPS.score_days = buildSampleScoreDays()

function numericMetric(
  id: string,
  name: string,
  mean: number,
  count: number,
): CallImportMetricAggregate {
  if (count === 0) {
    return {
      metric_id: id,
      metric_name: name,
      metric_type: 'number',
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

/** Catalog rows for metric scope filters in sample drilldowns. */
export const SAMPLE_METRIC_CATALOG = [
  { id: 'sample-unused', name: 'Hold time', agent_ids: [] as string[], scenario_ids: [] as string[], parent_metric_id: null as string | null },
  { id: 'sample-transfer', name: 'Transfer offer', agent_ids: [], scenario_ids: [], parent_metric_id: null },
  { id: METRICS.closing, name: 'Closing quality', agent_ids: ['sample-support', 'sample-sales'], scenario_ids: [], parent_metric_id: null },
  { id: METRICS.accuracy, name: 'Answer accuracy', agent_ids: ['sample-support'], scenario_ids: ['sample-refund'], parent_metric_id: null },
  { id: METRICS.empathy, name: 'Empathy', agent_ids: ['sample-billing'], scenario_ids: [], parent_metric_id: null },
  { id: METRICS.outcome, name: 'Call outcome', agent_ids: [], scenario_ids: [], parent_metric_id: null },
]

export const SAMPLE_METRICS: CallImportMetricAggregate[] = [
  numericMetric('sample-unused', 'Hold time', 0, 0),
  numericMetric('sample-transfer', 'Transfer offer', 0, 0),
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

function dayInRange(day: string, start: string | null, end: string | null): boolean {
  const key = day.slice(0, 10)
  if (start && key < start) return false
  if (end && key > end) return false
  return true
}

export function scopeSampleOps(
  ops: EvaluatorResultsDashboardOpsResponse,
  agentId: string,
  start: string | null,
  end: string | null,
): EvaluatorResultsDashboardOpsResponse {
  const agents = agentId ? ops.cost_by_agent.filter((row) => row.agent_id === agentId) : ops.cost_by_agent
  const shareDenom = ops.cost_by_agent.reduce((sum, row) => sum + row.total_usd, 0)
  const share = agentId
    ? (agents.reduce((sum, row) => sum + row.total_usd, 0) / (shareDenom || 1))
    : 1
  const scale = (value: number) => money(value * share)
  const dailyModels = ops.cost_by_model_day.filter((row) => dayInRange(row.day, start, end))
  const layerTotals = new Map<string, number>()
  for (const row of dailyModels) layerTotals.set(row.model, (layerTotals.get(row.model) ?? 0) + row.cost_usd)
  return {
    ...ops,
    cost_by_agent: agents,
    cost_by_agent_day: ops.cost_by_agent_day.filter((row) => (!agentId || row.agent_id === agentId) && dayInRange(row.day, start, end)),
    cost_by_model_day: dailyModels.map((row) => ({ ...row, cost_usd: scale(row.cost_usd) })),
    model_layers: ops.model_layers.map((layer) => ({
      ...layer,
      cost_usd: scale(layerTotals.get(layer.model) ?? 0),
    })),
    tool_calls_by_agent_day: ops.tool_calls_by_agent_day.filter((row) => (!agentId || row.agent_id === agentId) && dayInRange(row.day, start, end)),
    tool_calls_by_tool: ops.tool_calls_by_tool.filter((row) => !agentId || row.agent_id === agentId),
    tool_calls_per_run: ops.tool_calls_per_run.filter((row) => !agentId || row.agent_id === agentId),
    provider_by_day: ops.provider_by_day.filter((row) => dayInRange(row.day, start, end)),
    provider_by_agent: ops.provider_by_agent.filter((row) => !agentId || row.agent_id === agentId),
    score_days: (ops.score_days ?? []).filter((row) => dayInRange(row.day, start, end)),
    run_days: (ops.run_days ?? []).filter((row) => dayInRange(row.day, start, end)),
  }
}

export function sampleMetricsFor(rows: EvaluatorResultRow[]): CallImportMetricAggregate[] {
  const scored = [
    { id: METRICS.closing, name: 'Closing quality' },
    { id: METRICS.accuracy, name: 'Answer accuracy' },
    { id: METRICS.empathy, name: 'Empathy' },
  ].map((spec) => {
    const values = rows.flatMap((row) => {
      const score = row.metric_scores?.[spec.id]
      return typeof score?.value === 'number' ? [score.value] : []
    })
    const mean = values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : 0
    return numericMetric(spec.id, spec.name, Number(mean.toFixed(2)), values.length)
  })
  const outcomes = new Map<string, number>()
  for (const row of rows) {
    const score = row.metric_scores?.[METRICS.outcome]
    const label = typeof score?.value === 'string' ? score.value : ''
    if (!label) continue
    outcomes.set(label, (outcomes.get(label) ?? 0) + 1)
  }
  const outcomeCount = Array.from(outcomes.values()).reduce((sum, count) => sum + count, 0)
  return [
    numericMetric('sample-unused', 'Hold time', 0, 0),
    numericMetric('sample-transfer', 'Transfer offer', 0, 0),
    ...scored,
    {
      metric_id: METRICS.outcome,
      metric_name: 'Call outcome',
      metric_type: 'classification',
      count: outcomeCount,
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
      value_counts: Array.from(outcomes.entries()).map(([label, count]) => ({ label, count })),
    },
  ]
}

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
      resultId: `R${dayIndex}${agentIndex}`,
    }
  }),
)
