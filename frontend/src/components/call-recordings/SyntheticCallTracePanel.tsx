import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import {
  Activity,
  ChevronDown,
  ChevronRight,
  Clock,
  Cpu,
  Mic,
  MessageSquare,
  Radio,
  Volume2,
  X,
  Zap,
} from 'lucide-react'
import { apiClient } from '../../lib/api'

interface SyntheticCallTracePanelProps {
  evaluatorResultId?: string
  traceId?: string
  callShortId?: string
  onClose?: () => void
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
  events?: Array<Record<string, unknown>>
}

type DetailTab = 'conversation' | 'latency' | 'raw'
type ComponentKind = 'stt' | 'llm' | 'tts' | 's2s'

const COMPONENT_STYLES: Record<
  ComponentKind,
  { label: string; bar: string; text: string; bg: string; border: string; icon: typeof Mic }
> = {
  stt: {
    label: 'STT',
    bar: 'bg-sky-500',
    text: 'text-sky-700',
    bg: 'bg-sky-50',
    border: 'border-sky-200',
    icon: Mic,
  },
  llm: {
    label: 'LLM',
    bar: 'bg-violet-500',
    text: 'text-violet-700',
    bg: 'bg-violet-50',
    border: 'border-violet-200',
    icon: Cpu,
  },
  tts: {
    label: 'TTS',
    bar: 'bg-emerald-500',
    text: 'text-emerald-700',
    bg: 'bg-emerald-50',
    border: 'border-emerald-200',
    icon: Volume2,
  },
  s2s: {
    label: 'S2S',
    bar: 'bg-fuchsia-500',
    text: 'text-fuchsia-700',
    bg: 'bg-fuchsia-50',
    border: 'border-fuchsia-200',
    icon: Radio,
  },
}

function formatMs(value?: number | null): string {
  if (value == null || Number.isNaN(value)) return '—'
  return `${Math.round(value)}ms`
}

function latencyTone(ms?: number | null): string {
  if (ms == null) return 'text-gray-900'
  if (ms < 800) return 'text-emerald-700'
  if (ms < 2000) return 'text-amber-700'
  return 'text-rose-700'
}

function shortModel(raw: unknown): string | null {
  if (raw == null) return null
  const text = String(raw).trim()
  if (!text) return null
  if (text.includes('/models/')) {
    return text.split('/models/')[1]?.split('/')[0] ?? text
  }
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
  const provider =
    attrStr(attrs, 'gen_ai.provider.name') ?? attrStr(attrs, 'gen_ai.system')
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

function providerLabel(provider?: string | null, model?: string | null): string {
  if (provider && model) return `${provider} · ${model}`
  return provider ?? model ?? '—'
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
  if (isS2sTurn(turn)) {
    fill('s2s')
  } else {
    fill('stt')
    fill('llm')
    fill('tts')
  }
  return extra
}

function PipelineModelsBar({ models }: { models: PipelineModels }) {
  const items = (['stt', 'llm', 'tts', 's2s'] as const)
    .map((key) => ({ key, meta: models[key], ...COMPONENT_STYLES[key] }))
    .filter((item) => item.meta?.model || item.meta?.provider)

  if (items.length === 0) return null

  return (
    <div className="px-5 py-3 border-b border-gray-100 bg-slate-50/60 shrink-0">
      <p className="text-[10px] font-semibold uppercase tracking-wider text-gray-400 mb-2.5">
        Voice pipeline models
      </p>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
        {items.map(({ key, meta, label, icon: Icon, bg, border, text }) => (
          <div key={key} className={`rounded-lg border ${border} ${bg} px-3 py-2.5`}>
            <div className="flex items-center gap-2 mb-1">
              <Icon className={`w-3.5 h-3.5 ${text}`} />
              <span className={`text-[10px] font-bold uppercase tracking-wider ${text}`}>{label}</span>
            </div>
            <p className="text-xs font-semibold text-gray-900 truncate" title={meta?.model ?? undefined}>
              {meta?.model ?? '—'}
            </p>
            {meta?.provider && (
              <p className="text-[11px] text-gray-500 truncate mt-0.5">{meta.provider}</p>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

interface WaterfallSegment {
  kind: ComponentKind
  ms: number
}

function buildWaterfallSegments(turn: TraceTurn): WaterfallSegment[] {
  if (isS2sTurn(turn)) {
    const ms = turn.s2s_ttfb_ms ?? turn.sut_response_latency_ms
    return ms != null ? [{ kind: 's2s', ms }] : []
  }
  const segments: WaterfallSegment[] = []
  if (turn.stt_ttfb_ms != null) segments.push({ kind: 'stt', ms: turn.stt_ttfb_ms })
  if (turn.llm_ttfb_ms != null) segments.push({ kind: 'llm', ms: turn.llm_ttfb_ms })
  if (turn.tts_ttfb_ms != null) segments.push({ kind: 'tts', ms: turn.tts_ttfb_ms })
  return segments
}

function LatencyWaterfall({
  turn,
  extra,
  compact,
}: {
  turn: TraceTurn
  extra: TraceTurnExtra
  compact?: boolean
}) {
  const segments = buildWaterfallSegments(turn)
  const total = segments.reduce((sum, s) => sum + s.ms, 0) || turn.sut_response_latency_ms || 0

  if (segments.length === 0) {
    return (
      <div className="text-xs text-gray-400 italic">
        No component timing{turn.sut_response_latency_ms != null ? ` · total ${formatMs(turn.sut_response_latency_ms)}` : ''}
      </div>
    )
  }

  return (
    <div className={compact ? 'space-y-2' : 'space-y-3'}>
      <div className="flex h-7 rounded-md overflow-hidden bg-gray-100 ring-1 ring-gray-200/80">
        {segments.map((seg, idx) => {
          const pct = total > 0 ? (seg.ms / total) * 100 : 100 / segments.length
          const style = COMPONENT_STYLES[seg.kind]
          const model = extra[`${seg.kind}_model` as keyof TraceTurnExtra] as string | undefined
          const provider = extra[`${seg.kind}_provider` as keyof TraceTurnExtra] as string | undefined
          return (
            <div
              key={`${seg.kind}-${idx}`}
              className={`${style.bar} relative group min-w-[2rem] flex items-center justify-center`}
              style={{ width: `${Math.max(pct, 8)}%` }}
              title={`${style.label}: ${formatMs(seg.ms)} · ${providerLabel(provider, model)}`}
            >
              <span className="text-[10px] font-bold text-white/90 drop-shadow-sm px-1 truncate">
                {formatMs(seg.ms)}
              </span>
            </div>
          )
        })}
      </div>

      <div
        className="grid gap-2"
        style={{ gridTemplateColumns: `repeat(${segments.length}, minmax(0, 1fr))` }}
      >
        {segments.map((seg, idx) => {
          const style = COMPONENT_STYLES[seg.kind]
          const Icon = style.icon
          const model = extra[`${seg.kind}_model` as keyof TraceTurnExtra] as string | undefined
          const provider = extra[`${seg.kind}_provider` as keyof TraceTurnExtra] as string | undefined
          return (
            <div
              key={`${seg.kind}-detail-${idx}`}
              className={`rounded-md border ${style.border} ${style.bg} px-2.5 py-2`}
            >
              <div className="flex items-center gap-1.5 mb-0.5">
                <Icon className={`w-3 h-3 ${style.text}`} />
                <span className={`text-[10px] font-bold uppercase ${style.text}`}>{style.label}</span>
                <span className="ml-auto text-xs font-semibold tabular-nums text-gray-900">
                  {formatMs(seg.ms)}
                </span>
              </div>
              <p className="text-[11px] font-medium text-gray-800 truncate" title={model}>
                {model ?? '—'}
              </p>
              {provider && <p className="text-[10px] text-gray-500 truncate">{provider}</p>}
            </div>
          )
        })}
      </div>
    </div>
  )
}

function RawSpanRow({ span }: { span: OtelSpan }) {
  const [open, setOpen] = useState(false)
  const kind = spanKind(span)
  const meta = metaFromSpan(span)
  const ttfb = span.attributes?.['metrics.ttfb']
  const durationMs =
    span.start_time_unix_nano != null && span.end_time_unix_nano != null
      ? Math.round((span.end_time_unix_nano - span.start_time_unix_nano) / 1_000_000)
      : null
  const style = kind ? COMPONENT_STYLES[kind] : null

  return (
    <div className="rounded-lg border border-gray-200 bg-white text-xs overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center gap-2 px-3 py-2.5 text-left hover:bg-gray-50"
      >
        {open ? <ChevronDown className="w-3.5 h-3.5 text-gray-400 shrink-0" /> : <ChevronRight className="w-3.5 h-3.5 text-gray-400 shrink-0" />}
        {style && (
          <span className={`text-[10px] font-bold uppercase px-1.5 py-0.5 rounded ${style.bg} ${style.text}`}>
            {style.label}
          </span>
        )}
        {!style && <span className="font-medium text-gray-600">{span.name}</span>}
        <span className="text-gray-500 truncate hidden sm:inline">{meta.model ?? ''}</span>
        <span className="ml-auto tabular-nums text-gray-600 shrink-0 font-medium">
          {durationMs != null ? `${durationMs}ms` : '—'}
          {ttfb != null && <span className="text-gray-400 font-normal"> · ttfb {Math.round(Number(ttfb) * 1000)}ms</span>}
        </span>
      </button>
      {open && (
        <pre className="text-[10px] font-mono bg-slate-50 border-t border-slate-100 px-3 py-2 overflow-x-auto max-h-48 whitespace-pre-wrap">
          {JSON.stringify(span.attributes ?? {}, null, 2)}
        </pre>
      )}
    </div>
  )
}

function TurnCard({
  turn,
  spans,
  sessionModels,
}: {
  turn: TraceTurn
  spans: OtelSpan[]
  sessionModels: PipelineModels
}) {
  const [showSpans, setShowSpans] = useState(false)
  const spanMeta = useMemo(() => turnMetaFromSpans(spans), [spans])
  const extra = useMemo(() => mergeTurnMeta(turn, spanMeta, sessionModels), [turn, spanMeta, sessionModels])
  const parsed = parseTranscript(turn.transcript)
  const userText = extra.user_text ?? parsed.user
  const assistantText = extra.assistant_text ?? parsed.assistant
  const agent = extra.agent_role ?? extra.agent_id
  const interrupted = Boolean(extra.was_interrupted)
  const componentSpans = spans
    .filter((s) => spanKind(s) != null)
    .sort((a, b) => (a.start_time_unix_nano ?? 0) - (b.start_time_unix_nano ?? 0))

  return (
    <article className="rounded-xl border border-gray-200 bg-white shadow-sm overflow-hidden">
      <header className="px-4 py-3 border-b border-gray-100 flex items-center justify-between gap-3 bg-gradient-to-r from-white to-gray-50/80">
        <div className="flex items-center gap-2 flex-wrap min-w-0">
          <span className="inline-flex items-center justify-center h-6 min-w-[1.5rem] px-1.5 rounded-md bg-gray-900 text-white text-xs font-bold">
            {turn.turn_number}
          </span>
          {agent && (
            <span className="text-[10px] font-semibold uppercase tracking-wide px-2 py-0.5 rounded-full bg-purple-100 text-purple-800">
              {agent}
            </span>
          )}
          {interrupted && (
            <span className="text-[10px] font-semibold uppercase tracking-wide px-2 py-0.5 rounded-full bg-rose-100 text-rose-800">
              Interrupted
            </span>
          )}
        </div>
        <div className="flex items-center gap-1.5 shrink-0">
          <Zap className="w-3.5 h-3.5 text-indigo-400" />
          <span className="text-[10px] uppercase tracking-wider text-gray-400 font-medium">Round-trip</span>
          <span className={`text-base font-bold tabular-nums ${latencyTone(turn.sut_response_latency_ms)}`}>
            {formatMs(turn.sut_response_latency_ms)}
          </span>
        </div>
      </header>

      <div className="px-4 py-4 space-y-4">
        {(userText || assistantText) && (
          <div className="space-y-2.5">
            {userText && (
              <div className="flex justify-end">
                <div className="max-w-[88%] rounded-2xl rounded-tr-sm bg-indigo-600 text-white px-3.5 py-2.5 shadow-sm">
                  <p className="text-[10px] font-semibold uppercase tracking-wider text-indigo-200 mb-0.5">User</p>
                  <p className="text-sm leading-relaxed">{userText}</p>
                </div>
              </div>
            )}
            {assistantText && (
              <div className="flex justify-start">
                <div className="max-w-[88%] rounded-2xl rounded-tl-sm bg-gray-100 border border-gray-200/80 px-3.5 py-2.5">
                  <p className="text-[10px] font-semibold uppercase tracking-wider text-gray-500 mb-0.5">Agent</p>
                  <p className="text-sm text-gray-900 leading-relaxed">{assistantText}</p>
                </div>
              </div>
            )}
          </div>
        )}

        <div>
          <p className="text-[10px] font-semibold uppercase tracking-wider text-gray-400 mb-2">
            Latency waterfall
          </p>
          <LatencyWaterfall turn={turn} extra={extra} />
        </div>

        {componentSpans.length > 0 && (
          <div className="pt-1 border-t border-gray-100">
            <button
              type="button"
              onClick={() => setShowSpans((v) => !v)}
              className="text-xs text-gray-500 hover:text-gray-800 inline-flex items-center gap-1 font-medium"
            >
              {showSpans ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />}
              {showSpans ? 'Hide' : 'View'} span details ({componentSpans.length})
            </button>
            {showSpans && (
              <div className="mt-2 space-y-1.5">
                {componentSpans.map((span) => (
                  <RawSpanRow key={`${span.trace_id}-${span.span_id}`} span={span} />
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </article>
  )
}

export default function SyntheticCallTracePanel({
  evaluatorResultId,
  traceId,
  callShortId,
  onClose,
}: SyntheticCallTracePanelProps) {
  const [tab, setTab] = useState<DetailTab>('conversation')

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

  if (isLoading) {
    return <div className="flex items-center justify-center h-40 text-sm text-gray-500">Loading trace…</div>
  }

  if (isError) {
    const message = (error as Error)?.message || 'Trace not available'
    if (message.includes('404') || message.toLowerCase().includes('not found')) {
      return (
        <div className="p-6 text-sm text-gray-600">
          No trace yet. Run a Pipecat WebRTC session with tracing, then see{' '}
          <Link to="/call-traces" className="text-indigo-600 hover:text-indigo-800 font-medium">
            Call Traces → Connect Pipecat
          </Link>
        </div>
      )
    }
    return <div className="p-6 text-sm text-amber-800 bg-amber-50">Could not load trace: {message}</div>
  }

  const trace = data
  if (!trace) return null

  const statusLabel = trace.status === 'finalized' ? 'closed' : trace.status
  const aggregates = trace.component_aggregates as Record<string, { p50?: number }> | undefined
  const isEmbedded = !onClose

  return (
    <div
      className={`flex flex-col w-full bg-gray-50/40 ${isEmbedded ? '' : 'h-full min-h-0'}`}
    >
      <div className="flex items-start justify-between gap-4 px-5 py-4 border-b border-gray-200 bg-white shrink-0">
        <div className="min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <h2 className="text-lg font-semibold text-gray-900 tracking-tight">
              {trace.call_short_id ? `#${trace.call_short_id}` : 'Call trace'}
            </h2>
            <span
              className={`text-xs rounded-full px-2.5 py-0.5 capitalize font-medium ${
                trace.status === 'open' ? 'bg-amber-100 text-amber-800' : 'bg-emerald-100 text-emerald-800'
              }`}
            >
              {statusLabel}
            </span>
            <span className="text-xs px-2 py-0.5 rounded-md bg-blue-50 text-blue-700 font-medium">
              {trace.transport === 'webrtc' ? 'WebRTC' : trace.transport}
            </span>
          </div>
          <div className="flex items-center gap-3 mt-1.5 text-xs text-gray-500">
            <span>{trace.turn_count} turns</span>
            {trace.started_at && (
              <span className="inline-flex items-center gap-1">
                <Clock className="w-3 h-3" />
                {new Date(trace.started_at).toLocaleString()}
              </span>
            )}
          </div>
        </div>
        {onClose && (
          <button type="button" onClick={onClose} className="p-2 rounded-lg text-gray-400 hover:bg-gray-100" aria-label="Close">
            <X className="w-5 h-5" />
          </button>
        )}
      </div>

      <div className="px-5 py-3 border-b border-gray-100 bg-white shrink-0">
        <div className="grid grid-cols-3 gap-2">
          {(['p50', 'p90', 'p95'] as const).map((label) => {
            const value =
              label === 'p50'
                ? trace.response_latency_p50_ms
                : label === 'p90'
                  ? trace.response_latency_p90_ms
                  : trace.response_latency_p95_ms
            return (
              <div key={label} className="rounded-lg bg-gray-50 border border-gray-100 px-3 py-2 text-center">
                <p className="text-[10px] uppercase tracking-wider text-gray-400 font-semibold">{label}</p>
                <p className={`text-lg font-bold tabular-nums ${latencyTone(value)}`}>{formatMs(value)}</p>
              </div>
            )
          })}
        </div>
        {aggregates && (
          <div className="flex flex-wrap gap-1.5 mt-2.5">
            {(['stt', 'llm', 'tts', 's2s'] as const).map((kind) => {
              const p50 = aggregates[`${kind}_ttfb_ms`]?.p50
              if (p50 == null) return null
              const style = COMPONENT_STYLES[kind]
              const sessionMeta = pipelineModels[kind]
              return (
                <span
                  key={kind}
                  className={`text-[10px] px-2 py-0.5 rounded-full border ${style.border} ${style.bg} ${style.text} font-medium`}
                  title={providerLabel(sessionMeta?.provider, sessionMeta?.model)}
                >
                  {style.label} p50 {Math.round(p50)}ms
                  {sessionMeta?.model && <span className="opacity-70"> · {sessionMeta.model}</span>}
                </span>
              )
            })}
          </div>
        )}
      </div>

      <PipelineModelsBar models={pipelineModels} />

      <div className="flex gap-0.5 px-4 py-2 border-b border-gray-200 bg-white shrink-0">
        {(
          [
            ['conversation', 'Conversation', MessageSquare],
            ['latency', 'Waterfall', Activity],
            ['raw', 'Raw spans', Zap],
          ] as const
        ).map(([id, label, Icon]) => (
          <button
            key={id}
            type="button"
            onClick={() => setTab(id)}
            className={`px-3 py-2 text-sm font-medium rounded-lg inline-flex items-center gap-1.5 transition-colors ${
              tab === id ? 'bg-gray-900 text-white shadow-sm' : 'text-gray-500 hover:text-gray-800 hover:bg-gray-100'
            }`}
          >
            <Icon className="w-4 h-4" />
            {label}
          </button>
        ))}
      </div>

      <div className={`${isEmbedded ? '' : 'flex-1 min-h-0'} overflow-y-auto px-4 py-4 space-y-3`}>
        {tab === 'conversation' && (
          <>
            {turns.length === 0 ? (
              <p className="text-center py-16 text-sm text-gray-500">No conversation turns yet</p>
            ) : (
              turns.map((turn) => (
                <TurnCard
                  key={turn.turn_number}
                  turn={turn}
                  spans={spansByTurn.get(turn.turn_number) ?? []}
                  sessionModels={pipelineModels}
                />
              ))
            )}
          </>
        )}

        {tab === 'latency' && (
          <div className="space-y-3">
            {turns.length === 0 ? (
              <p className="text-center py-16 text-sm text-gray-500">No latency data</p>
            ) : (
              turns.map((turn) => {
                const spanMeta = turnMetaFromSpans(spansByTurn.get(turn.turn_number) ?? [])
                const extra = mergeTurnMeta(turn, spanMeta, pipelineModels)
                return (
                  <div key={turn.turn_number} className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm">
                    <div className="flex items-center justify-between mb-3">
                      <span className="text-sm font-semibold text-gray-900">Turn {turn.turn_number}</span>
                      <span className={`text-sm font-bold tabular-nums ${latencyTone(turn.sut_response_latency_ms)}`}>
                        {formatMs(turn.sut_response_latency_ms)} total
                      </span>
                    </div>
                    <LatencyWaterfall turn={turn} extra={extra} compact />
                  </div>
                )
              })
            )}
          </div>
        )}

        {tab === 'raw' && (
          <div className="space-y-1.5">
            {otelSpans.length === 0 ? (
              <p className="text-center py-16 text-sm text-gray-500">No spans</p>
            ) : (
              otelSpans
                .slice()
                .sort((a, b) => (a.start_time_unix_nano ?? 0) - (b.start_time_unix_nano ?? 0))
                .map((span) => <RawSpanRow key={`${span.trace_id}-${span.span_id}`} span={span} />)
            )}
          </div>
        )}
      </div>
    </div>
  )
}
