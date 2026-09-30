export type ComponentKind = 'stt' | 'llm' | 'tts' | 's2s'
export type PipelineMode = 's2s' | 'stt_llm_tts'

export interface TraceTurnLike {
  turn_number: number
  sut_response_latency_ms?: number | null
  talk_over?: boolean
  stt_ttfb_ms?: number | null
  llm_ttfb_ms?: number | null
  tts_ttfb_ms?: number | null
  s2s_ttfb_ms?: number | null
  caller_stream_complete_at?: number | null
  sut_speech_start_at?: number | null
  sut_speech_stop_at?: number | null
  extra?: {
    was_interrupted?: boolean
    pipeline_mode?: PipelineMode
    user_text?: string
    user_utterances?: string[]
    assistant_text?: string
    is_opener?: boolean
  }
}

export function textSimilar(a: string, b: string): boolean {
  const na = a.trim().toLowerCase()
  const nb = b.trim().toLowerCase()
  if (!na || !nb) return na === nb
  if (na === nb) return true
  if (na.length >= 20 && (na.includes(nb) || nb.includes(na))) return true
  const shorter = na.length <= nb.length ? na : nb
  const longer = na.length <= nb.length ? nb : na
  return shorter.length >= 15 && longer.startsWith(shorter.slice(0, 15))
}

export interface SpanTranscriptMessage {
  role: 'user' | 'agent'
  text: string
  turn: number
  offsetMs: number
  agentRole?: string | null
  spanId: string
}

function attrString(attrs: Record<string, unknown> | undefined, key: string): string | null {
  const val = attrs?.[key]
  if (val == null) return null
  const text = String(val).trim()
  return text || null
}

function spanComponentKind(span: OtelSpanLike): ComponentKind | null {
  const op = attrString(span.attributes, 'gen_ai.operation.name')?.toLowerCase()
  const name = span.name.toLowerCase()
  if (op === 's2s' || name === 's2s') return 's2s'
  if (op === 'stt' || name === 'stt') return 'stt'
  if (op === 'tts' || name === 'tts') return 'tts'
  if (op === 'chat' || op === 'llm' || op === 'llm_response' || name === 'llm' || name === 'llm_response') {
    return 'llm'
  }
  return null
}

function spokenTextFromSpan(span: OtelSpanLike, kind: ComponentKind): string | null {
  const attrs = span.attributes ?? {}
  if (kind === 'stt') {
    return attrString(attrs, 'transcript')
  }
  if (kind === 'tts' || kind === 's2s') {
    return attrString(attrs, 'text') ?? attrString(attrs, 'output')
  }
  return attrString(attrs, 'output')
}

function isLowSignalTranscript(text: string): boolean {
  const cleaned = text.trim()
  if (!cleaned) return true
  if (cleaned.length < 3 && !cleaned.includes(' ')) return true
  return false
}

function assignTranscriptTurnNumbers(messages: SpanTranscriptMessage[]): void {
  let turn = 1
  let hasUser = false
  let hasAgent = false
  for (const message of messages) {
    if (message.role === 'user') {
      turn = !hasUser ? (hasAgent ? 2 : 1) : turn + 1
      hasUser = true
    } else if (!hasUser) {
      turn = 1
    }
    message.turn = turn
    if (message.role === 'agent') {
      hasAgent = true
    }
  }
}

function hasMatchingTts(
  spans: OtelSpanLike[],
  llmSpan: OtelSpanLike,
  text: string,
): boolean {
  const llmStart = parseUnixNano(llmSpan.start_time_unix_nano) ?? 0n
  return spans.some((other) => {
    const kind = spanComponentKind(other)
    if (kind !== 'tts' && kind !== 's2s') return false
    const spoken = spokenTextFromSpan(other, kind)
    if (!spoken || !textSimilar(spoken, text)) return false
    const ttsStart = parseUnixNano(other.start_time_unix_nano) ?? 0n
    return ttsStart >= llmStart && ttsStart - llmStart <= 30_000_000_000n
  })
}

export function buildSpanTranscriptMessages(
  spans: OtelSpanLike[],
  traceStartNs: bigint,
): SpanTranscriptMessage[] {
  const sorted = [...spans].sort((a, b) => {
    const startA = parseUnixNano(a.start_time_unix_nano) ?? 0n
    const startB = parseUnixNano(b.start_time_unix_nano) ?? 0n
    if (startA === startB) return 0
    return startA < startB ? -1 : 1
  })

  const messages: SpanTranscriptMessage[] = []
  for (const span of sorted) {
    const kind = spanComponentKind(span)
    if (!kind) continue

    let role: 'user' | 'agent' | null = null
    let text: string | null = null
    if (kind === 'stt') {
      text = spokenTextFromSpan(span, kind)
      if (!text || isLowSignalTranscript(text)) continue
      role = 'user'
    } else if (kind === 'tts' || kind === 's2s') {
      text = spokenTextFromSpan(span, kind)
      if (!text) continue
      role = 'agent'
    } else if (kind === 'llm') {
      text = spokenTextFromSpan(span, kind)
      if (!text || hasMatchingTts(sorted, span, text)) continue
      role = 'agent'
    } else {
      continue
    }

    messages.push({
      role,
      text,
      turn: 0,
      offsetMs: unixNanoOffsetMs(span.start_time_unix_nano, traceStartNs),
      agentRole: attrString(span.attributes, 'efficientai.agent_role'),
      spanId: span.span_id,
    })
  }

  assignTranscriptTurnNumbers(messages)
  return messages
}

export function collectUserTextLines(turn?: TraceTurnLike): string[] {
  const extra = turn?.extra
  if (!extra) return []
  const lines: string[] = []
  const primary = extra.user_text?.trim()
  if (primary) lines.push(primary)
  for (const utterance of extra.user_utterances ?? []) {
    const text = utterance.trim()
    if (!text) continue
    if (lines.some((existing) => textSimilar(text, existing))) continue
    lines.push(text)
  }
  return lines
}

export interface OtelSpanLike {
  trace_id?: string
  span_id: string
  parent_span_id?: string | null
  name: string
  start_time_unix_nano?: number | string | null
  end_time_unix_nano?: number | string | null
  attributes?: Record<string, unknown>
  events?: Array<{ name?: string; attributes?: Record<string, unknown> }>
}

export function parseUnixNano(value: unknown): bigint | null {
  if (value == null) return null
  if (typeof value === 'bigint') return value
  if (typeof value === 'number' && Number.isFinite(value)) {
    return BigInt(Math.trunc(value))
  }
  if (typeof value === 'string') {
    const trimmed = value.trim()
    if (!trimmed) return null
    try {
      return BigInt(trimmed)
    } catch {
      return null
    }
  }
  return null
}

export function unixNanoOffsetMs(value: unknown, traceStartNs: bigint): number {
  const start = parseUnixNano(value)
  if (start == null) return 0
  return Number((start - traceStartNs) / 1_000_000n)
}

export function resolveTraceStartNsFromSpans(spans: OtelSpanLike[]): bigint {
  let min: bigint | null = null
  for (const span of spans) {
    const start = parseUnixNano(span.start_time_unix_nano)
    if (start == null) continue
    if (min == null || start < min) min = start
  }
  return min ?? 0n
}

export const FAILURE_FLAG_LABELS: Record<string, string> = {
  no_turns: 'No turns',
  high_latency: 'High latency',
}

export const PIPELINE_MODE_LABELS: Record<PipelineMode, string> = {
  s2s: 'S2S',
  stt_llm_tts: 'STT · LLM · TTS',
}

export function formatMs(value?: number | null): string {
  if (value == null || Number.isNaN(value)) return '—'
  return `${Math.round(value)}ms`
}

export function formatCallDuration(startedAt?: string | null, endedAt?: string | null): string | null {
  if (!startedAt || !endedAt) return null
  const ms = new Date(endedAt).getTime() - new Date(startedAt).getTime()
  if (ms < 0) return null
  const sec = Math.round(ms / 1000)
  if (sec < 60) return `${sec}s`
  const m = Math.floor(sec / 60)
  const s = sec % 60
  return `${m}m ${s}s`
}

export function sessionPipelineMode(turns: TraceTurnLike[]): PipelineMode | null {
  if (turns.some((t) => t.extra?.pipeline_mode === 's2s' || (t.s2s_ttfb_ms != null && t.s2s_ttfb_ms > 0))) {
    return 's2s'
  }
  if (turns.some((t) => t.stt_ttfb_ms || t.llm_ttfb_ms || t.tts_ttfb_ms)) return 'stt_llm_tts'
  return null
}

export function isTurnIncomplete(turn: TraceTurnLike, mode: PipelineMode | null): boolean {
  const extra = turn.extra ?? {}
  if (extra.was_interrupted) {
    return false
  }
  if (extra.is_opener || (extra.assistant_text && !extra.user_text)) {
    return false
  }

  const hasData =
    turn.sut_response_latency_ms != null ||
    turn.stt_ttfb_ms != null ||
    turn.llm_ttfb_ms != null ||
    turn.tts_ttfb_ms != null ||
    turn.s2s_ttfb_ms != null
  if (!hasData) return false

  if (mode === 's2s') {
    return turn.sut_response_latency_ms != null && (turn.s2s_ttfb_ms == null || turn.s2s_ttfb_ms <= 0)
  }
  if (turn.sut_response_latency_ms == null) return false
  const missingLlm = turn.llm_ttfb_ms == null || turn.llm_ttfb_ms <= 0
  const missingStages =
    (turn.stt_ttfb_ms == null || turn.stt_ttfb_ms <= 0) &&
    (turn.tts_ttfb_ms == null || turn.tts_ttfb_ms <= 0)
  return missingLlm || missingStages
}

export function spanHasError(span: OtelSpanLike): boolean {
  const attrs = span.attributes ?? {}
  const status = String(attrs['otel.status_code'] ?? attrs['status'] ?? '').toUpperCase()
  if (status === 'ERROR') return true
  if (attrs['error'] === true) return true
  if (attrs['exception.type'] || attrs['exception.message']) return true
  return (span.events ?? []).some((e) => {
    const n = String(e.name ?? '').toLowerCase()
    return n.includes('exception') || n.includes('error')
  })
}
