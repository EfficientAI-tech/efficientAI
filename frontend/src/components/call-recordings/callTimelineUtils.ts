export type TimelineCategory =
  | 'call'
  | 'stt'
  | 'llm'
  | 'tts'
  | 'transport'
  | 'message'
  | 'analysis'
  | 'pipeline'
  | 's2s'

export type TimelineLevel = 'info' | 'warn' | 'error'

export interface CallTimelineEvent {
  id: string
  offsetMs: number
  category: TimelineCategory
  level: TimelineLevel
  title: string
  detail?: string
  raw?: Record<string, unknown>
  sortOrder?: number
}

const CATEGORY_LABELS: Record<TimelineCategory, string> = {
  call: 'Call',
  stt: 'Transcriber',
  llm: 'LLM',
  tts: 'Voice',
  transport: 'Transport',
  message: 'Message',
  analysis: 'Analysis',
  pipeline: 'Pipeline',
  s2s: 'S2S',
}

export function timelineCategoryLabel(category: TimelineCategory): string {
  return CATEGORY_LABELS[category] ?? category
}

function truncate(text: string, max = 120): string {
  const t = text.trim()
  if (t.length <= max) return t
  return `${t.slice(0, max)}…`
}

function parseIsoMs(value: unknown): number | null {
  if (typeof value !== 'string' || !value) return null
  const ms = Date.parse(value)
  return Number.isNaN(ms) ? null : ms
}

function isTimelineMessage(msg: unknown): msg is Record<string, unknown> {
  return msg != null && typeof msg === 'object'
}

function messageOffsetMs(msg: Record<string, unknown>, callStartMs: number | null): number {
  if (typeof msg.secondsFromStart === 'number') {
    return Math.max(0, Math.round(msg.secondsFromStart * 1000))
  }
  if (typeof msg.time === 'number') {
    if (msg.time > 1e12 && callStartMs) return Math.max(0, Math.round(msg.time - callStartMs))
    return Math.max(0, Math.round(msg.time))
  }
  return 0
}

function messageEndOffsetMs(msg: Record<string, unknown>, callStartMs: number | null): number {
  const start = messageOffsetMs(msg, callStartMs)
  const duration =
    typeof msg.duration === 'number'
      ? msg.duration
      : typeof msg.durationMs === 'number'
        ? msg.durationMs
        : typeof msg.endTime === 'number' && typeof msg.time === 'number' && msg.time <= 1e12
          ? msg.endTime - msg.time
          : 0
  return start + Math.max(0, Math.round(duration))
}

function sortTimeline(events: CallTimelineEvent[]): CallTimelineEvent[] {
  return [...events].sort((a, b) => {
    if (a.offsetMs !== b.offsetMs) return a.offsetMs - b.offsetMs
    return (a.sortOrder ?? 0) - (b.sortOrder ?? 0)
  })
}

function resolveVapiTurnNumber(turn: Record<string, unknown>, index: number): number {
  const candidates = [turn.turnNumber, turn.turn, turn.turn_number]
  for (const value of candidates) {
    const n = Number(value)
    if (!Number.isNaN(n) && n > 0) return n
  }
  return index + 1
}

export function buildVapiCallTimeline(callData: Record<string, unknown>): CallTimelineEvent[] {
  const events: CallTimelineEvent[] = []
  const raw = callData as Record<string, any>
  const artifact = raw.artifact || {}
  const perf = artifact.performanceMetrics || {}
  let seq = 0

  const callStartMs = parseIsoMs(raw.startedAt) ?? parseIsoMs(raw.createdAt)
  const callEndMs = parseIsoMs(raw.endedAt)

  const push = (partial: Omit<CallTimelineEvent, 'id'>) => {
    events.push({ ...partial, id: `vapi-${seq++}` })
  }

  const createdMs = parseIsoMs(raw.createdAt)
  if (createdMs != null && callStartMs != null && createdMs < callStartMs) {
    push({
      offsetMs: callStartMs - createdMs,
      category: 'call',
      level: 'info',
      title: 'Call queued',
      detail: raw.type ? String(raw.type) : undefined,
      sortOrder: 10,
    })
  } else if (raw.createdAt || raw.startedAt) {
    push({
      offsetMs: 0,
      category: 'call',
      level: 'info',
      title: 'Call queued',
      detail: raw.type ? String(raw.type) : undefined,
      sortOrder: 10,
    })
  }

  if (raw.startedAt) {
    push({
      offsetMs: 0,
      category: 'call',
      level: 'info',
      title: 'Call started',
      detail: raw.assistantId ? `Assistant ${String(raw.assistantId).slice(0, 8)}…` : undefined,
      sortOrder: 20,
    })
  }

  const messages = [...(artifact.messages || raw.messages || [])]
    .filter(isTimelineMessage)
    .sort(
    (a, b) => messageOffsetMs(a, callStartMs) - messageOffsetMs(b, callStartMs),
  )

  for (const msg of messages) {
    const role = String(msg.role || 'unknown')
    const offsetMs = messageOffsetMs(msg, callStartMs)
    const text = msg.message || msg.content || ''
    if (role === 'system') {
      push({
        offsetMs,
        category: 'call',
        level: 'info',
        title: 'System prompt configured',
        detail: truncate(String(text), 160),
        sortOrder: 30,
      })
      continue
    }
    if (role === 'user') {
      push({
        offsetMs,
        category: 'message',
        level: 'info',
        title: 'User spoke',
        detail: truncate(String(text)),
        sortOrder: 40,
      })
      continue
    }
    if (role === 'bot' || role === 'assistant') {
      push({
        offsetMs,
        category: 'message',
        level: 'info',
        title: 'Agent spoke',
        detail: truncate(String(text)),
        sortOrder: 50,
      })
      continue
    }
    if (role === 'tool') {
      push({
        offsetMs,
        category: 'pipeline',
        level: 'info',
        title: 'Tool result',
        detail: truncate(String(text || msg.result || JSON.stringify(msg))),
        sortOrder: 55,
      })
      continue
    }
    const toolCalls = msg.toolCalls || msg.tool_calls
    if (Array.isArray(toolCalls) && toolCalls.length > 0) {
      push({
        offsetMs,
        category: 'pipeline',
        level: 'info',
        title: 'Tool call',
        detail: truncate(
          toolCalls
            .map((tc) => {
              const item = tc as Record<string, unknown>
              const fn = item.function as Record<string, unknown> | undefined
              return String(fn?.name || item.name || 'tool')
            })
            .join(', '),
        ),
        sortOrder: 54,
      })
    }
  }

  const userMessages = messages.filter((m) => m.role === 'user')
  const turnLatencies: Record<string, unknown>[] = (perf.turnLatencies || []).filter(
    (turn: unknown): turn is Record<string, unknown> =>
      turn != null && typeof turn === 'object',
  )

  for (let index = 0; index < turnLatencies.length; index++) {
    const turn = turnLatencies[index]
    const turnNum = resolveVapiTurnNumber(turn, index)
    const userMsg = userMessages[index] as Record<string, unknown> | undefined
    const turnStartMs = userMsg ? messageEndOffsetMs(userMsg, callStartMs) : null
    const prevComplete = events.filter((e) => e.title.includes('pipeline complete')).at(-1)?.offsetMs
    const fallbackStart = turnStartMs ?? (index === 0 ? 0 : (prevComplete ?? 0) + 200)

    const stt = Number(turn.transcriberLatency ?? 0)
    const endpointing = Number(turn.endpointingLatency ?? 0)
    const llm = Number(turn.modelLatency ?? 0)
    const voice = Number(turn.voiceLatency ?? 0)
    const total = Number(turn.turnLatency ?? stt + endpointing + llm + voice)

    if (stt > 0) {
      push({
        offsetMs: fallbackStart + stt,
        category: 'stt',
        level: 'info',
        title: `Turn ${turnNum} — transcriber`,
        detail: `${stt}ms`,
        sortOrder: 60,
      })
    }
    if (endpointing > 0) {
      push({
        offsetMs: fallbackStart + stt + endpointing,
        category: 'pipeline',
        level: 'info',
        title: `Turn ${turnNum} — endpointing`,
        detail: `${endpointing}ms`,
        sortOrder: 61,
      })
    }
    if (llm > 0) {
      push({
        offsetMs: fallbackStart + stt + endpointing + llm,
        category: 'llm',
        level: 'info',
        title: `Turn ${turnNum} — LLM`,
        detail: `${llm}ms`,
        sortOrder: 62,
      })
    }
    if (voice > 0) {
      push({
        offsetMs: fallbackStart + stt + endpointing + llm + voice,
        category: 'tts',
        level: 'info',
        title: `Turn ${turnNum} — voice`,
        detail: `${voice}ms`,
        sortOrder: 63,
      })
    }
    push({
      offsetMs: fallbackStart + total,
      category: 'pipeline',
      level: 'info',
      title: `Turn ${turnNum} pipeline complete`,
      detail: `STT ${stt || '—'}ms · LLM ${llm || '—'}ms · TTS ${voice || '—'}ms · total ${total || '—'}ms`,
      raw: turn as Record<string, unknown>,
      sortOrder: 64,
    })
  }

  let callEndOffsetMs = 0
  if (callStartMs != null && callEndMs != null) {
    callEndOffsetMs = Math.max(0, callEndMs - callStartMs)
  }
  for (const msg of messages) {
    callEndOffsetMs = Math.max(callEndOffsetMs, messageEndOffsetMs(msg, callStartMs))
  }
  for (const turn of turnLatencies) {
    const idx = turnLatencies.indexOf(turn)
    const userMsg = userMessages[idx] as Record<string, unknown> | undefined
    const turnStart = userMsg ? messageEndOffsetMs(userMsg, callStartMs) : 0
    const total = Number(turn.turnLatency ?? 0)
    if (total > 0) callEndOffsetMs = Math.max(callEndOffsetMs, turnStart + total)
  }

  if (raw.endedAt || raw.status === 'ended') {
    push({
      offsetMs: callEndOffsetMs,
      category: 'call',
      level: 'info',
      title: 'Call ended',
      detail: raw.endedReason ? String(raw.endedReason).replace(/-/g, ' ') : undefined,
      sortOrder: 1000,
    })
  }

  const analysis = raw.analysis as Record<string, unknown> | undefined
  if (analysis?.summary) {
    push({
      offsetMs: callEndOffsetMs,
      category: 'analysis',
      level: 'info',
      title: 'Call summary',
      detail: truncate(String(analysis.summary)),
      sortOrder: 1010,
    })
  }
  if (analysis?.successEvaluation != null) {
    push({
      offsetMs: callEndOffsetMs,
      category: 'analysis',
      level: analysis.successEvaluation === false || analysis.successEvaluation === 'false' ? 'warn' : 'info',
      title: 'Success evaluation',
      detail: String(analysis.successEvaluation),
      sortOrder: 1011,
    })
  }

  if (typeof raw.cost === 'number') {
    push({
      offsetMs: callEndOffsetMs,
      category: 'call',
      level: 'info',
      title: 'Call cost',
      detail: `$${raw.cost.toFixed(4)}`,
      sortOrder: 1020,
    })
  }

  return sortTimeline(events)
}

export function buildRetellCallTimeline(callData: Record<string, unknown>): CallTimelineEvent[] {
  const events: CallTimelineEvent[] = []
  const raw = callData as Record<string, any>
  let seq = 0
  const push = (partial: Omit<CallTimelineEvent, 'id'>) => {
    events.push({ ...partial, id: `retell-${seq++}` })
  }

  const callStartMs = typeof raw.start_timestamp === 'number' ? raw.start_timestamp : null

  if (raw.start_timestamp) {
    push({ offsetMs: 0, category: 'call', level: 'info', title: 'Call started', sortOrder: 10 })
  }

  const latency = raw.latency as Record<string, { p50?: number; p90?: number; max?: number }> | undefined
  if (latency) {
    const parts = ['e2e', 'asr', 'llm', 'tts']
      .map((key) => {
        const bucket = latency[key]
        if (!bucket?.p50) return null
        return `${key.toUpperCase()} p50 ${bucket.p50}ms`
      })
      .filter(Boolean)
    if (parts.length > 0) {
      push({
        offsetMs: 0,
        category: 'pipeline',
        level: 'info',
        title: 'Latency overview',
        detail: parts.join(' · '),
        sortOrder: 15,
      })
    }
  }

  const transcript = raw.transcript_object || []
  for (const entry of transcript) {
    const role = String(entry.role || 'unknown')
    let offsetMs = 0
    if (entry.words?.length) {
      offsetMs = Math.round((entry.words[0].start ?? 0) * 1000)
    } else if (callStartMs && typeof entry.start === 'number') {
      offsetMs = Math.max(0, entry.start - callStartMs)
    }
    push({
      offsetMs,
      category: 'message',
      level: 'info',
      title: role === 'user' ? 'User spoke' : 'Agent spoke',
      detail: truncate(String(entry.content || '')),
      sortOrder: role === 'user' ? 40 : 50,
    })
  }

  if (raw.disconnection_reason) {
    const durationMs = typeof raw.duration_ms === 'number' ? raw.duration_ms : 0
    push({
      offsetMs: durationMs,
      category: 'call',
      level: 'info',
      title: 'Call disconnected',
      detail: String(raw.disconnection_reason).replace(/_/g, ' '),
      sortOrder: 1000,
    })
  }

  const callAnalysis = raw.call_analysis as Record<string, unknown> | undefined
  if (callAnalysis?.call_summary) {
    const durationMs = typeof raw.duration_ms === 'number' ? raw.duration_ms : 0
    push({
      offsetMs: durationMs,
      category: 'analysis',
      level: 'info',
      title: 'Call summary',
      detail: truncate(String(callAnalysis.call_summary)),
      sortOrder: 1010,
    })
  }

  if (typeof raw.call_cost === 'number' || typeof raw.cost === 'number') {
    const durationMs = typeof raw.duration_ms === 'number' ? raw.duration_ms : 0
    const cost = typeof raw.call_cost === 'number' ? raw.call_cost : raw.cost
    push({
      offsetMs: durationMs,
      category: 'call',
      level: 'info',
      title: 'Call cost',
      detail: `$${Number(cost).toFixed(4)}`,
      sortOrder: 1020,
    })
  }

  return sortTimeline(events)
}

export interface OtelSpanLike {
  span_id: string
  parent_span_id?: string | null
  name: string
  start_time_unix_nano?: number | null
  end_time_unix_nano?: number | null
  attributes?: Record<string, unknown>
  events?: Array<{ name?: string; attributes?: Record<string, unknown> }>
}

export interface OtelTurnTimelineInput {
  turn_number: number
  stt_ttfb_ms?: number | null
  llm_ttfb_ms?: number | null
  tts_ttfb_ms?: number | null
  sut_response_latency_ms?: number | null
  transcript?: string | null
  extra?: {
    user_text?: string
    assistant_text?: string
  }
}

const OTEL_SORT = {
  globalPipeline: 10,
  turnPipeline: 20,
  userMessage: 30,
  stt: 40,
  llm: 50,
  tts: 60,
  agentMessage: 70,
} as const

function spanOffsetMs(span: OtelSpanLike, traceStart: number): number {
  return span.start_time_unix_nano != null
    ? Math.round((span.start_time_unix_nano - traceStart) / 1_000_000)
    : 0
}

function spanEndOffsetMs(span: OtelSpanLike, traceStart: number): number {
  if (span.end_time_unix_nano != null) {
    return Math.round((span.end_time_unix_nano - traceStart) / 1_000_000)
  }
  return spanOffsetMs(span, traceStart)
}

function resolveOtelTurnNumber(span: OtelSpanLike, byId: Map<string, OtelSpanLike>): number | null {
  const display = span.attributes?.['efficientai.display_turn_number']
  if (display != null) {
    const n = Number(display)
    if (!Number.isNaN(n)) return n
  }
  const visited = new Set<string>()
  let current: OtelSpanLike | undefined = span
  while (current) {
    const raw = current.attributes?.['turn.number']
    if (raw != null) {
      const n = Number(raw)
      if (!Number.isNaN(n)) return n
    }
    const spanId = current.span_id
    if (spanId) {
      if (visited.has(spanId)) break
      visited.add(spanId)
    }
    const parentId = current.parent_span_id
    if (!parentId) break
    current = byId.get(parentId)
  }
  return null
}

function isPipelineSpan(span: OtelSpanLike): boolean {
  const kind = spanKindFromName(span)
  return kind === 'pipeline' || kind === 's2s'
}

function parseOtelTurnTexts(turn?: OtelTurnTimelineInput): { user?: string; assistant?: string } {
  if (!turn) return {}
  const user = turn.extra?.user_text?.trim()
  const assistant = turn.extra?.assistant_text?.trim()
  if (user || assistant) return { user, assistant }
  const transcript = turn.transcript
  if (!transcript) return {}
  const userMatch = transcript.match(/^User:\s*(.+)$/m)
  const assistantMatch = transcript.match(/^Assistant:\s*(.+)$/m)
  if (userMatch || assistantMatch) {
    return { user: userMatch?.[1]?.trim(), assistant: assistantMatch?.[1]?.trim() }
  }
  return { assistant: transcript.trim() }
}

function spanEventDetail(span: OtelSpanLike, durationMs?: number): string | undefined {
  const model =
    span.attributes?.['gen_ai.request.model'] ||
    span.attributes?.['settings.model'] ||
    span.attributes?.['model']
  return [
    durationMs != null ? `${durationMs}ms` : null,
    model ? String(model) : null,
    span.attributes?.transcript ? truncate(String(span.attributes.transcript)) : null,
  ]
    .filter(Boolean)
    .join(' · ')
}

function makeSpanTimelineEvent(
  span: OtelSpanLike,
  traceStart: number,
  seq: number,
  sortOrder: number,
): CallTimelineEvent {
  const offsetMs = spanOffsetMs(span, traceStart)
  const durationMs =
    span.start_time_unix_nano != null && span.end_time_unix_nano != null
      ? Math.round((span.end_time_unix_nano - span.start_time_unix_nano) / 1_000_000)
      : undefined
  const kind = spanKindFromName(span)
  const hasError = span.attributes?.['error.type'] != null
  return {
    id: `otel-${seq}`,
    offsetMs,
    category: kind,
    level: hasError ? 'error' : 'info',
    title: span.name || kind,
    detail: spanEventDetail(span, durationMs),
    raw: span.attributes,
    sortOrder,
  }
}

function turnAnchorMs(turnSpans: OtelSpanLike[], traceStart: number): number {
  const pipelineSpans = turnSpans.filter(isPipelineSpan)
  const pool = pipelineSpans.length ? pipelineSpans : turnSpans
  if (!pool.length) return 0
  return Math.min(...pool.map((span) => spanOffsetMs(span, traceStart)))
}

function userMessageOffsetMs(
  turnSpans: OtelSpanLike[],
  turn: OtelTurnTimelineInput | undefined,
  traceStart: number,
  anchor: number,
): number {
  const sttSpans = turnSpans.filter((span) => spanKindFromName(span) === 'stt')
  if (!sttSpans.length) return anchor
  const sttStart = Math.min(...sttSpans.map((span) => spanOffsetMs(span, traceStart)))
  const ttfb = turn?.stt_ttfb_ms ?? 0
  if (ttfb && ttfb > 0) return Math.max(0, sttStart - ttfb)
  return Math.min(anchor, sttStart)
}

function agentMessageOffsetMs(turnSpans: OtelSpanLike[], traceStart: number, anchor: number): number {
  const ttsSpans = turnSpans.filter((span) => spanKindFromName(span) === 'tts')
  const llmSpans = turnSpans.filter((span) => spanKindFromName(span) === 'llm')
  const s2sSpans = turnSpans.filter((span) => spanKindFromName(span) === 's2s')
  if (ttsSpans.length) {
    return Math.max(...ttsSpans.map((span) => spanEndOffsetMs(span, traceStart)))
  }
  if (s2sSpans.length) {
    return Math.max(...s2sSpans.map((span) => spanEndOffsetMs(span, traceStart)))
  }
  if (llmSpans.length) {
    return Math.max(...llmSpans.map((span) => spanEndOffsetMs(span, traceStart)))
  }
  return anchor
}

function spanKindFromName(span: OtelSpanLike): TimelineCategory {
  const op = String(span.attributes?.['gen_ai.operation.name'] || '').toLowerCase()
  const name = span.name.toLowerCase()
  if (op.includes('stt') || name.includes('stt')) return 'stt'
  if (op.includes('tts') || name.includes('tts')) return 'tts'
  if (op.includes('llm') || name.includes('llm')) return 'llm'
  if (op.includes('s2s') || name.includes('s2s')) return 's2s'
  if (name.includes('turn')) return 'pipeline'
  return 'pipeline'
}

export function buildOtelCallTimeline(
  spans: OtelSpanLike[],
  turns: OtelTurnTimelineInput[] = [],
): CallTimelineEvent[] {
  if (!spans.length) return []
  const starts = spans
    .map((s) => s.start_time_unix_nano)
    .filter((v): v is number => v != null)
  const traceStart = starts.length ? Math.min(...starts) : 0
  const byId = new Map(spans.map((span) => [span.span_id, span]))
  let seq = 0

  const globalSpans: OtelSpanLike[] = []
  const spansByTurn = new Map<number, OtelSpanLike[]>()
  for (const span of spans) {
    const turnNum = resolveOtelTurnNumber(span, byId)
    if (turnNum == null) {
      globalSpans.push(span)
      continue
    }
    const list = spansByTurn.get(turnNum) ?? []
    list.push(span)
    spansByTurn.set(turnNum, list)
  }

  const events: CallTimelineEvent[] = []
  const push = (partial: Omit<CallTimelineEvent, 'id'>) => {
    events.push({ ...partial, id: `otel-${seq++}` })
  }

  for (const span of [...globalSpans].sort(
    (a, b) => (a.start_time_unix_nano ?? 0) - (b.start_time_unix_nano ?? 0),
  )) {
    events.push(makeSpanTimelineEvent(span, traceStart, seq++, OTEL_SORT.globalPipeline))
    for (const ev of span.events || []) {
      push({
        offsetMs: spanOffsetMs(span, traceStart),
        category: spanKindFromName(span),
        level: 'info',
        title: ev.name || 'span event',
        detail: ev.attributes ? truncate(JSON.stringify(ev.attributes)) : undefined,
        sortOrder: OTEL_SORT.globalPipeline + 1,
      })
    }
  }

  const turnNumbers = [
    ...new Set([...turns.map((turn) => turn.turn_number), ...spansByTurn.keys()]),
  ].sort((a, b) => a - b)

  for (const turnNumber of turnNumbers) {
    const turnSpans = spansByTurn.get(turnNumber) ?? []
    const turnData = turns.find((turn) => turn.turn_number === turnNumber)
    const { user, assistant } = parseOtelTurnTexts(turnData)
    const anchor = turnAnchorMs(turnSpans, traceStart)

    for (const span of turnSpans.filter(isPipelineSpan).sort(
      (a, b) => (a.start_time_unix_nano ?? 0) - (b.start_time_unix_nano ?? 0),
    )) {
      events.push(makeSpanTimelineEvent(span, traceStart, seq++, OTEL_SORT.turnPipeline))
    }

    if (user) {
      push({
        offsetMs: userMessageOffsetMs(turnSpans, turnData, traceStart, anchor),
        category: 'message',
        level: 'info',
        title: `User spoke (turn ${turnNumber})`,
        detail: truncate(user),
        sortOrder: OTEL_SORT.userMessage,
      })
    }

    let ttsOrder = 0
    for (const span of [...turnSpans]
      .filter((item) => !isPipelineSpan(item))
      .sort((a, b) => (a.start_time_unix_nano ?? 0) - (b.start_time_unix_nano ?? 0))) {
      const kind = spanKindFromName(span)
      const sortOrder =
        kind === 'stt'
          ? OTEL_SORT.stt
          : kind === 'llm'
            ? OTEL_SORT.llm
            : kind === 'tts' || kind === 's2s'
              ? OTEL_SORT.tts + ttsOrder++
              : OTEL_SORT.turnPipeline + 1
      events.push(makeSpanTimelineEvent(span, traceStart, seq++, sortOrder))
      for (const ev of span.events || []) {
        push({
          offsetMs: spanOffsetMs(span, traceStart),
          category: kind,
          level: 'info',
          title: ev.name || 'span event',
          detail: ev.attributes ? truncate(JSON.stringify(ev.attributes)) : undefined,
          sortOrder: sortOrder + 1,
        })
      }
    }

    if (assistant) {
      push({
        offsetMs: agentMessageOffsetMs(turnSpans, traceStart, anchor),
        category: 'message',
        level: 'info',
        title: `Agent spoke (turn ${turnNumber})`,
        detail: truncate(assistant),
        sortOrder: OTEL_SORT.agentMessage,
      })
    }
  }

  return sortTimeline(events)
}
