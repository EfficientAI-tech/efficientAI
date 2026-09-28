import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import {
  Activity,
  BarChart3,
  Clock,
  ChevronDown,
  ChevronRight,
  ExternalLink,
  Layers,
  Info,
  Loader2,
  MessageSquare,
  Radio,
  X,
} from 'lucide-react'
import { apiClient } from '../../lib/api'
import TraceTurnDetail from './TraceTurnDetail'
import TraceWaterfall from './TraceWaterfall'
import CallWaveformPlayer from './CallWaveformPlayer'
import CallEventTimeline from './CallEventTimeline'
import {
  buildOtelCallTimeline,
  computeTurnMessageOffsets,
  resolveTraceStartNs,
} from './callTimelineUtils'
import { buildSpanTranscriptMessages } from './traceUtils'
import { parseUnixNano, unixNanoOffsetMs } from './traceUtils'
import { computeResponseLatencySummary, responseLatencySampleLabel, RESPONSE_LATENCY_SAMPLE_HINT } from '../../lib/traceLatencySummary'
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
import { transcriptBubbleClass, transcriptMetaClass } from './transcriptBubbleStyles'

interface SyntheticCallTracePanelProps {
  evaluatorResultId?: string
  traceId?: string
  callShortId?: string
  onClose?: () => void
  embedded?: boolean
  hideRecording?: boolean
  /** When set, parent owns tab navigation (e.g. unified call-details tab bar). */
  activeTab?: SyntheticTraceDetailTab
  hideTabBar?: boolean
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
  user_utterances?: string[]
  assistant_text?: string
  agent_id?: string
  agent_role?: string
  turn_type?: string
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
  start_time_unix_nano?: number | string | null
  end_time_unix_nano?: number | string | null
  attributes?: Record<string, unknown>
  events?: Array<{ name?: string; attributes?: Record<string, unknown> }>
}

export type SyntheticTraceDetailTab = 'trace' | 'waterfall' | 'transcript' | 'timeline' | 'spans'
type DetailTab = SyntheticTraceDetailTab
type ComponentKind = 'stt' | 'llm' | 'tts' | 's2s'

const COMPONENT_LABELS: Record<ComponentKind, string> = {
  stt: 'STT',
  llm: 'LLM',
  tts: 'TTS',
  s2s: 'S2S',
}

const TABS: Array<{ id: DetailTab; label: string; icon: typeof Activity }> = [
  { id: 'trace', label: 'Trace', icon: Activity },
  { id: 'waterfall', label: 'Waterfall', icon: BarChart3 },
  { id: 'transcript', label: 'Transcript', icon: MessageSquare },
  { id: 'timeline', label: 'Timeline', icon: Clock },
  { id: 'spans', label: 'Spans', icon: Layers },
]

function TracePanelSkeleton({
  embedded = false,
  compact = false,
  message = 'Loading trace…',
}: {
  embedded?: boolean
  compact?: boolean
  message?: string
}) {
  if (compact) {
    return (
      <div className={`flex flex-col items-center justify-center gap-3 ${embedded ? 'py-12' : 'py-16'}`}>
        <Loader2 className="h-6 w-6 animate-spin text-primary-500" />
        <p className="text-sm text-gray-500">{message}</p>
      </div>
    )
  }
  return (
    <div className={`space-y-3 ${embedded ? 'p-1' : 'p-5'}`}>
      <div className="flex items-center gap-3">
        <Loader2 className="h-5 w-5 animate-spin text-primary-500" />
        <p className="text-sm text-gray-500">{message}</p>
      </div>
      <div className="h-8 w-48 animate-pulse rounded-lg bg-gray-100" />
      <div className={`animate-pulse rounded-xl bg-gray-100 ${embedded ? 'h-32' : 'h-48'}`} />
      <div className="h-64 animate-pulse rounded-xl bg-gray-100" />
    </div>
  )
}

function TraceTabBar({
  tabs,
  activeTab,
  onSelect,
  compact = false,
}: {
  tabs: typeof TABS
  activeTab: DetailTab
  onSelect: (tab: DetailTab) => void
  compact?: boolean
}) {
  return (
    <div
      className={`flex flex-nowrap gap-0.5 overflow-x-auto border-b border-gray-200 bg-white px-1 [-ms-overflow-style:none] [scrollbar-width:none] [&::-webkit-scrollbar]:hidden ${
        compact ? '' : 'px-5'
      }`}
    >
      {tabs.map(({ id, label, icon: Icon }) => (
        <button
          key={id}
          type="button"
          onClick={() => onSelect(id)}
          className={`inline-flex shrink-0 items-center gap-1.5 border-b-2 px-2.5 py-1.5 text-sm font-medium transition-colors ${
            activeTab === id
              ? 'border-primary-500 text-primary-800'
              : 'border-transparent text-gray-500 hover:border-gray-300 hover:text-gray-700'
          }`}
        >
          <Icon className="h-4 w-4" />
          {label}
        </button>
      ))}
    </div>
  )
}

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
    const attrs = span.attributes ?? {}
    const agentRole = attrStr(attrs, 'efficientai.agent_role')
    if (agentRole && !out.agent_role) {
      out.agent_role = agentRole
    }
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

function isSessionLevelSpan(span: OtelSpan, traceDurationMs: number): boolean {
  const name = span.name.toLowerCase()
  if (name !== 'conversation' && name !== 'turn') return false
  const start = parseUnixNano(span.start_time_unix_nano)
  const end = parseUnixNano(span.end_time_unix_nano)
  if (start == null || end == null) {
    return name === 'conversation'
  }
  const durationMs = Number((end - start) / 1_000_000n)
  return traceDurationMs > 0 && durationMs >= traceDurationMs * 0.85
}

function formatTraceRoleLabel(raw?: string | null): string | null {
  if (!raw) return null
  const normalized = raw.trim().toLowerCase()
  if (!normalized || normalized === 'conversation') return null
  return raw
    .trim()
    .replace(/[_-]+/g, ' ')
    .replace(/\b\w/g, (char) => char.toUpperCase())
}

function resolveTranscriptSpeakerLabel(
  role: 'user' | 'agent',
  extra: TraceTurnExtra,
  sessionAgentName?: string | null,
): string {
  if (role === 'user') return 'User'
  return (
    formatTraceRoleLabel(extra.agent_role) ||
    formatTraceRoleLabel(extra.turn_type) ||
    sessionAgentName?.trim() ||
    'Bot'
  )
}

function MetricTile({
  label,
  value,
  unit,
  subtitle,
  hint,
  highlight,
}: {
  label: string
  value: string
  unit?: string
  subtitle?: string
  hint?: string
  highlight?: boolean
}) {
  return (
    <div
      className={`rounded-lg border px-3 py-3 ${
        highlight ? 'border-primary-400 bg-primary-50/40' : 'border-gray-200 bg-white'
      }`}
      title={hint}
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
      {subtitle ? <p className="mt-1 text-[10px] text-gray-500">{subtitle}</p> : null}
    </div>
  )
}

function RawSpanRow({ span }: { span: OtelSpan }) {
  const [open, setOpen] = useState(false)
  const kind = spanKind(span)
  const meta = metaFromSpan(span)
  const start = parseUnixNano(span.start_time_unix_nano)
  const end = parseUnixNano(span.end_time_unix_nano)
  const durationMs = start != null && end != null ? Number((end - start) / 1_000_000n) : null
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
  activeTab: controlledTab,
  hideTabBar = false,
}: SyntheticCallTracePanelProps) {
  const [internalTab, setInternalTab] = useState<DetailTab>('trace')
  const tab = controlledTab ?? internalTab
  const visibleTabs = embedded ? TABS.filter((item) => item.id !== 'transcript') : TABS

  const lookupKey = traceId ?? callShortId ?? evaluatorResultId
  const lookupMode = traceId ? 'by-trace' : callShortId ? 'by-call-short-id' : 'by-result'

  const { data, isLoading, isFetching, isError, error } = useQuery({
    queryKey: ['synthetic-call-trace', lookupKey, lookupMode],
    queryFn: () => {
      if (traceId) return apiClient.getSyntheticCallTrace(traceId, false)
      if (callShortId) return apiClient.getSyntheticCallTraceByCallShortId(callShortId, false)
      return apiClient.getSyntheticCallTraceForResult(evaluatorResultId!, false)
    },
    enabled: Boolean(traceId || callShortId || evaluatorResultId),
    retry: false,
    refetchInterval: (query) =>
      query.state.data?.status === 'open' ? 3000 : false,
  })

  const resolvedTraceId = traceId ?? data?.id

  const tabNeedsSpans = tab === 'spans' || tab === 'waterfall' || tab === 'timeline'
  const isOpenTrace = data?.status === 'open'

  const {
    data: spansData,
    isLoading: spansLoading,
    isFetching: spansFetching,
    isError: spansIsError,
    error: spansError,
  } = useQuery({
    queryKey: ['synthetic-call-trace-spans', resolvedTraceId],
    queryFn: () => apiClient.getSyntheticCallTraceSpans(resolvedTraceId!),
    enabled: Boolean(resolvedTraceId),
    retry: false,
    refetchInterval: isOpenTrace ? 3000 : false,
  })

  const traceHeaderLoading = !data && (isLoading || isFetching)
  const spansPending =
    tabNeedsSpans &&
    Boolean(resolvedTraceId) &&
    (spansLoading || (spansFetching && spansData === undefined))
  const spansErrorMessage = spansIsError ? (spansError as Error)?.message || 'Failed to load spans' : null

  const otelSpans = (spansData?.otel_spans ?? data?.otel_spans ?? []) as OtelSpan[]
  const spansByTurn = useMemo(() => buildSpansByTurn(otelSpans), [otelSpans])
  const turns = (data?.turns ?? []) as TraceTurn[]
  const pipelineModels = (data?.pipeline_models ?? {}) as PipelineModels
  const pipelineMode = useMemo(() => sessionPipelineMode(turns), [turns])

  const linkedAgentId = data?.agent_id
  const { data: linkedAgent } = useQuery({
    queryKey: ['trace-agent', linkedAgentId],
    queryFn: () => apiClient.getAgent(linkedAgentId!),
    enabled: Boolean(linkedAgentId),
  })

  const traceStartNs = useMemo(() => resolveTraceStartNs(otelSpans), [otelSpans])
  const traceDurationMs = useMemo(() => {
    if (!otelSpans.length) return 0
    const traceEnd = otelSpans.reduce((max, span) => {
      const end =
        parseUnixNano(span.end_time_unix_nano) ??
        parseUnixNano(span.start_time_unix_nano) ??
        traceStartNs
      return end > max ? end : max
    }, traceStartNs)
    return Math.max(0, unixNanoOffsetMs(traceEnd, traceStartNs))
  }, [otelSpans, traceStartNs])

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
      const offsets = computeTurnMessageOffsets(
        turnSpans,
        {
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
        },
        traceStartNs,
      )
      return {
        turnNumber: turn.turn_number,
        offsetMs: offsets.userOffsetMs ?? offsets.agentOffsetMs ?? 0,
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
          durationMs: (() => {
            const start = parseUnixNano(span.start_time_unix_nano)
            const end = parseUnixNano(span.end_time_unix_nano)
            return start != null && end != null ? Number((end - start) / 1_000_000n) : null
          })(),
        })),
      }
    })
  }, [turns, spansByTurn, pipelineModels, pipelineMode, traceStartNs])

  const transcriptMessages = useMemo(() => {
    const sessionAgentName = linkedAgent?.name ?? null
    const turnByNumber = new Map(turns.map((turn) => [turn.turn_number, turn]))
    const spanMessages = buildSpanTranscriptMessages(otelSpans, traceStartNs)

    return spanMessages.map((message) => {
      const turn = turnByNumber.get(message.turn)
      const turnSpans = spansByTurn.get(message.turn) ?? []
      const spanMeta = turnMetaFromSpans(turnSpans)
      const extra = turn
        ? mergeTurnMeta(turn, spanMeta, pipelineModels)
        : { ...spanMeta, agent_role: message.agentRole ?? spanMeta.agent_role }
      const incomplete = turn ? isTurnIncomplete(turn, pipelineMode) : false
      const isLastAgentInTurn =
        message.role === 'agent' &&
        !spanMessages.some(
          (other) =>
            other.role === 'agent' &&
            other.turn === message.turn &&
            other.offsetMs > message.offsetMs,
        )

      return {
        role: message.role,
        speakerLabel: resolveTranscriptSpeakerLabel(
          message.role,
          {
            ...extra,
            agent_role: message.agentRole ?? extra.agent_role,
          },
          sessionAgentName,
        ),
        text: message.text,
        turn: message.turn,
        offsetMs: message.offsetMs,
        latencyMs:
          message.role === 'agent' && isLastAgentInTurn
            ? turn?.sut_response_latency_ms ?? undefined
            : undefined,
        talkOver: turn?.talk_over,
        interrupted: message.role === 'agent' && isLastAgentInTurn ? extra.was_interrupted : undefined,
        incomplete,
      }
    })
  }, [turns, spansByTurn, pipelineModels, pipelineMode, linkedAgent?.name, traceStartNs, otelSpans])

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
          user_utterances: extra.user_utterances,
          assistant_text: extra.assistant_text,
        },
      }
    })
  }, [turns, spansByTurn, pipelineModels])

  const responseLatencyStats = useMemo(() => computeResponseLatencySummary(turns), [turns])

  const timelineEvents = useMemo(() => {
    return buildOtelCallTimeline(otelSpans, timelineTurnInputs)
  }, [otelSpans, timelineTurnInputs])

  if (traceHeaderLoading) {
    return <TracePanelSkeleton embedded={embedded} message="Loading trace…" />
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
              No trace yet. Run a voice agent session with OTLP tracing enabled, then check{' '}
              <Link to="/observability/calls" className="text-primary-600 hover:text-primary-800 font-medium">
                Calls
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
  const transport = (trace.transport ?? 'webrtc').toLowerCase()
  const showPhonePipelineHint = transport === 'phone' && otelSpans.length === 0 && !isOpen

  const medianMs =
    responseLatencyStats?.p50 ??
    (trace.response_latency_p50_ms != null ? Math.round(trace.response_latency_p50_ms) : null)
  const p90Ms =
    responseLatencyStats?.p90 ??
    (trace.response_latency_p90_ms != null ? Math.round(trace.response_latency_p90_ms) : null)
  const p95Ms =
    responseLatencyStats?.p95 ??
    (trace.response_latency_p95_ms != null ? Math.round(trace.response_latency_p95_ms) : null)
  const latencySampleCount =
    responseLatencyStats?.sampleCount ?? trace.response_latency_sample_count ?? null
  const turnCountForLatency = turns.length || trace.turn_count || 0
  const latencySampleLabel =
    latencySampleCount != null && turnCountForLatency > 0
      ? responseLatencySampleLabel(latencySampleCount, turnCountForLatency)
      : undefined

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

  const spansErrorBanner = spansErrorMessage ? (
    <div className={`text-sm text-red-800 bg-red-50 ${embedded ? 'mx-0 mb-4 rounded-lg border border-red-200 p-3' : 'mx-5 mb-4 rounded-lg border border-red-200 p-3'}`}>
      Could not load span data: {spansErrorMessage}
    </div>
  ) : null

  const tabBody = spansPending ? (
    <TracePanelSkeleton embedded={embedded} compact message="Loading spans and timeline…" />
  ) : (
    <>
      {spansErrorBanner}
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
          {spansErrorMessage ? (
            <p className="py-12 text-center text-sm text-gray-500">Waterfall unavailable until spans load.</p>
          ) : traceTurnRows.length === 0 ? (
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
                    <div className={transcriptBubbleClass(isUser)}>
                      <div className={transcriptMetaClass(isUser)}>
                        <span>{msg.speakerLabel}</span>
                        <span className="text-[10px] font-normal normal-case tracking-normal tabular-nums opacity-90">
                          Turn {msg.turn} {formatOffset(msg.offsetMs)}
                          {msg.latencyMs != null ? ` · ${formatMs(msg.latencyMs)}` : ''}
                        </span>
                        <TurnSignalBadges
                          talkOver={isUser ? msg.talkOver : undefined}
                          interrupted={!isUser ? msg.interrupted : undefined}
                          incomplete={msg.incomplete}
                        />
                      </div>
                      <p className="text-sm leading-relaxed whitespace-pre-wrap">{msg.text}</p>
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
          {spansErrorMessage ? (
            <p className="py-12 text-center text-sm text-gray-500">Timeline unavailable until spans load.</p>
          ) : (
            <CallEventTimeline
              events={timelineEvents}
              emptyMessage="No pipeline events captured for this session."
            />
          )}
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
                .filter((span) => !isSessionLevelSpan(span, traceDurationMs))
                .slice()
                .sort((a, b) => {
                  const startA = parseUnixNano(a.start_time_unix_nano) ?? 0n
                  const startB = parseUnixNano(b.start_time_unix_nano) ?? 0n
                  if (startA === startB) return 0
                  return startA < startB ? -1 : 1
                })
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
    if (hideTabBar) {
      return <div className="min-h-0">{tabBody}</div>
    }
    return (
      <div className="rounded-xl border border-gray-200 bg-white">
        <TraceTabBar tabs={visibleTabs} activeTab={tab} onSelect={setInternalTab} compact />
        <div className="p-4">{tabBody}</div>
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
              {data?.spans_storage && (
                <span className="inline-flex items-center rounded-full border border-gray-200 bg-white px-2.5 py-0.5 text-xs font-medium text-gray-600">
                  {data.spans_storage === 's3' ? 'Archived' : data.spans_storage === 'batches' ? 'Live' : 'Legacy'}
                </span>
              )}
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

        <div className={`space-y-2.5 bg-gray-50 ${isDrawer ? 'px-5 pb-3 pt-4' : 'space-y-3 px-5 py-4'}`}>
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
              subtitle={latencySampleLabel}
              hint={
                latencySampleCount != null &&
                turnCountForLatency > latencySampleCount
                  ? RESPONSE_LATENCY_SAMPLE_HINT
                  : undefined
              }
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
          {showPhonePipelineHint && (
            <div
              className="flex gap-2.5 rounded-lg border border-sky-200 bg-sky-50/90 px-3.5 py-3 text-left text-xs leading-relaxed text-sky-950"
              role="status"
            >
              <Info className="mt-0.5 h-4 w-4 shrink-0 text-sky-600" aria-hidden />
              <p>
                <span className="font-semibold">Phone evaluation trace.</span> Turn-level response timing is
                expected here. Waterfall, pipeline stages (STT / LLM / TTS), and in-drawer transcript need
                OTLP spans—use WebRTC tests with tracing enabled for full pipeline detail. For recording,
                dialogue, and scores on this run, use{' '}
                {trace.evaluator_result_id ? (
                  <Link
                    to={`/results/${trace.evaluator_result_id}`}
                    className="font-medium text-sky-800 underline underline-offset-2 hover:text-sky-950"
                  >
                    View eval result
                  </Link>
                ) : (
                  'the evaluation result'
                )}
                .
              </p>
            </div>
          )}
          {isDrawer ? <TraceTabBar tabs={visibleTabs} activeTab={tab} onSelect={setInternalTab} compact /> : null}
        </div>

        {!isDrawer ? <TraceTabBar tabs={visibleTabs} activeTab={tab} onSelect={setInternalTab} /> : null}
      </div>

      <div className={isDrawer ? 'min-h-0 flex-1 overflow-y-auto overscroll-contain' : undefined}>
        {tabBody}
      </div>
    </div>
  )
}
