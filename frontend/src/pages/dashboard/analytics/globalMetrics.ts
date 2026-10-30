import type { Polarity } from './metricMath'

export type GlobalMetricKind = 'count' | 'duration' | 'rating' | 'ratio'

export type GlobalMetricId =
  | 'total_calls'
  | 'avg_duration'
  | 'closing_quality'
  | 'early_ending'
  | 'silence_duration'
  | 'longest_pause'
  | 'tool_call_failures'
  | 'rag_call_failures'
  | 'talk_ratio'

export interface GlobalMetricFailRule {
  op: 'gt' | 'gte' | 'lt' | 'lte' | 'eq' | 'neq'
  value: number
}

export interface GlobalMetricDef {
  id: GlobalMetricId
  name: string
  kind: GlobalMetricKind
  unit: string
  polarity: Polarity
  clickable: boolean
  parentId?: GlobalMetricId
  subMetricIds?: GlobalMetricId[]
  description: string
  improvementHints: string[]
  failRule?: GlobalMetricFailRule
}

export const GLOBAL_METRICS: GlobalMetricDef[] = [
  {
    id: 'total_calls',
    name: 'Total calls',
    kind: 'count',
    unit: 'calls',
    polarity: 'neutral',
    clickable: false,
    description: 'All calls in the window across the selected agents. Simulation and live are counted separately.',
    improvementHints: [],
  },
  {
    id: 'avg_duration',
    name: 'Avg duration',
    kind: 'duration',
    unit: 's',
    polarity: 'neutral',
    clickable: true,
    description: 'Average call length. Drill-down shows the longest and shortest calls across agents.',
    improvementHints: [
      'Calls under 20s usually mean the agent hung up or the caller abandoned before the first useful turn.',
      'Calls over 8 minutes often loop on the same policy explanation — add a callback or escalation path.',
    ],
    failRule: { op: 'lt', value: 20 },
  },
  {
    id: 'closing_quality',
    name: 'Avg closing quality',
    kind: 'rating',
    unit: '/5',
    polarity: 'higher_is_better',
    clickable: true,
    description: 'Was the reason for the call closed before it ended? Rated 1–5 on each call, then averaged.',
    improvementHints: [
      'Add an explicit wrap-up: confirm the outcome, next step, and whether the caller is unblocked.',
      'When the issue cannot be resolved, offer a callback or ticket instead of ending the call.',
    ],
    failRule: { op: 'lt', value: 3 },
  },
  {
    id: 'early_ending',
    name: 'Early ending',
    kind: 'count',
    unit: 'calls',
    polarity: 'lower_is_better',
    clickable: true,
    description: 'Calls that ended earlier than intended — hang-up, timeout, or transfer before resolution.',
    improvementHints: [
      'Inspect hang-up logic after failed identity checks and after two unanswered questions.',
      'Raise the silence-hangup threshold if callers are being dropped while they think.',
    ],
    failRule: { op: 'eq', value: 1 },
  },
  {
    id: 'silence_duration',
    name: 'Silence duration',
    kind: 'duration',
    unit: 's',
    polarity: 'lower_is_better',
    clickable: true,
    subMetricIds: ['longest_pause'],
    description: 'Average gap between consecutive turns. Longest pause is a sub-metric of the same gaps.',
    improvementHints: [
      'Long gaps after user speech usually mean high TTFT — check LLM and TTS latency.',
      'If the agent waits for itself, add a filler or barge-in so the caller hears something within 1.5s.',
    ],
    failRule: { op: 'gt', value: 2.5 },
  },
  {
    id: 'longest_pause',
    name: 'Longest pause',
    kind: 'duration',
    unit: 's',
    polarity: 'lower_is_better',
    clickable: true,
    parentId: 'silence_duration',
    description: 'The single longest inter-turn gap on a call, then averaged (or listed) across calls.',
    improvementHints: [
      'A single pause over 6 seconds is almost always a tool timeout or an empty RAG result.',
    ],
    failRule: { op: 'gt', value: 6 },
  },
  {
    id: 'tool_call_failures',
    name: 'Tool call failures',
    kind: 'count',
    unit: 'failures',
    polarity: 'lower_is_better',
    clickable: true,
    description: 'Total tool/function-call errors across calls.',
    improvementHints: [
      'Retry idempotent tools once and tell the caller you are checking, instead of going silent.',
      'Map common error codes to a spoken fallback so the agent does not invent an answer.',
    ],
    failRule: { op: 'gt', value: 0 },
  },
  {
    id: 'rag_call_failures',
    name: 'RAG call failures',
    kind: 'count',
    unit: 'failures',
    polarity: 'lower_is_better',
    clickable: true,
    description: 'Total retrieval/knowledge-base errors across calls.',
    improvementHints: [
      'Log empty retrievals and add a “I don’t have that in the knowledge base” path.',
      'Tighten the query rewrite so billing and policy questions hit the right documents.',
    ],
    failRule: { op: 'gt', value: 0 },
  },
  {
    id: 'talk_ratio',
    name: 'Talk ratio',
    kind: 'ratio',
    unit: ':1',
    polarity: 'lower_is_better',
    clickable: true,
    description: 'Agent turns to human turns. Values well above 1 mean the agent is talking over the caller.',
    improvementHints: [
      'Cap policy explanations at two sentences, then ask a check-in question.',
      'If the ratio is below 0.4 the agent is barely speaking — look for missed turns or muted TTS.',
    ],
    failRule: { op: 'gt', value: 2 },
  },
]

const BY_ID: Record<string, GlobalMetricDef> = Object.fromEntries(
  GLOBAL_METRICS.map((metric) => [metric.id, metric]),
)

export function isGlobalMetricId(value: string | null | undefined): value is GlobalMetricId {
  return Boolean(value && value in BY_ID)
}

export function globalMetricById(id: string | null | undefined): GlobalMetricDef | undefined {
  if (!id) return undefined
  return BY_ID[id]
}

export const STRIP_METRIC_IDS: GlobalMetricId[] = [
  'total_calls',
  'avg_duration',
  'closing_quality',
  'early_ending',
  'silence_duration',
  'tool_call_failures',
  'rag_call_failures',
  'talk_ratio',
]

export function failsRule(value: number, rule: GlobalMetricFailRule | undefined): boolean {
  if (!rule) return false
  switch (rule.op) {
    case 'gt':
      return value > rule.value
    case 'gte':
      return value >= rule.value
    case 'lt':
      return value < rule.value
    case 'lte':
      return value <= rule.value
    case 'eq':
      return value === rule.value
    case 'neq':
      return value !== rule.value
    default:
      return false
  }
}

export function formatGlobalValue(def: GlobalMetricDef, value: number | null): string {
  if (value == null || Number.isNaN(value)) return '—'
  if (def.kind === 'count') return Math.round(value).toLocaleString()
  if (def.kind === 'rating') return `${value.toFixed(1)} / 5`
  if (def.kind === 'ratio') return `${value.toFixed(2)} : 1`
  return formatDuration(value)
}

export function formatDuration(seconds: number): string {
  if (seconds < 60) return `${seconds < 10 ? seconds.toFixed(1) : Math.round(seconds)}s`
  const minutes = Math.floor(seconds / 60)
  const rest = Math.round(seconds % 60)
  return `${minutes}m ${rest.toString().padStart(2, '0')}s`
}
