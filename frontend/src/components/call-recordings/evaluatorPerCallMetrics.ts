import { computeCallMetrics, type CallLike, type CallTurn, type PerCallMetrics } from './perCallMetricsCompute'
import { failsRule, globalMetricById } from './perCallGlobalMetrics'
import type { EvaluatorResultMetricScore } from '../../types/api'
import { shouldHideMetricScore, type MetricScoreEntry } from '../../pages/metrics/utils/metricScoreFilters'

export type PerCallLocalRow = {
  metricId: string
  label: string
  value: string
  failed: boolean
}

export type EvaluatorPerCallMetricsView = {
  call: CallLike
  computed: PerCallMetrics
  quality: PerCallLocalRow[]
  outcome: PerCallLocalRow[]
  insights: PerCallLocalRow[]
  hasAny: boolean
}

const ACOUSTIC_NAMES = new Set([
  'pitch variance',
  'jitter',
  'shimmer',
  'hnr',
  'mos score',
  'emotion category',
  'emotion confidence',
  'valence',
  'arousal',
  'speaker consistency',
  'prosody score',
])

function isUserSpeaker(speaker: string): boolean {
  const n = speaker.trim().toLowerCase()
  return n === 'speaker 1' || n === 'user' || n === 'caller' || n === 'customer'
}

function formatMetricValue(value: unknown, type?: string | null): string {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'boolean') return value ? 'true' : 'false'
  if (typeof value === 'number') {
    const t = (type || '').toLowerCase()
    if (t === 'rating' && value <= 1) return value.toFixed(2)
    if (Number.isInteger(value)) return String(value)
    return value.toFixed(2)
  }
  return String(value)
}

function isLocalMetricFailed(metric: MetricScoreEntry, display: string): boolean {
  if (typeof metric.passed === 'boolean') return !metric.passed
  const badTokens = ['angry_hangup', 'hangup', 'failed', 'unsuccessful']
  return badTokens.some((token) => display.toLowerCase().includes(token))
}

function isToolCallError(row: Record<string, unknown>): boolean {
  if (row.error) return true
  if (row.failed === true) return true
  return String(row.status ?? '').toLowerCase() === 'error'
}

function toolCallDedupeKey(row: Record<string, unknown>): string {
  const tool = String(row.tool ?? row.name ?? '')
  const ts = String(row.timestamp ?? row.ts ?? '')
  const turn = String(row.turn ?? row.turn_index ?? row.step ?? '')
  const query = String(row.query ?? '')
  return [tool, ts, turn, query].join('|')
}

function knowledgeBaseToolRecords(
  callData: Record<string, unknown>,
): Record<string, unknown>[] {
  const dedicated = callData.knowledge_base_tool_calls
  if (Array.isArray(dedicated) && dedicated.length > 0) {
    return dedicated.filter(
      (raw): raw is Record<string, unknown> => Boolean(raw) && typeof raw === 'object',
    )
  }
  const tools = callData.tool_calls
  if (!Array.isArray(tools)) return []
  return tools.filter((raw) => {
    if (!raw || typeof raw !== 'object') return false
    const row = raw as Record<string, unknown>
    const provider = String(row.provider ?? '').toLowerCase()
    const tool = String(row.tool ?? row.name ?? '').toLowerCase()
    return provider === 'knowledge_base' || tool.includes('knowledge_base')
  })
}

function pickNumericMetric(
  scores: Record<string, MetricScoreEntry>,
  pattern: RegExp,
): number | null {
  for (const entry of Object.values(scores)) {
    const name = (entry.metric_name || '').toLowerCase()
    if (!pattern.test(name)) continue
    const n = Number(entry.value)
    if (!Number.isNaN(n)) return n
  }
  return null
}

function countToolAndRagFailures(callData: Record<string, unknown> | null | undefined): {
  tool: number
  rag: number
} {
  let tool = 0
  let rag = 0
  if (!callData || typeof callData !== 'object') return { tool, rag }

  const ragSeen = new Set<string>()
  for (const row of knowledgeBaseToolRecords(callData)) {
    const key = toolCallDedupeKey(row)
    if (ragSeen.has(key)) continue
    ragSeen.add(key)
    if (isToolCallError(row)) rag += 1
  }

  const toolSeen = new Set<string>()
  const noteToolFailure = (row: Record<string, unknown>) => {
    const provider = String(row.provider ?? '').toLowerCase()
    if (provider === 'knowledge_base') return
    const key = toolCallDedupeKey(row)
    if (toolSeen.has(key)) return
    toolSeen.add(key)
    if (isToolCallError(row)) tool += 1
  }

  const rootTools = callData.tool_calls
  if (Array.isArray(rootTools)) {
    for (const raw of rootTools) {
      if (raw && typeof raw === 'object') noteToolFailure(raw as Record<string, unknown>)
    }
  }

  const messages = callData.messages
  if (Array.isArray(messages)) {
    for (const raw of messages) {
      if (!raw || typeof raw !== 'object') continue
      const msg = raw as Record<string, unknown>
      const nested = msg.tool_calls ?? msg.toolCalls
      if (!Array.isArray(nested)) continue
      for (const t of nested) {
        if (t && typeof t === 'object') noteToolFailure(t as Record<string, unknown>)
      }
    }
  }

  return { tool, rag }
}

function categorizeMetric(
  metricId: string,
  metric: MetricScoreEntry,
): 'quality' | 'outcome' | 'insight' | 'skip' {
  const name = (metric.metric_name || metricId).toLowerCase()
  if (ACOUSTIC_NAMES.has(name)) return 'skip'
  if (/^summary$|^sentiment$|^successful$/.test(name)) return 'skip'
  if (/outcome/.test(name) || metricId.toLowerCase().includes('outcome')) return 'outcome'
  if (/intent|insight/.test(name)) return 'insight'
  return 'quality'
}

export function buildEvaluatorPerCallMetricsView(
  result: {
    id: string
    agent_id?: string | null
    timestamp?: string | null
    duration_seconds?: number | null
    speaker_segments?: Array<{ speaker: string; text: string; start: number; end?: number }> | null
    metric_scores?: Record<string, EvaluatorResultMetricScore> | null
    call_data?: Record<string, unknown> | null
  },
  childMetricIds: Set<string> = new Set(),
): EvaluatorPerCallMetricsView | null {
  const segments = result.speaker_segments ?? []
  const turns: CallTurn[] = segments.map((seg, idx) => {
    const start = typeof seg.start === 'number' ? seg.start : idx
    const end = typeof seg.end === 'number' ? seg.end : start + 1
    return {
      speaker: isUserSpeaker(seg.speaker) ? 'human' : 'agent',
      text: seg.text,
      start,
      end,
    }
  })

  const callData = result.call_data
  const { tool: toolFromMessages, rag: ragFromMessages } = countToolAndRagFailures(callData)
  const scores = (result.metric_scores ?? {}) as Record<string, MetricScoreEntry>
  const closingFromScores = pickNumericMetric(scores, /closing/)
  const endedEarly =
    callData?.ended_early === true ||
    callData?.endedEarly === true ||
    String(callData?.endedReason ?? '')
      .toLowerCase()
      .includes('hangup')

  const duration =
    typeof result.duration_seconds === 'number' && result.duration_seconds > 0
      ? result.duration_seconds
      : turns.length > 0
        ? Math.max(...turns.map((t) => t.end))
        : 0

  const callLike: CallLike = {
    id: result.id,
    agentId: result.agent_id ? String(result.agent_id) : 'unknown',
    source: 'simulation',
    startedAt: result.timestamp ?? new Date().toISOString(),
    durationSeconds: duration,
    turns,
    endedEarly,
    closingQuality: closingFromScores,
  }

  let computed = computeCallMetrics(callLike)
  if (toolFromMessages > 0 || ragFromMessages > 0) {
    computed = {
      ...computed,
      toolCallFailures: Math.max(computed.toolCallFailures, toolFromMessages),
      ragCallFailures: Math.max(computed.ragCallFailures, ragFromMessages),
    }
  }

  const quality: PerCallLocalRow[] = []
  const outcome: PerCallLocalRow[] = []
  const insights: PerCallLocalRow[] = []

  for (const [metricId, metric] of Object.entries(scores)) {
    if (shouldHideMetricScore(metricId, metric, childMetricIds)) continue
    const val = metric.value
    if (val === null || val === undefined || val === '') continue
    const bucket = categorizeMetric(metricId, metric)
    if (bucket === 'skip') continue
    const display = formatMetricValue(val, metric.type)
    const row: PerCallLocalRow = {
      metricId,
      label: metric.metric_name || metricId,
      value: display,
      failed: isLocalMetricFailed(metric, display),
    }
    if (bucket === 'outcome') outcome.push(row)
    else if (bucket === 'insight') insights.push(row)
    else quality.push(row)
  }

  const hasAny =
    quality.length > 0 ||
    outcome.length > 0 ||
    insights.length > 0 ||
    duration > 0 ||
    turns.length > 0

  if (!hasAny) return null

  return { call: callLike, computed, quality, outcome, insights, hasAny }
}

export function perCallGlobalValue(computed: PerCallMetrics, metricId: string): number | null {
  const global = globalMetricById(metricId)
  if (!global) return null
  switch (global.id) {
    case 'avg_duration':
      return computed.durationSeconds
    case 'closing_quality':
      return computed.closingQuality
    case 'early_ending':
      return computed.earlyEnding
    case 'silence_duration':
      return computed.silenceAvgSeconds
    case 'longest_pause':
      return computed.silenceMaxSeconds
    case 'tool_call_failures':
      return computed.toolCallFailures
    case 'rag_call_failures':
      return computed.ragCallFailures
    case 'talk_ratio':
      return computed.talkRatio
    default:
      return null
  }
}

export function perCallGlobalFailed(computed: PerCallMetrics, metricId: string): boolean {
  const global = globalMetricById(metricId)
  if (!global) return false
  const value = perCallGlobalValue(computed, metricId)
  if (value == null) return false
  return failsRule(value, global.failRule)
}