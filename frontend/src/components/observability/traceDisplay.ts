import type { ObservabilityCallTrace, ObservabilityTraceSpan } from '../../types/api'

export type SpanTreeNode = ObservabilityTraceSpan & {
  children: SpanTreeNode[]
}

const SPAN_LABELS: Record<string, string> = {
  conversation: 'Call',
  turn: 'User turn',
  stt: 'STT',
  llm: 'LLM inference',
  tts: 'TTS',
  s2s: 'Speech-to-speech',
  tool_call: 'Tool call',
  endpointing: 'Endpointing',
}

const ELEVENLABS_SPAN_LABELS: Record<string, string> = {
  'elevenlabs.conversation': 'ElevenLabs conversation',
  'elevenlabs.recv.user_transcript': 'User transcript',
  'elevenlabs.recv.agent_response': 'Agent response',
}

const HIGHLIGHT_ATTR_KEYS = [
  'turn.number',
  'turn.duration_seconds',
  'turn.was_interrupted',
  'turn.user_transcript',
  'turn.agent_transcript',
  'conversation.id',
  'conversation.type',
  'stt.transcript',
  'transcript',
  'gen_ai.system',
  'gen_ai.request.model',
  'gen_ai.response.model',
  'llm.model',
  'tts.voice',
  'function.name',
]

export function buildSpanTree(trace: ObservabilityCallTrace): SpanTreeNode[] {
  const spans = trace.spans || []
  const byId = new Map<string, SpanTreeNode>()
  const children = new Map<string, SpanTreeNode[]>()

  spans.forEach((span) => {
    if (!span.span_id) return
    byId.set(span.span_id, { ...span, children: [] })
  })

  spans.forEach((span) => {
    if (!span.span_id) return
    const parent = span.parent_span_id || '__root__'
    const list = children.get(parent) || []
    const node = byId.get(span.span_id)
    if (node) list.push(node)
    children.set(parent, list)
  })

  const roots =
    children.get('__root__') ||
    spans
      .filter((span) => span.span_id && (!span.parent_span_id || !byId.has(span.parent_span_id)))
      .map((span) => byId.get(span.span_id!)!)
      .filter(Boolean)

  const attachChildren = (node: SpanTreeNode) => {
    if (!node.span_id) {
      node.children = []
      return
    }
    const kids = children.get(node.span_id) || []
    node.children = [...kids].sort((a, b) => (a.start_time || 0) - (b.start_time || 0))
    node.children.forEach(attachChildren)
  }

  const sortedRoots = [...roots].sort((a, b) => (a.start_time || 0) - (b.start_time || 0))
  sortedRoots.forEach(attachChildren)
  return sortedRoots
}

export function flattenSpanTree(nodes: SpanTreeNode[]): ObservabilityTraceSpan[] {
  const out: ObservabilityTraceSpan[] = []
  const walk = (list: SpanTreeNode[]) => {
    list.forEach((node) => {
      out.push(node)
      walk(node.children)
    })
  }
  walk(nodes)
  return out
}

export function getSpanDisplayName(span: ObservabilityTraceSpan): string {
  const estimatedSuffix = span.attributes?.['metric.estimated'] === true ? ' (estimated)' : ''
  if (isElevenLabsSpan(span)) {
    if (span.name in ELEVENLABS_SPAN_LABELS) return `${ELEVENLABS_SPAN_LABELS[span.name]}${estimatedSuffix}`
    if (span.name.startsWith('elevenlabs.tool.')) {
      const toolName = span.name.replace('elevenlabs.tool.', '')
      return `Tool call (${toolName})${estimatedSuffix}`
    }
    if (span.name.startsWith('elevenlabs.metric.')) {
      const metric = span.name.replace('elevenlabs.metric.', '').toUpperCase()
      return `${metric} metrics${estimatedSuffix}`
    }
    return `${span.name}${estimatedSuffix}`
  }
  const base = SPAN_LABELS[span.name] || span.name
  if (span.name === 'turn') {
    const role = String(span.attributes?.['turn.role'] || '').toLowerCase()
    const rolePrefix = role === 'agent' ? 'Agent turn' : 'User turn'
    const turnNumber = span.attributes?.['turn.number']
    if (turnNumber !== undefined && turnNumber !== null) {
      return `${rolePrefix} ${turnNumber}`
    }
    return rolePrefix
  }
  return `${base}${estimatedSuffix}`
}

export function formatDuration(ms: number | null | undefined, style: 'auto' | 'ms' | 'seconds' = 'auto'): string {
  const value = ms ?? 0
  if (style === 'ms') return `${Math.round(value)} ms`
  if (style === 'seconds' || value >= 1000) {
    const seconds = value / 1000
    if (seconds >= 10) return `${seconds.toFixed(1)}s`
    return `${seconds.toFixed(2)}s`
  }
  return `${Math.round(value)} ms`
}

export function truncateSpanId(spanId: string | undefined | null, head = 6, tail = 4): string {
  if (!spanId) return '—'
  if (spanId.length <= head + tail + 1) return spanId
  return `${spanId.slice(0, head)}…${spanId.slice(-tail)}`
}

export function formatSpanTimestamp(startTimeMs: number | null | undefined): string {
  if (!startTimeMs) return '—'
  return new Date(startTimeMs).toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    second: '2-digit',
  })
}

export function getServiceName(span: ObservabilityTraceSpan): string {
  const attrs = span.attributes || {}
  const candidates = [
    attrs['service.name'],
    attrs['service_name'],
    attrs['gen_ai.system'],
  ]
  for (const value of candidates) {
    if (typeof value === 'string' && value.trim()) return value
  }
  if (isElevenLabsSpan(span)) return 'elevenlabs'
  return 'efficientai'
}

export function getSpanKind(span: ObservabilityTraceSpan): string {
  const kind = span.attributes?.['span.kind'] ?? span.attributes?.['span_kind']
  if (typeof kind === 'string' && kind.trim()) return kind
  return 'Internal'
}

export function getStatusLabel(status: string | null | undefined): string {
  if (!status) return 'Unset'
  const normalized = String(status).toLowerCase()
  if (normalized.includes('ok') || normalized === '1') return 'OK'
  if (normalized.includes('error') || normalized === '2') return 'Error'
  return String(status)
}

function collectDescendants(spanId: string, allSpans: ObservabilityTraceSpan[]): ObservabilityTraceSpan[] {
  const children = allSpans.filter((s) => s.parent_span_id === spanId)
  return children.flatMap((child) => {
    if (!child.span_id) return [child]
    return [child, ...collectDescendants(child.span_id, allSpans)]
  })
}

export function enrichSpanAttributes(
  span: ObservabilityTraceSpan,
  allSpans: ObservabilityTraceSpan[],
): Record<string, unknown> {
  const attrs = { ...(span.attributes || {}) }

  if (span.name === 'turn' && span.span_id) {
    const descendants = collectDescendants(span.span_id, allSpans)
    if (!attrs['turn.user_transcript']) {
      const stt = descendants.find((s) => s.name === 'stt')
      const transcript =
        stt?.attributes?.['stt.transcript'] ?? stt?.attributes?.['transcript']
      if (typeof transcript === 'string' && transcript.trim()) {
        attrs['turn.user_transcript'] = transcript
      }
    }
    if (!attrs['turn.agent_transcript']) {
      const llm = descendants.find((s) => s.name === 'llm')
      const response =
        llm?.attributes?.['gen_ai.response.text'] ??
        llm?.attributes?.['llm.response'] ??
        llm?.attributes?.['output']
      if (typeof response === 'string' && response.trim()) {
        attrs['turn.agent_transcript'] = response
      }
    }
  }

  return attrs
}

export function partitionAttributes(attrs: Record<string, unknown>): {
  highlighted: Array<[string, unknown]>
  rest: Array<[string, unknown]>
} {
  const entries = Object.entries(attrs)
  const highlighted: Array<[string, unknown]> = []
  const rest: Array<[string, unknown]> = []
  const seen = new Set<string>()

  for (const key of HIGHLIGHT_ATTR_KEYS) {
    if (key in attrs) {
      highlighted.push([key, attrs[key]])
      seen.add(key)
    }
  }

  entries
    .filter(([key]) => !seen.has(key))
    .sort(([a], [b]) => a.localeCompare(b))
    .forEach(([key, value]) => rest.push([key, value]))

  return { highlighted, rest }
}

export function computeTraceStats(spans: ObservabilityTraceSpan[]) {
  const isEstimatedMetric = (span: ObservabilityTraceSpan) =>
    span.attributes?.['metric.estimated'] === true
  const isTurnScopedMetric = (span: ObservabilityTraceSpan) => {
    const scope = span.attributes?.['metric.scope']
    return typeof scope === 'string' && scope.startsWith('turn_')
  }

  const sumByMatcher = (matcher: (span: ObservabilityTraceSpan) => boolean) =>
    spans
      .filter((s) => !isEstimatedMetric(s) && !isTurnScopedMetric(s) && matcher(s))
      .reduce((sum, s) => sum + (s.duration_ms || 0), 0)

  const llmMs = sumByMatcher(
    (s) =>
      s.name === 'llm' ||
      s.name === 'elevenlabs.metric.llm' ||
      s.name === 'retell-metric-llm' ||
      s.name === 'vapi-metric-llm' ||
      s.attributes?.['metric.layer'] === 'llm',
  )
  const sttMs = sumByMatcher(
    (s) =>
      s.name === 'stt' ||
      s.name === 'elevenlabs.metric.asr' ||
      s.name === 'retell-metric-stt' ||
      s.name === 'vapi-metric-stt' ||
      s.attributes?.['metric.layer'] === 'stt',
  )
  const ttsMs = sumByMatcher(
    (s) =>
      s.name === 'tts' ||
      s.name === 'elevenlabs.metric.tts' ||
      s.name === 'retell-metric-tts' ||
      s.name === 'vapi-metric-tts' ||
      s.attributes?.['metric.layer'] === 'tts',
  )
  const totalMs = Math.max(
    ...spans.map((s) => s.duration_ms || 0),
    llmMs + sttMs + ttsMs,
    1,
  )

  const root = spans.find((s) => s.name === 'conversation') || spans[0]
  const traceDurationMs = root?.duration_ms ?? totalMs

  return { llmMs, sttMs, ttsMs, totalMs: traceDurationMs || totalMs }
}

export function formatAttributeValue(value: unknown): string {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'string') return value
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  try {
    return JSON.stringify(value)
  } catch {
    return String(value)
  }
}

/** Offset from trace/call start, e.g. "+0:12" or "+1:05.3" */
export function formatRelativeOffset(
  offsetMs: number | null | undefined,
  style: 'short' | 'long' = 'short',
): string {
  if (offsetMs === null || offsetMs === undefined || Number.isNaN(offsetMs)) return '—'
  const totalSec = Math.max(0, offsetMs / 1000)
  const mins = Math.floor(totalSec / 60)
  const secs = totalSec % 60
  if (style === 'long') {
    return mins > 0 ? `+${mins}:${secs.toFixed(1).padStart(4, '0')}` : `+${secs.toFixed(1)}s`
  }
  if (mins > 0) {
    return `+${mins}:${Math.floor(secs).toString().padStart(2, '0')}`
  }
  return `+${secs.toFixed(secs >= 10 ? 0 : 1)}s`
}

export function getTraceRootStartMs(spans: ObservabilityTraceSpan[]): number {
  const values = spans.map((s) => s.start_time || 0).filter((v) => v > 0)
  return values.length ? Math.min(...values) : 0
}

const PIPELINE_SPAN_NAMES = new Set(['stt', 'llm', 'tts', 's2s', 'tool_call', 'endpointing'])

export function getDefaultCollapsedSpanIds(nodes: SpanTreeNode[]): Set<string> {
  const collapsed = new Set<string>()
  const walk = (list: SpanTreeNode[]) => {
    list.forEach((node) => {
      if (
        node.span_id &&
        (PIPELINE_SPAN_NAMES.has(node.name) || node.name.startsWith('elevenlabs.tool.'))
      ) {
        collapsed.add(node.span_id)
      }
      walk(node.children)
    })
  }
  walk(nodes)
  return collapsed
}

export function getAllCollapsibleSpanIds(nodes: SpanTreeNode[]): string[] {
  const ids: string[] = []
  const walk = (list: SpanTreeNode[]) => {
    list.forEach((node) => {
      if (node.span_id && node.children.length > 0) ids.push(node.span_id)
      walk(node.children)
    })
  }
  walk(nodes)
  return ids
}

export function getTurnPreview(span: ObservabilityTraceSpan, allSpans: ObservabilityTraceSpan[]): string | null {
  if (isElevenLabsTurnSpan(span)) {
    const text =
      span.attributes?.['elevenlabs.user.text'] ??
      span.attributes?.['elevenlabs.agent.text'] ??
      span.attributes?.['text']
    if (typeof text === 'string' && text.trim()) {
      const clipped = text.trim()
      return clipped.length > 72 ? `${clipped.slice(0, 72)}…` : clipped
    }
  }
  const enriched = enrichSpanAttributes(span, allSpans)
  const user = enriched['turn.user_transcript']
  if (typeof user === 'string' && user.trim()) {
    return user.trim().length > 72 ? `${user.trim().slice(0, 72)}…` : user.trim()
  }
  const agent = enriched['turn.agent_transcript']
  if (typeof agent === 'string' && agent.trim()) {
    return agent.trim().length > 72 ? `${agent.trim().slice(0, 72)}…` : agent.trim()
  }
  return null
}

export interface SpanSummaryLine {
  label: string
  value: string
}

export function getSpanSummaryLines(
  span: ObservabilityTraceSpan,
  allSpans: ObservabilityTraceSpan[],
): SpanSummaryLine[] {
  const attrs = enrichSpanAttributes(span, allSpans)
  const lines: SpanSummaryLine[] = []

  if (isElevenLabsTurnSpan(span)) {
    const label = span.name.includes('user') ? 'User said' : 'Agent replied'
    const text =
      attrs['elevenlabs.user.text'] ??
      attrs['elevenlabs.agent.text'] ??
      attrs['text']
    if (typeof text === 'string' && text.trim()) lines.push({ label, value: text.trim() })
  } else if (span.name === 'turn') {
    const user = attrs['turn.user_transcript']
    const agent = attrs['turn.agent_transcript']
    if (typeof user === 'string' && user.trim()) lines.push({ label: 'User said', value: user.trim() })
    if (typeof agent === 'string' && agent.trim()) lines.push({ label: 'Agent replied', value: agent.trim() })
    if (attrs['turn.was_interrupted']) lines.push({ label: 'Interrupted', value: 'Yes' })
  } else if (span.name === 'stt') {
    const transcript = attrs['stt.transcript'] ?? attrs['transcript']
    if (typeof transcript === 'string' && transcript.trim()) {
      lines.push({ label: 'Transcript', value: transcript.trim() })
    }
  } else if (span.name === 'llm') {
    const model = attrs['gen_ai.request.model'] ?? attrs['gen_ai.response.model'] ?? attrs['llm.model']
    if (typeof model === 'string') lines.push({ label: 'Model', value: model })
    const inputTokens = attrs['gen_ai.usage.input_tokens']
    const outputTokens = attrs['gen_ai.usage.output_tokens']
    if (inputTokens !== undefined || outputTokens !== undefined) {
      lines.push({
        label: 'Tokens',
        value: `${inputTokens ?? '?'} in / ${outputTokens ?? '?'} out`,
      })
    }
    const response =
      attrs['gen_ai.response.text'] ?? attrs['llm.response'] ?? attrs['output']
    if (typeof response === 'string' && response.trim()) {
      const preview = response.trim().length > 200 ? `${response.trim().slice(0, 200)}…` : response.trim()
      lines.push({ label: 'Response', value: preview })
    }
  } else if (span.name === 'tts') {
    const voice = attrs['tts.voice']
    if (typeof voice === 'string') lines.push({ label: 'Voice', value: voice })
  } else if (span.name === 'tool_call') {
    const fn = attrs['function.name']
    if (typeof fn === 'string') lines.push({ label: 'Function', value: fn })
  }

  return lines
}

export function findTurnSpanForTranscriptIndex(
  turnIndex: number,
  allSpans: ObservabilityTraceSpan[],
): ObservabilityTraceSpan | null {
  const turnSpans = allSpans
    .filter((s) => (s.name === 'turn' || isElevenLabsTurnSpan(s)) && s.span_id)
    .sort((a, b) => (a.start_time || 0) - (b.start_time || 0))
  if (turnSpans.length === 0) return null
  const idx = Math.min(turnIndex, turnSpans.length - 1)
  return turnSpans[idx] ?? null
}

export function findNearestTurnSpan(
  audioOffsetSec: number,
  callStartMs: number | null,
  rootStartMs: number,
  allSpans: ObservabilityTraceSpan[],
): ObservabilityTraceSpan | null {
  const turnSpans = allSpans
    .filter((s) => (s.name === 'turn' || isElevenLabsTurnSpan(s)) && s.span_id && s.start_time)
    .sort((a, b) => (a.start_time || 0) - (b.start_time || 0))
  if (turnSpans.length === 0) return null

  const anchorMs = callStartMs && callStartMs > 0 ? callStartMs : rootStartMs
  const targetMs = anchorMs + audioOffsetSec * 1000

  let nearest = turnSpans[0]
  let nearestDist = Math.abs((nearest.start_time || 0) - targetMs)
  for (const turn of turnSpans) {
    const dist = Math.abs((turn.start_time || 0) - targetMs)
    if (dist < nearestDist) {
      nearest = turn
      nearestDist = dist
    }
  }
  return nearest
}

export function isElevenLabsSpan(span: ObservabilityTraceSpan): boolean {
  const provider = span.attributes?.['trace.provider']
  return provider === 'elevenlabs' || span.name.startsWith('elevenlabs.')
}

export function isElevenLabsTurnSpan(span: ObservabilityTraceSpan): boolean {
  return (
    span.name === 'elevenlabs.recv.user_transcript' ||
    span.name === 'elevenlabs.recv.agent_response'
  )
}

export function spanOffsetSec(
  span: ObservabilityTraceSpan,
  callStartMs: number | null,
  rootStartMs: number,
): number | null {
  if (!span.start_time) return null
  const anchorMs = callStartMs && callStartMs > 0 ? callStartMs : rootStartMs
  return Math.max(0, (span.start_time - anchorMs) / 1000)
}
