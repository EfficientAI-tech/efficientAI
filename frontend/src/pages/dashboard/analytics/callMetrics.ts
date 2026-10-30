import { failsRule, type GlobalMetricId } from './globalMetrics'

/**
 * Per-call shape that maps 1:1 onto `speaker_segments` / `call_data.messages`.
 * The same functions will run against a real backend payload later.
 */
export interface CallTurn {
  speaker: 'agent' | 'human'
  text: string
  start: number
  end: number
  toolCall?: { name: string; failed: boolean; integration?: string }
  ragCall?: { query: string; failed: boolean }
}

export interface CallLike {
  id: string
  agentId: string
  source: 'simulation' | 'live'
  startedAt: string
  durationSeconds: number
  turns: CallTurn[]
  endedReason?: string
  endedEarly: boolean
  closingQuality: number
}

export interface PerCallMetrics {
  durationSeconds: number
  closingQuality: number
  endedEarly: boolean
  earlyEnding: number
  silenceAvgSeconds: number
  silenceMaxSeconds: number
  silenceMinSeconds: number
  silenceGaps: number[]
  toolCallFailures: number
  ragCallFailures: number
  agentTurns: number
  humanTurns: number
  talkRatio: number | null
}

export interface AggregatedMetric {
  count: number
  sum: number
  avg: number | null
  min: number | null
  max: number | null
  failingCount: number
  distribution: Array<{ x0: number; x1: number; count: number }>
}

export type GlobalCallValues = Record<GlobalMetricId, number>

export function computeCallMetrics(call: CallLike): PerCallMetrics {
  const gaps: number[] = []
  const ordered = [...call.turns].sort((a, b) => a.start - b.start)
  for (let i = 1; i < ordered.length; i += 1) {
    const gap = ordered[i].start - ordered[i - 1].end
    if (gap >= 0) gaps.push(gap)
  }
  const agentTurns = ordered.filter((turn) => turn.speaker === 'agent').length
  const humanTurns = ordered.filter((turn) => turn.speaker === 'human').length
  const toolCallFailures = ordered.filter((turn) => turn.toolCall?.failed).length
  const ragCallFailures = ordered.filter((turn) => turn.ragCall?.failed).length
  const silenceAvg = gaps.length ? gaps.reduce((sum, gap) => sum + gap, 0) / gaps.length : 0
  return {
    durationSeconds: call.durationSeconds,
    closingQuality: call.closingQuality,
    endedEarly: call.endedEarly,
    earlyEnding: call.endedEarly ? 1 : 0,
    silenceAvgSeconds: silenceAvg,
    silenceMaxSeconds: gaps.length ? Math.max(...gaps) : 0,
    silenceMinSeconds: gaps.length ? Math.min(...gaps) : 0,
    silenceGaps: gaps,
    toolCallFailures,
    ragCallFailures,
    agentTurns,
    humanTurns,
    talkRatio: humanTurns === 0 ? null : agentTurns / humanTurns,
  }
}

export function globalValuesFromCall(metrics: PerCallMetrics): GlobalCallValues {
  return {
    total_calls: 1,
    avg_duration: metrics.durationSeconds,
    closing_quality: metrics.closingQuality,
    early_ending: metrics.earlyEnding,
    silence_duration: metrics.silenceAvgSeconds,
    longest_pause: metrics.silenceMaxSeconds,
    tool_call_failures: metrics.toolCallFailures,
    rag_call_failures: metrics.ragCallFailures,
    talk_ratio: metrics.talkRatio ?? 0,
  }
}

export function valueForMetric(metrics: PerCallMetrics, id: GlobalMetricId): number {
  return globalValuesFromCall(metrics)[id]
}

const COUNT_IDS: GlobalMetricId[] = [
  'total_calls',
  'early_ending',
  'tool_call_failures',
  'rag_call_failures',
]

export function isCountMetric(id: GlobalMetricId): boolean {
  return COUNT_IDS.includes(id)
}

export function aggregateValues(
  values: number[],
  opts?: { failing?: boolean[]; buckets?: number; min?: number; max?: number },
): AggregatedMetric {
  const count = values.length
  if (count === 0) {
    return {
      count: 0,
      sum: 0,
      avg: null,
      min: null,
      max: null,
      failingCount: 0,
      distribution: [],
    }
  }
  const sum = values.reduce((acc, value) => acc + value, 0)
  const min = Math.min(...values)
  const max = Math.max(...values)
  const failingCount = opts?.failing
    ? opts.failing.filter(Boolean).length
    : 0
  return {
    count,
    sum,
    avg: sum / count,
    min,
    max,
    failingCount,
    distribution: histogram(values, opts?.buckets ?? 6, opts?.min, opts?.max),
  }
}

export function aggregateCalls(
  calls: CallLike[],
  id: GlobalMetricId,
  failRule?: { op: 'gt' | 'gte' | 'lt' | 'lte' | 'eq' | 'neq'; value: number },
): AggregatedMetric {
  const metrics = calls.map((call) => computeCallMetrics(call))
  if (id === 'total_calls') {
    return aggregateValues(
      [calls.length],
      { failing: [false], buckets: 1 },
    )
  }
  if (isCountMetric(id)) {
    const values = metrics.map((item) => valueForMetric(item, id))
    const failing = values.map((value) => failsRule(value, failRule))
    const empty = aggregateValues(values, { failing })
    return {
      ...empty,
      avg: values.reduce((sum, value) => sum + value, 0),
      count: calls.length,
    }
  }
  const usable = metrics.filter((item) => (id === 'talk_ratio' ? item.talkRatio != null : true))
  const values = usable.map((item) => valueForMetric(item, id))
  const failing = usable.map((item) => failsRule(valueForMetric(item, id), failRule))
  return aggregateValues(values, { failing })
}

function histogram(
  values: number[],
  buckets: number,
  forcedMin?: number,
  forcedMax?: number,
): Array<{ x0: number; x1: number; count: number }> {
  if (values.length === 0) return []
  const min = forcedMin ?? Math.min(...values)
  const max = forcedMax ?? Math.max(...values)
  const span = max - min || 1
  const counts = new Array<number>(buckets).fill(0)
  for (const value of values) {
    const index = Math.min(buckets - 1, Math.floor(((value - min) / span) * buckets))
    counts[index] += 1
  }
  return counts.map((count, index) => ({
    x0: min + (span * index) / buckets,
    x1: min + (span * (index + 1)) / buckets,
    count,
  }))
}
