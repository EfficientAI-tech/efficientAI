import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { Clock, ChevronDown, ChevronRight, ExternalLink, Radio, X } from 'lucide-react'
import { apiClient } from '../../lib/api'
import TraceTurnDetail from './TraceTurnDetail'
import TraceWaterfall from './TraceWaterfall'
import CallWaveformPlayer from './CallWaveformPlayer'
import CallEventTimeline from './CallEventTimeline'
import { buildOtelCallTimeline } from './callTimelineUtils'
import { TurnSignalBadges } from './TraceTurnBadges'
import {
  FAILURE_FLAG_LABELS,
  formatCallDuration,
  formatMs,
  isTurnIncomplete,
  PIPELINE_MODE_LABELS,
  sessionPipelineMode,
  spanHasError,
} from './traceUtils'

interface SyntheticCallTracePanelProps {
  evaluatorResultId?: string
  traceId?: string
  callShortId?: string
  onClose?: () => void
  embedded?: boolean
  hideRecording?: boolean
}

interface ComponentMeta {
  model?: string | null
  provider?: string | null
}

interface PipelineModels {
  stt?: ComponentMeta
  llm?: ComponentMeta
  tts?: ComponentMeta
  s2s?: ComponentMeta
}

interface TraceTurnExtra {
  user_text?: string
  assistant_text?: string
  agent_id?: string
  agent_role?: string
  was_interrupted?: boolean
  pipeline_mode?: 'stt_llm_tts' | 's2s'
  stt_model?: string
  llm_model?: string
  tts_model?: string
  s2s_model?: string
  stt_provider?: string
  llm_provider?: string
  tts_provider?: string
  s2s_provider?: string
}

interface TraceTurn {
  turn_number: number
  sut_response_latency_ms?: number | null
  talk_over?: boolean
  stt_ttfb_ms?: number | null
  llm_ttfb_ms?: number | null
  tts_ttfb_ms?: number | null
  s2s_ttfb_ms?: number | null
  transcript?: string | null
  extra?: TraceTurnExtra
}

interface OtelSpan {
  trace_id: string
  span_id: string
  parent_span_id?: string | null
  name: string
  start_time_unix_nano?: number | null
  end_time_unix_nano?: number | null
  attributes?: Record<string, unknown>
  events?: Array<{ name?: string; attributes?: Record<string, unknown> }>
}

type DetailTab = 'trace' | 'waterfall' | 'transcript' | 'timeline' | 'spans'
type ComponentKind = 'stt' | 'llm' | 'tts' | 's2s'

const COMPONENT_LABELS: Record<ComponentKind, string> = {
  stt: 'STT',
  llm: 'LLM',
  tts: 'TTS',
  s2s: 'S2S',
}

const TABS: Array<{ id: DetailTab; label: string }> = [
  { id: 'trace', label: 'Trace' },
  { id: 'waterfall', label: 'Waterfall' },
  { id: 'transcript', label: 'Transcript' },
  { id: 'timeline', label: 'Timeline' },
  { id: 'spans', label: 'Spans' },
]

function formatOffset(ms: number): string {
  const totalSec = ms / 1000
  const mins = Math.floor(totalSec / 60)
  const sec = totalSec % 60
  return `(+${String(mins).padStart(2, '0')}:${sec.toFixed(2).padStart(5, '0')})`
}

function shortModel(raw: unknown): string | null {
  if (raw == null) return null
  const text = String(raw).trim()
  if (!text) return null
  if (text.includes('/models/')) return text.split('/models/')[1]?.split('/')[0] ?? text
  if (text.includes('/')) return text.split('/').pop() ?? text
  return text
}

function attrStr(attrs: Record<string, unknown> | undefined, key: string): string | null {
  const val = attrs?.[key]
  if (val == null) return null
  return String(val)
}

function spanKind(span: OtelSpan): ComponentKind | null {
  const op = attrStr(span.attributes, 'gen_ai.operation.name')?.toLowerCase()
  const name = span.name.toLowerCase()
  if (op === 's2s' || name === 's2s') return 's2s'
  if (op === 'stt' || name === 'stt') return 'stt'
  if (op === 'tts' || name === 'tts') return 'tts'
  if (op === 'chat' || op === 'llm' || op === 'llm_response' || name === 'llm' || name === 'llm_response') {
    return 'llm'
  }
  return null
}

function metaFromSpan(span: OtelSpan): ComponentMeta {
  const attrs = span.attributes ?? {}
  const kind = spanKind(span)
  const model =
    shortModel(attrs['gen_ai.request.model']) ??
    shortModel(attrs['param.model']) ??
    (kind === 'tts' || kind === 'stt' ? shortModel(attrs['settings.model']) : null)
  const provider = attrStr(attrs, 'gen_ai.provider.name') ?? attrStr(attrs, 'gen_ai.system')
  return { model, provider: provider?.toLowerCase() ?? null }
}

function parseTranscript(transcript?: string | null): { user?: string; assistant?: string } {
  if (!transcript) return {}
  const userMatch = transcript.match(/^User:\s*(.+)$/m)
  const assistantMatch = transcript.match(/^Assistant:\s*(.+)$/m)
  if (userMatch || assistantMatch) {
    return { user: userMatch?.[1]?.trim(), assistant: assistantMatch?.[1]?.trim() }
  }
  if (transcript.trim().startsWith('[') || transcript.trim().startsWith('{')) return {}
  return { assistant: transcript.trim() }
}

function isS2sTurn(turn: TraceTurn): boolean {
  return turn.extra?.pipeline_mode === 's2s' || turn.s2s_ttfb_ms != null
}

function resolveTurnNumber(span: OtelSpan, byId: Map<string, OtelSpan>): number | null {
  const display = span.attributes?.['efficientai.display_turn_number']
  if (display != null) {
    const n = Number(display)
    if (!Number.isNaN(n)) return n
  }
  const visited = new Set<string>()
  let current: OtelSpan | undefined = span
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

function buildSpansByTurn(spans: OtelSpan[]): Map<number, OtelSpan[]> {
  const byId = new Map(spans.map((s) => [s.span_id, s]))
  const map = new Map<number, OtelSpan[]>()
  for (const span of spans) {
    const turnNum = resolveTurnNumber(span, byId)
    if (turnNum == null) continue
    const list = map.get(turnNum) ?? []
    list.push(span)
    map.set(turnNum, list)
  }
  return map
}

function turnMetaFromSpans(spans: OtelSpan[]): Partial<TraceTurnExtra> {
  const out: Partial<TraceTurnExtra> = {}
  for (const span of spans) {
    const kind = spanKind(span)
    if (!kind) continue
    const meta = metaFromSpan(span)
    if (meta.model && !out[`${kind}_model` as keyof TraceTurnExtra]) {
      ;(out as Record<string, string>)[`${kind}_model`] = meta.model
    }
    if (meta.provider && !out[`${kind}_provider` as keyof TraceTurnExtra]) {
      ;(out as Record<string, string>)[`${kind}_provider`] = meta.provider
    }
  }
  return out
}

function mergeTurnMeta(
  turn: TraceTurn,
  spanMeta: Partial<TraceTurnExtra>,
  sessionModels: PipelineModels,
): TraceTurnExtra {
  const extra = { ...spanMeta, ...turn.extra }
  const fill = (kind: ComponentKind) => {
    const modelKey = `${kind}_model` as keyof TraceTurnExtra
    const providerKey = `${kind}_provider` as keyof TraceTurnExtra
    if (!extra[modelKey] && sessionModels[kind]?.model) {
      ;(extra as Record<string, string>)[modelKey] = sessionModels[kind]!.model!
    }
    if (!extra[providerKey] && sessionModels[kind]?.provider) {
      ;(extra as Record<string, string>)[providerKey] = sessionModels[kind]!.provider!
    }
  }
  if (isS2sTurn(turn)) fill('s2s')
  else {
    fill('stt')
    fill('llm')
    fill('tts')
  }
  return extra
}

function turnOffsetMs(turns: TraceTurn[], turnNumber: number): number {
  let ms = 0
  for (const t of turns) {
    if (t.turn_number >= turnNumber) break
    ms += t.sut_response_latency_ms ?? 0
  }
  return ms
}

function MetricTile({
  label,
  value,
  unit,
  highlight,
}: {
  label: string
  value: string
  unit?: string
  highlight?: boolean
}) {
  return (
    <div
      className={`rounded-lg border px-3 py-3 ${
        highlight ? 'border-primary-400 bg-primary-50/40' : 'border-gray-200 bg-white'
      }`}
    >
      <p
        className={`text-[10px] font-semibold uppercase tracking-wider ${
          highlight ? 'text-primary-800/70' : 'text-gray-400'
        }`}
      >
        {label}
      </p>
      <p className="mt-1 text-xl font-bold tabular-nums text-gray-900">
        {value}
        {unit && <span className="ml-0.5 text-sm font-medium text-gray-500">{unit}</span>}
      </p>
    </div>
  )
}

function RawSpanRow({ span }: { span: OtelSpan }) {
  const [open, setOpen] = useState(false)
  const kind = spanKind(span)
  const meta = metaFromSpan(span)
  const durationMs =
    span.start_time_unix_nano != null && span.end_time_unix_nano != null
      ? Math.round((span.end_time_unix_nano - span.start_time_unix_nano) / 1_000_000)
      : null
  const hasError = spanHasError(span)

  const stageLabel = kind ? COMPONENT_LABELS[kind] : 'Other'
  const spanLabel = span.name
  const modelLabel =
    meta.model && meta.model !== span.name ? meta.model : meta.provider ?? '—'

  return (
    <div className="border-b border-gray-100 last:border-0">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="w-full text-left hover:bg-gray-50"
      >
        <div className="grid grid-cols-[3.5rem_minmax(0,1fr)_minmax(0,1.2fr)_4.5rem] items-center gap-4 px-4 py-3">
          <span className="flex items-center gap-1.5 text-xs font-medium text-gray-500">
            {open ? <ChevronDown className="h-3.5 w-3.5 shrink-0" /> : <ChevronRight className="h-3.5 w-3.5 shrink-0" />}
            <span
              className={`inline-flex rounded-md border px-1.5 py-0.5 text-[10px] font-semibold ${
                kind
                  ? 'border-primary-300 bg-primary-50/60 text-primary-800'
                  : 'border-gray-200 bg-gray-50 text-gray-600'
              }`}
            >
              {stageLabel}
            </span>
          </span>
          <span className={`truncate font-mono text-xs ${hasError ? 'text-rose-700' : 'text-gray-800'}`}>
            {spanLabel}
          </span>
          <span className="truncate font-mono text-xs text-gray-500">{modelLabel}</span>
          <span className="text-right tabular-nums text-xs font-medium text-gray-900">
            {durationMs != null ? `${durationMs}ms` : '—'}
          </span>
        </div>
      </button>
      {open && (
        <pre className="mx-4 mb-3 max-h-48 overflow-x-auto rounded-md border border-gray-100 bg-gray-50 px-3 py-2 text-xs">
          {JSON.stringify(span.attributes ?? {}, null, 2)}
        </pre>
      )}
    </div>
  )
}

export default function SyntheticCallTracePanel({
  evaluatorResultId,
  traceId,
  callShortId,
  onClose,
  embedded = false,
  hideRecording = false,
}: SyntheticCallTracePanelProps) {
  const [tab, setTab] = useState<DetailTab>('trace')
  const visibleTabs = embedded ? TABS.filter((item) => item.id !== 'transcript') : TABS

  const lookupKey = traceId ?? callShortId ?? evaluatorResultId
  const lookupMode = traceId ? 'by-trace' : callShortId ? 'by-call-short-id' : 'by-result'

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['synthetic-call-trace', lookupKey, lookupMode],
    queryFn: () => {
      if (traceId) return apiClient.getSyntheticCallTrace(traceId)
      if (callShortId) return apiClient.getSyntheticCallTraceByCallShortId(callShortId)
      return apiClient.getSyntheticCallTraceForResult(evaluatorResultId!)
    },
    enabled: Boolean(traceId || callShortId || evaluatorResultId),
    retry: false,
  })

  const otelSpans = (data?.otel_spans ?? []) as OtelSpan[]
  const spansByTurn = useMemo(() => buildSpansByTurn(otelSpans), [otelSpans])
  const turns = (data?.turns ?? []) as TraceTurn[]
  const pipelineModels = (data?.pipeline_models ?? {}) as PipelineModels
  const pipelineMode = useMemo(() => sessionPipelineMode(turns), [turns])

  const { data: linkedAgent } = useQuery({
    queryKey: ['trace-agent', data?.agent_id],
    queryFn: () => apiClient.getAgent(data!.agent_id),
    enabled: Boolean(data?.agent_id),
  })

  const traceTurnRows = useMemo(() => {
    return turns.map((turn) => {
      const turnSpans = spansByTurn.get(turn.turn_number) ?? []
      const spanMeta = turnMetaFromSpans(turnSpans)
      const extra = mergeTurnMeta(turn, spanMeta, pipelineModels)
      const models: Partial<Record<ComponentKind, string>> = {}
      for (const kind of ['stt', 'llm', 'tts', 's2s'] as const) {
        const model = extra[`${kind}_model` as keyof TraceTurnExtra] as string | undefined
        if (model) models[kind] = model
      }
      return {
        turnNumber: turn.turn_number,
        offsetMs: turnOffsetMs(turns, turn.turn_number),
        sttMs: turn.stt_ttfb_ms,
        llmMs: turn.llm_ttfb_ms,
        ttsMs: turn.tts_ttfb_ms,
        s2sMs: turn.s2s_ttfb_ms,
        totalMs: turn.sut_response_latency_ms,
        talkOver: turn.talk_over,
        interrupted: extra.was_interrupted,
        incomplete: isTurnIncomplete(turn, pipelineMode),
        models,
        spans: turnSpans.map((span) => ({
          id: span.span_id,
          kind: spanKind(span),
          name: span.name,
          model: metaFromSpan(span).model ?? undefined,
          durationMs:
            span.start_time_unix_nano != null && span.end_time_unix_nano != null
              ? Math.round((span.end_time_unix_nano - span.start_time_unix_nano) / 1_000_000)
              : null,
        })),
      }
    })
  }, [turns, spansByTurn, pipelineModels, pipelineMode])

  const transcriptMessages = useMemo(() => {
    const messages: Array<{
      role: 'user' | 'agent'
      text: string
      turn: number
      offsetMs: number
      latencyMs?: number
      talkOver?: boolean
      interrupted?: boolean
      incomplete?: boolean
    }> = []
    for (const turn of turns) {
      const spanMeta = turnMetaFromSpans(spansByTurn.get(turn.turn_number) ?? [])
      const extra = mergeTurnMeta(turn, spanMeta, pipelineModels)
      const parsed = parseTranscript(turn.transcript)
      const offset = turnOffsetMs(turns, turn.turn_number)
      const userText = extra.user_text ?? parsed.user
      const assistantText = extra.assistant_text ?? parsed.assistant
      const incomplete = isTurnIncomplete(turn, pipelineMode)
      if (userText) {
        messages.push({
          role: 'user',
          text: userText,
          turn: turn.turn_number,
          offsetMs: offset,
          talkOver: turn.talk_over,
          incomplete,
        })
      }
      if (assistantText) {
        messages.push({
          role: 'agent',
          text: assistantText,
          turn: turn.turn_number,
          offsetMs: offset + (turn.stt_ttfb_ms ?? 0),
          latencyMs: turn.sut_response_latency_ms ?? undefined,
          interrupted: extra.was_interrupted,
          incomplete,
        })
      }
    }
    return messages
  }, [turns, spansByTurn, pipelineModels, pipelineMode])

  const timelineTurnInputs = useMemo(() => {
    return turns.map((turn) => {
      const spanMeta = turnMetaFromSpans(spansByTurn.get(turn.turn_number) ?? [])
      const extra = mergeTurnMeta(turn, spanMeta, pipelineModels)
      return {
        turn_number: turn.turn_number,
        stt_ttfb_ms: turn.stt_ttfb_ms,
        llm_ttfb_ms: turn.llm_ttfb_ms,
        tts_ttfb_ms: turn.tts_ttfb_ms,
        sut_response_latency_ms: turn.sut_response_latency_ms,
        transcript: turn.transcript,
        extra: {
          user_text: extra.user_text,
          assistant_text: extra.assistant_text,
        },
      }
    })
  }, [turns, spansByTurn, pipelineModels])

  const timelineEvents = useMemo(() => {
    return buildOtelCallTimeline(otelSpans, timelineTurnInputs)
  }, [otelSpans, timelineTurnInputs])

  if (isLoading && !data) {
    return (
      <div className={`space-y-3 ${embedded ? 'p-1' : 'p-5'}`}>
        <div className="h-8 w-48 animate-pulse rounded-lg bg-gray-100" />
        <div className={`animate-pulse rounded-xl bg-gray-100 ${embedded ? 'h-32' : 'h-48'}`} />
        <div className="h-64 animate-pulse rounded-xl bg-gray-100" />
      </div>
    )
  }

  if (isError) {
    const message = (error as Error)?.message || 'Trace not available'
    if (message.includes('404') || message.toLowerCase().includes('not found')) {
      return (
        <div className={`text-sm text-gray-600 ${embedded ? 'rounded-xl border border-gray-200 bg-white p-6' : 'p-8'}`}>
          {embedded ? (
            <p>No pipeline trace for this run yet. OTLP tracing is available for internal Test Agent web sessions.</p>
          ) : (
            <>
              No trace yet. Run a Pipecat session with tracing enabled, then see{' '}
              <Link to="/calls" className="text-primary-600 hover:text-primary-800 font-medium">
                Connect Pipecat →
              </Link>
            </>
          )}
        </div>
      )
    }
    return (
      <div className={`text-sm text-red-800 bg-red-50 ${embedded ? 'rounded-xl border border-red-200 p-4' : 'p-8'}`}>
        Could not load trace: {message}
      </div>
    )
  }

  const trace = data
  if (!trace) return null

  const statusLabel = trace.status === 'finalized' ? 'closed' : trace.status
  const isDrawer = Boolean(onClose)
  const isOpen = trace.status === 'open'

  const medianMs =
    trace.response_latency_p50_ms != null ? Math.round(trace.response_latency_p50_ms) : null
  const p90Ms = trace.response_latency_p90_ms != null ? Math.round(trace.response_latency_p90_ms) : null
  const p95Ms = trace.response_latency_p95_ms != null ? Math.round(trace.response_latency_p95_ms) : null

  const startedLabel = trace.started_at
    ? new Date(trace.started_at).toLocaleString(undefined, {
        day: '2-digit',
        month: '2-digit',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
      })
    : null

  const callDuration = formatCallDuration(trace.started_at, trace.ended_at)
  const failureFlags = (trace.failure_flags ?? []) as string[]
  const agentRouteId = linkedAgent?.agent_id || linkedAgent?.id || trace.agent_id
  const agentLabel = linkedAgent?.name || (trace.agent_id ? 'Agent' : null)

  const tabContent = (
    <>
      {tab === 'trace' && (
        <div className={embedded ? 'pb-4' : 'p-5 pb-16'}>
          <TraceTurnDetail
            rows={traceTurnRows}
            pipelineModels={pipelineModels}
            componentAggregates={
              trace.component_aggregates as Record<string, { p50?: number; p90?: number; p95?: number }> | undefined
            }
          />
        </div>
      )}

      {tab === 'waterfall' && (
        <div className={embedded ? 'pb-4' : 'p-5 pb-16'}>
          {traceTurnRows.length === 0 ? (
            <p className="py-12 text-center text-sm text-gray-500">No waterfall data</p>
          ) : (
            <TraceWaterfall rows={traceTurnRows} />
          )}
        </div>
      )}

      {tab === 'transcript' && !embedded && (
        <div className="bg-gray-50/50 p-5 pb-16">
          {transcriptMessages.length === 0 ? (
            <p className="text-center py-16 text-sm text-gray-500">No transcript</p>
          ) : (
            <div className="space-y-4 max-w-2xl mx-auto">
              {transcriptMessages.map((msg, idx) => {
                const isUser = msg.role === 'user'
                return (
                  <div key={`${msg.turn}-${msg.role}-${idx}`} className={isUser ? 'flex justify-end' : 'flex justify-start'}>
                    <div className="max-w-[85%]">
                      <div
                        className={`rounded-xl px-4 py-3 ${
                          isUser
                            ? 'bg-white border border-gray-200 text-gray-900'
                            : 'bg-gray-100 border border-gray-200/80 text-gray-900'
                        }`}
                      >
                        <div className="mb-1 flex flex-wrap items-center gap-2">
                          <p className={`text-xs font-semibold ${isUser ? 'text-gray-700' : 'text-gray-600'}`}>
                            {isUser ? 'User' : 'Agent'}
                          </p>
                          <TurnSignalBadges
                            talkOver={isUser ? msg.talkOver : undefined}
                            interrupted={!isUser ? msg.interrupted : undefined}
                            incomplete={msg.incomplete}
                          />
                        </div>
                        <p className="text-sm leading-relaxed whitespace-pre-wrap">{msg.text}</p>
                      </div>
                      <p className={`text-[11px] mt-1 tabular-nums text-gray-500 ${isUser ? 'text-right' : ''}`}>
                        Turn {msg.turn} {formatOffset(msg.offsetMs)}
                        {msg.latencyMs != null && (
                          <span className="ml-2">· {formatMs(msg.latencyMs)}</span>
                        )}
                      </p>
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </div>
      )}

      {tab === 'timeline' && (
        <div className={embedded ? 'pb-4' : 'p-5 pb-16'}>
          <CallEventTimeline
            events={timelineEvents}
            emptyMessage="No pipeline events captured for this session."
          />
        </div>
      )}

      {tab === 'spans' && (
        <div className={embedded ? 'overflow-hidden rounded-xl border border-gray-200 bg-white pb-4' : 'bg-white pb-16'}>
          {otelSpans.length === 0 ? (
            <p className="py-16 text-center text-sm text-gray-500">No spans</p>
          ) : (
            <>
              <div className="grid grid-cols-[3.5rem_minmax(0,1fr)_minmax(0,1.2fr)_4.5rem] items-center gap-4 border-b border-gray-200 bg-gray-50/80 px-4 py-2.5 text-[10px] font-semibold uppercase tracking-wider text-gray-400">
                <span>Stage</span>
                <span>Span</span>
                <span>Model</span>
                <span className="text-right">Duration</span>
              </div>
              {otelSpans
                .slice()
                .sort((a, b) => (a.start_time_unix_nano ?? 0) - (b.start_time_unix_nano ?? 0))
                .map((span) => (
                  <RawSpanRow key={`${span.trace_id}-${span.span_id}`} span={span} />
                ))}
            </>
          )}
        </div>
      )}
    </>
  )

  if (embedded) {
    return (
      <div className="rounded-xl border border-gray-200 bg-white">
        <div className="flex flex-wrap gap-1 border-b border-gray-100 px-2">
          {visibleTabs.map(({ id, label }) => (
            <button
              key={id}
              type="button"
              onClick={() => setTab(id)}
              className={`shrink-0 whitespace-nowrap border-b-2 px-3 py-2 text-sm font-medium transition-colors ${
                tab === id
                  ? 'border-primary-600 text-gray-900'
                  : 'border-transparent text-gray-500 hover:text-gray-800'
              }`}
            >
              {label}
            </button>
          ))}
        </div>
        <div className="p-4">{tabContent}</div>
      </div>
    )
  }

  return (
    <div className={isDrawer ? 'flex h-full min-h-0 flex-col bg-gray-50' : 'bg-gray-50 pb-10'}>
      <div
        className={
          isDrawer
            ? 'shrink-0 overflow-x-hidden border-b border-gray-200 bg-white'
            : 'sticky top-0 z-10 overflow-x-hidden border-b border-gray-200 bg-white shadow-sm'
        }
      >
        <div className="flex items-start justify-between gap-3 border-b border-gray-100 px-5 py-4">
          <div className="min-w-0">
            <h2 className="font-mono text-xl font-bold tracking-tight text-primary-600">
              {trace.call_short_id ? `#${trace.call_short_id}` : 'Call trace'}
            </h2>
            <div className="mt-2.5 flex flex-wrap items-center gap-2">
              <span
                className={`inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium capitalize ${
                  isOpen
                    ? 'border-primary-300 bg-primary-50/60 text-primary-800'
                    : 'border-gray-200 bg-gray-50 text-gray-600'
                }`}
              >
                {isOpen && <span className="mr-1.5 inline-block h-1.5 w-1.5 rounded-full bg-primary-500" />}
                {statusLabel}
              </span>
              <span className="inline-flex items-center gap-1 rounded-full border border-gray-200 bg-white px-2.5 py-0.5 text-xs font-medium capitalize text-gray-700">
                <Radio className="h-3 w-3 text-gray-400" />
                {trace.transport ?? 'webrtc'}
              </span>
              {startedLabel && (
                <span className="inline-flex items-center gap-1 rounded-full border border-gray-200 bg-white px-2.5 py-0.5 text-xs text-gray-600">
                  <Clock className="h-3 w-3 text-gray-400" />
                  {startedLabel}
                </span>
              )}
              {callDuration && (
                <span className="inline-flex items-center rounded-full border border-gray-200 bg-white px-2.5 py-0.5 text-xs text-gray-600">
                  Duration {callDuration}
                </span>
              )}
              {pipelineMode && (
                <span className="inline-flex items-center rounded-full border border-primary-300 bg-primary-50/60 px-2.5 py-0.5 text-xs font-medium text-primary-800">
                  {PIPELINE_MODE_LABELS[pipelineMode]}
                </span>
              )}
              {failureFlags.map((flag) => (
                <span
                  key={flag}
                  className="inline-flex items-center rounded-full border border-rose-200 bg-rose-50 px-2.5 py-0.5 text-xs font-medium text-rose-800"
                >
                  {FAILURE_FLAG_LABELS[flag] ?? flag}
                </span>
              ))}
            </div>
            <div className="mt-3 flex flex-wrap items-center gap-3 text-xs">
              {agentRouteId && (
                <Link
                  to={`/agents/${agentRouteId}`}
                  className="inline-flex items-center gap-1 font-medium text-primary-600 hover:text-primary-800"
                >
                  {agentLabel}
                  <ExternalLink className="h-3 w-3" />
                </Link>
              )}
              {trace.evaluator_result_id && (
                <Link
                  to={`/results/${trace.evaluator_result_id}`}
                  className="inline-flex items-center gap-1 font-medium text-primary-600 hover:text-primary-800"
                >
                  View eval result
                  <ExternalLink className="h-3 w-3" />
                </Link>
              )}
            </div>
          </div>
          {onClose && (
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg p-2 text-gray-400 hover:bg-gray-100 hover:text-gray-700"
              aria-label="Close"
            >
              <X className="h-5 w-5" />
            </button>
          )}
        </div>

        <div className="space-y-3 px-5 py-4">
          {!hideRecording && (
            <CallWaveformPlayer
              callShortId={trace.call_short_id}
              callRecordingId={trace.call_recording_id ?? trace.call_short_id}
              evaluatorResultId={
                trace.call_short_id ? undefined : (trace.evaluator_result_id ?? evaluatorResultId)
              }
            />
          )}
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            <MetricTile
              label="Response p50"
              value={medianMs != null ? String(medianMs) : '—'}
              unit={medianMs != null ? 'ms' : undefined}
              highlight
            />
            <MetricTile
              label="P90"
              value={p90Ms != null ? String(p90Ms) : '—'}
              unit={p90Ms != null ? 'ms' : undefined}
            />
            <MetricTile
              label="P95"
              value={p95Ms != null ? String(p95Ms) : '—'}
              unit={p95Ms != null ? 'ms' : undefined}
            />
            <MetricTile label="Turns" value={String(trace.turn_count)} />
          </div>
        </div>

        <div className="flex border-t border-gray-100 bg-white px-5">
          {visibleTabs.map(({ id, label }) => (
            <button
              key={id}
              type="button"
              onClick={() => setTab(id)}
              className={`shrink-0 whitespace-nowrap border-b-2 px-4 py-3 text-sm font-medium transition-colors ${
                tab === id
                  ? 'border-primary-600 text-gray-900'
                  : 'border-transparent text-gray-500 hover:text-gray-800'
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      <div className={isDrawer ? 'min-h-0 flex-1 overflow-y-auto overscroll-contain' : undefined}>
        {tabContent}
      </div>
    </div>
  )
}
