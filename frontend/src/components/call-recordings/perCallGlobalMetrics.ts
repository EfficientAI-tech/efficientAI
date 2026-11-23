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
  clickable: boolean
  subMetricIds?: GlobalMetricId[]
  failRule?: GlobalMetricFailRule
}

export const GLOBAL_METRICS: GlobalMetricDef[] = [
  {
    id: 'avg_duration',
    name: 'Avg duration',
    kind: 'duration',
    clickable: true,
    failRule: { op: 'lt', value: 20 },
  },
  {
    id: 'closing_quality',
    name: 'Avg closing quality',
    kind: 'rating',
    clickable: true,
    failRule: { op: 'lt', value: 3 },
  },
  {
    id: 'early_ending',
    name: 'Early ending',
    kind: 'count',
    clickable: true,
    failRule: { op: 'eq', value: 1 },
  },
  {
    id: 'silence_duration',
    name: 'Silence duration',
    kind: 'duration',
    clickable: true,
    subMetricIds: ['longest_pause'],
    failRule: { op: 'gt', value: 2.5 },
  },
  {
    id: 'longest_pause',
    name: 'Longest pause',
    kind: 'duration',
    clickable: true,
    failRule: { op: 'gt', value: 6 },
  },
  {
    id: 'tool_call_failures',
    name: 'Tool call failures',
    kind: 'count',
    clickable: true,
    failRule: { op: 'gt', value: 0 },
  },
  {
    id: 'rag_call_failures',
    name: 'RAG call failures',
    kind: 'count',
    clickable: true,
    failRule: { op: 'gt', value: 0 },
  },
  {
    id: 'talk_ratio',
    name: 'Talk ratio',
    kind: 'ratio',
    clickable: true,
    failRule: { op: 'gt', value: 2 },
  },
]

const BY_ID: Record<string, GlobalMetricDef> = Object.fromEntries(
  GLOBAL_METRICS.map((metric) => [metric.id, metric]),
)

export function globalMetricById(id: string | null | undefined): GlobalMetricDef | undefined {
  if (!id) return undefined
  return BY_ID[id]
}

export const STRIP_METRIC_IDS: GlobalMetricId[] = [
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

function formatDuration(seconds: number): string {
  if (seconds < 60) return `${seconds < 10 ? seconds.toFixed(1) : Math.round(seconds)}s`
  const minutes = Math.floor(seconds / 60)
  const rest = Math.round(seconds % 60)
  return `${minutes}m ${rest.toString().padStart(2, '0')}s`
}