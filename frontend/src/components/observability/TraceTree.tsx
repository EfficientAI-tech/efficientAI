import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  ChevronDown,
  ChevronRight,
  Layers,
  MessageSquare,
  Mic,
  Sparkles,
  Volume2,
  Wrench,
  Zap,
  ArrowLeftRight,
  Circle,
  ChevronsDownUp,
  ChevronsUpDown,
} from 'lucide-react'
import type { ObservabilityCallTrace, ObservabilityTraceSpan } from '../../types/api'
import {
  buildSpanTree,
  computeTraceStats,
  enrichSpanAttributes,
  flattenSpanTree,
  formatAttributeValue,
  formatDuration,
  formatRelativeOffset,
  formatSpanTimestamp,
  getAllCollapsibleSpanIds,
  getDefaultCollapsedSpanIds,
  getServiceName,
  getSpanDisplayName,
  getSpanKind,
  getSpanSummaryLines,
  getStatusLabel,
  getTraceRootStartMs,
  getTurnPreview,
  isElevenLabsTurnSpan,
  partitionAttributes,
  spanOffsetSec,
  truncateSpanId,
  type SpanTreeNode,
} from './traceDisplay'

const SPAN_ICON_CLASS: Record<string, string> = {
  conversation: 'text-slate-500',
  turn: 'text-violet-600',
  stt: 'text-cyan-600',
  llm: 'text-violet-500',
  tts: 'text-emerald-600',
  s2s: 'text-fuchsia-600',
  tool_call: 'text-amber-600',
  endpointing: 'text-gray-500',
}

function SpanTypeIcon({ name, className = 'h-3.5 w-3.5' }: { name: string; className?: string }) {
  const color =
    SPAN_ICON_CLASS[name] ||
    (name.startsWith('elevenlabs.recv.') ? 'text-violet-600' : undefined) ||
    (name.startsWith('elevenlabs.tool.') ? 'text-amber-600' : undefined) ||
    (name.startsWith('elevenlabs.metric.') ? 'text-cyan-600' : undefined) ||
    'text-gray-400'
  const props = { className: `${className} ${color} shrink-0` }
  if (name.startsWith('elevenlabs.metric.')) {
    return <Zap {...props} />
  }
  if (name.startsWith('elevenlabs.tool.')) {
    return <Wrench {...props} />
  }
  if (name === 'elevenlabs.recv.user_transcript') {
    return <Mic {...props} />
  }
  if (name === 'elevenlabs.recv.agent_response') {
    return <MessageSquare {...props} />
  }
  if (name === 'elevenlabs.conversation') {
    return <Layers {...props} />
  }
  switch (name) {
    case 'conversation':
      return <Layers {...props} />
    case 'turn':
      return <MessageSquare {...props} />
    case 'stt':
      return <Mic {...props} />
    case 'llm':
      return <Sparkles {...props} />
    case 'tts':
      return <Volume2 {...props} />
    case 's2s':
      return <Zap {...props} />
    case 'tool_call':
      return <Wrench {...props} />
    case 'endpointing':
      return <ArrowLeftRight {...props} />
    default:
      return <Circle {...props} />
  }
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="grid grid-cols-[140px_1fr] gap-3 py-2 border-b border-gray-100 last:border-0">
      <span className="text-xs text-gray-500">{label}</span>
      <span className="text-xs font-mono text-emerald-700 break-all">{value}</span>
    </div>
  )
}

function AttributeTable({ entries }: { entries: Array<[string, unknown]> }) {
  if (entries.length === 0) {
    return <p className="text-sm text-gray-500">No attributes recorded.</p>
  }
  return (
    <div className="divide-y divide-gray-100 rounded-lg border border-gray-100 overflow-hidden">
      {entries.map(([key, value]) => (
        <div key={key} className="grid grid-cols-[minmax(140px,40%)_1fr] gap-3 px-3 py-2 bg-white">
          <span className="text-xs text-gray-500 break-all">{key}</span>
          <span className="text-xs font-mono text-emerald-700 break-words whitespace-pre-wrap">
            {formatAttributeValue(value)}
          </span>
        </div>
      ))}
    </div>
  )
}

function SpanDetailPanel({
  span,
  allSpans,
  rootStartMs,
  callStartMs,
}: {
  span: ObservabilityTraceSpan
  allSpans: ObservabilityTraceSpan[]
  rootStartMs: number
  callStartMs: number | null
}) {
  const enriched = useMemo(() => enrichSpanAttributes(span, allSpans), [span, allSpans])
  const summaryLines = useMemo(() => getSpanSummaryLines(span, allSpans), [span, allSpans])
  const { highlighted, rest } = useMemo(() => partitionAttributes(enriched), [enriched])
  const [showAllAttrs, setShowAllAttrs] = useState(false)
  const relativeOffset = span.start_time
    ? formatRelativeOffset(span.start_time - rootStartMs)
    : '—'

  return (
    <div className="flex flex-col h-full min-h-0">
      <div className="px-5 py-4 border-b border-gray-100 shrink-0">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <SpanTypeIcon name={span.name} className="h-4 w-4" />
              <h3 className="text-base font-semibold text-gray-900">{getSpanDisplayName(span)}</h3>
            </div>
            <p className="text-xs text-gray-500 mt-1 font-mono">{truncateSpanId(span.span_id)}</p>
            <p className="text-xs text-gray-400 mt-0.5">
              {relativeOffset} · {formatSpanTimestamp(span.start_time)}
            </p>
          </div>
          <div className="rounded-lg bg-violet-50 border border-violet-100 px-3 py-2 text-center min-w-[88px]">
            <p className="text-[10px] uppercase tracking-wider text-violet-600 font-semibold">Latency</p>
            <p className="text-lg font-semibold text-violet-900 tabular-nums">
              {formatDuration(span.duration_ms, 'seconds')}
            </p>
          </div>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-5 py-4 space-y-5">
        {summaryLines.length > 0 && (
          <section>
            <h4 className="text-xs uppercase tracking-wider text-gray-500 font-semibold mb-2">Summary</h4>
            <div className="rounded-lg border border-indigo-100 bg-indigo-50/40 divide-y divide-indigo-100/80">
              {summaryLines.map((line) => (
                <div key={line.label} className="px-3 py-2.5">
                  <p className="text-[10px] uppercase tracking-wider text-indigo-500 font-semibold mb-0.5">
                    {line.label}
                  </p>
                  <p className="text-sm text-gray-800 leading-relaxed whitespace-pre-wrap">{line.value}</p>
                </div>
              ))}
            </div>
          </section>
        )}

        <section>
          <h4 className="text-xs uppercase tracking-wider text-gray-500 font-semibold mb-2">
            Basic Information
          </h4>
          <div className="rounded-lg border border-gray-100 bg-gray-50/50 px-3">
            <InfoRow label="Span ID" value={span.span_id || '—'} />
            <InfoRow label="Parent Span ID" value={span.parent_span_id || '—'} />
            <InfoRow label="Span Name" value={span.name} />
            <InfoRow label="Service Name" value={getServiceName(span)} />
            <InfoRow label="Span Kind" value={getSpanKind(span)} />
            <InfoRow label="Duration" value={formatDuration(span.duration_ms, 'seconds')} />
            <InfoRow label="Relative time" value={relativeOffset} />
            {callStartMs && span.start_time && (
              <InfoRow
                label="Audio seek"
                value={`${(spanOffsetSec(span, callStartMs, rootStartMs) ?? 0).toFixed(1)}s`}
              />
            )}
            <InfoRow label="Timestamp" value={formatSpanTimestamp(span.start_time)} />
            <InfoRow label="Status Code" value={getStatusLabel(span.status)} />
          </div>
        </section>

        <section>
          <h4 className="text-xs uppercase tracking-wider text-gray-500 font-semibold mb-2">
            Span Attributes
          </h4>
          <AttributeTable entries={highlighted} />
          {rest.length > 0 && (
            <div className="mt-3">
              <button
                type="button"
                onClick={() => setShowAllAttrs((v) => !v)}
                className="text-xs text-indigo-600 hover:text-indigo-800 font-medium"
              >
                {showAllAttrs ? 'Hide additional attributes' : `Show ${rest.length} more attributes`}
              </button>
              {showAllAttrs && (
                <div className="mt-2">
                  <AttributeTable entries={rest} />
                </div>
              )}
            </div>
          )}
        </section>
      </div>
    </div>
  )
}

function SpanTreeRow({
  node,
  depth,
  selectedSpanId,
  collapsedIds,
  rootStartMs,
  allSpans,
  onSelect,
  onToggle,
}: {
  node: SpanTreeNode
  depth: number
  selectedSpanId: string | null
  collapsedIds: Set<string>
  rootStartMs: number
  allSpans: ObservabilityTraceSpan[]
  onSelect: (spanId: string) => void
  onToggle: (spanId: string) => void
}) {
  if (!node.span_id) return null

  const spanId = node.span_id
  const hasChildren = node.children.length > 0
  const isCollapsed = collapsedIds.has(spanId)
  const isSelected = selectedSpanId === spanId
  const durationLabel =
    node.name === 'conversation' || node.name === 'turn' || isElevenLabsTurnSpan(node)
      ? formatDuration(node.duration_ms, 'seconds')
      : formatDuration(node.duration_ms, 'auto')
  const relativeLabel = node.start_time
    ? formatRelativeOffset(node.start_time - rootStartMs)
    : null
  const preview = node.name === 'turn' || isElevenLabsTurnSpan(node) ? getTurnPreview(node, allSpans) : null

  return (
    <>
      <button
        type="button"
        onClick={() => onSelect(spanId)}
        className={`w-full flex items-start gap-1.5 py-1.5 pr-2 text-left transition-colors ${
          isSelected
            ? 'bg-violet-50 border-l-2 border-violet-500'
            : 'hover:bg-gray-50 border-l-2 border-transparent'
        }`}
        style={{ paddingLeft: `${8 + depth * 16}px` }}
      >
        {hasChildren ? (
          <span
            role="button"
            tabIndex={0}
            onClick={(e) => {
              e.stopPropagation()
              onToggle(spanId)
            }}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault()
                e.stopPropagation()
                onToggle(spanId)
              }
            }}
            className="p-0.5 rounded hover:bg-gray-200/80 text-gray-400 mt-0.5"
          >
            {isCollapsed ? <ChevronRight className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
          </span>
        ) : (
          <span className="w-4 shrink-0 mt-0.5" />
        )}
        <SpanTypeIcon name={node.name} className="mt-0.5" />
        <span className="flex-1 min-w-0">
          <span className="flex items-center gap-2 min-w-0">
            <span
              className={`text-sm truncate ${isSelected ? 'text-violet-900 font-medium' : 'text-gray-800'}`}
            >
              {getSpanDisplayName(node)}
            </span>
            {relativeLabel && (
              <span className="text-[10px] text-gray-400 tabular-nums shrink-0">{relativeLabel}</span>
            )}
            <span className="text-xs text-gray-500 tabular-nums shrink-0 ml-auto">{durationLabel}</span>
          </span>
          {preview && (
            <p className="text-[11px] text-gray-500 truncate mt-0.5 pr-1">{preview}</p>
          )}
        </span>
      </button>
      {hasChildren &&
        !isCollapsed &&
        node.children.map((child) => (
          <SpanTreeRow
            key={child.span_id}
            node={child}
            depth={depth + 1}
            selectedSpanId={selectedSpanId}
            collapsedIds={collapsedIds}
            rootStartMs={rootStartMs}
            allSpans={allSpans}
            onSelect={onSelect}
            onToggle={onToggle}
          />
        ))}
    </>
  )
}

export interface TraceTreeProps {
  trace: ObservabilityCallTrace
  embedded?: boolean
  callStartMs?: number | null
  audioCurrentTimeSec?: number | null
  selectedSpanId?: string | null
  onSelectSpan?: (span: ObservabilityTraceSpan) => void
  showTimeline?: boolean
  syncAudioToSelection?: boolean
}

export default function TraceTree({
  trace,
  embedded = false,
  callStartMs = null,
  audioCurrentTimeSec = null,
  selectedSpanId: controlledSelectedSpanId,
  onSelectSpan,
  showTimeline: showTimelineProp = true,
  syncAudioToSelection = true,
}: TraceTreeProps) {
  const tree = useMemo(() => buildSpanTree(trace), [trace])
  const allSpans = useMemo(() => flattenSpanTree(tree), [tree])
  const stats = useMemo(() => computeTraceStats(allSpans), [allSpans])
  const rootStartMs = useMemo(() => getTraceRootStartMs(allSpans), [allSpans])

  const [internalSelectedSpanId, setInternalSelectedSpanId] = useState<string | null>(null)
  const selectedSpanId = controlledSelectedSpanId ?? internalSelectedSpanId

  const [collapsedIds, setCollapsedIds] = useState<Set<string>>(() => getDefaultCollapsedSpanIds(tree))

  useEffect(() => {
    setCollapsedIds(getDefaultCollapsedSpanIds(tree))
  }, [trace.trace_id])

  useEffect(() => {
    if (controlledSelectedSpanId !== undefined) return
    if (!internalSelectedSpanId && allSpans.length > 0) {
      const firstTurn = allSpans.find((s) => (s.name === 'turn' || isElevenLabsTurnSpan(s)) && s.span_id)
      const defaultId = firstTurn?.span_id ?? allSpans.find((s) => s.span_id)?.span_id ?? null
      if (defaultId) setInternalSelectedSpanId(defaultId)
    }
  }, [allSpans, internalSelectedSpanId, controlledSelectedSpanId])

  const setSelectedSpanId = useCallback(
    (spanId: string) => {
      if (controlledSelectedSpanId === undefined) {
        setInternalSelectedSpanId(spanId)
      }
      const span = allSpans.find((s) => s.span_id === spanId)
      if (span && onSelectSpan) onSelectSpan(span)
    },
    [allSpans, controlledSelectedSpanId, onSelectSpan],
  )

  const selected = allSpans.find((s) => s.span_id === selectedSpanId) || null

  const toggleCollapsed = (spanId: string) => {
    setCollapsedIds((prev) => {
      const next = new Set(prev)
      if (next.has(spanId)) next.delete(spanId)
      else next.add(spanId)
      return next
    })
  }

  const expandAll = () => setCollapsedIds(new Set())
  const collapseAll = () => setCollapsedIds(new Set(getAllCollapsibleSpanIds(tree)))

  const pct = (part: number) => Math.round((part / stats.totalMs) * 100)

  const playheadOffsetSec = audioCurrentTimeSec ?? null
  const playheadPct =
    playheadOffsetSec !== null && stats.totalMs > 0
      ? Math.min(100, Math.max(0, ((playheadOffsetSec * 1000) / stats.totalMs) * 100))
      : null

  return (
    <div className={embedded ? 'overflow-hidden' : 'rounded-xl border border-gray-200 bg-white overflow-hidden'}>
      <div className={`${embedded ? '' : 'border-b border-gray-100'} px-4 py-3 flex flex-wrap items-center gap-2`}>
        {!embedded && <span className="text-sm font-semibold text-gray-900">Execution Trace</span>}
        <span className="text-xs font-mono bg-gray-100 text-gray-700 px-2 py-1 rounded">{trace.trace_id}</span>
        {trace.trace_source && (
          <span className="text-xs bg-indigo-50 text-indigo-700 px-2 py-1 rounded capitalize">
            {trace.trace_source}
          </span>
        )}
        <span className="text-xs text-gray-500 tabular-nums">
          {formatDuration(stats.totalMs, 'seconds')} total
        </span>
        <span className="text-xs bg-violet-50 text-violet-700 px-2 py-1 rounded">LLM {pct(stats.llmMs)}%</span>
        <span className="text-xs bg-cyan-50 text-cyan-700 px-2 py-1 rounded">STT {pct(stats.sttMs)}%</span>
        <span className="text-xs bg-emerald-50 text-emerald-700 px-2 py-1 rounded">TTS {pct(stats.ttsMs)}%</span>
        <div className="ml-auto flex items-center gap-1">
          <button
            type="button"
            onClick={expandAll}
            className="inline-flex items-center gap-1 text-xs text-gray-500 hover:text-gray-700 px-2 py-1 rounded hover:bg-gray-100"
            title="Expand all spans"
          >
            <ChevronsUpDown className="h-3.5 w-3.5" />
            Expand
          </button>
          <button
            type="button"
            onClick={collapseAll}
            className="inline-flex items-center gap-1 text-xs text-gray-500 hover:text-gray-700 px-2 py-1 rounded hover:bg-gray-100"
            title="Collapse pipeline spans"
          >
            <ChevronsDownUp className="h-3.5 w-3.5" />
            Collapse
          </button>
        </div>
      </div>

      {showTimelineProp && allSpans.length > 0 && (
        <div className="border-b border-gray-100 px-4 py-3 bg-gray-50/60">
          <div className="flex items-center justify-between mb-2">
            <p className="text-[10px] uppercase tracking-wider text-gray-500 font-semibold">Timeline</p>
            {playheadOffsetSec !== null && syncAudioToSelection && (
              <p className="text-[10px] text-indigo-600 tabular-nums font-medium">
                Playhead {formatRelativeOffset(playheadOffsetSec * 1000, 'long')}
              </p>
            )}
          </div>
          <div className="relative h-2 rounded-full bg-gray-200 overflow-hidden">
            {allSpans
              .filter((span) => span.span_id && (span.name === 'turn' || isElevenLabsTurnSpan(span)))
              .map((span) => {
                const startOffset = ((span.start_time || rootStartMs) - rootStartMs) / stats.totalMs
                const width = Math.max((span.duration_ms || 0) / stats.totalMs, 0.008)
                const isActive = span.span_id === selectedSpanId
                return (
                  <button
                    key={`tl-turn-${span.span_id}`}
                    type="button"
                    onClick={() => span.span_id && setSelectedSpanId(span.span_id)}
                    className={`absolute top-0 h-2 rounded-sm transition-colors ${
                      isActive ? 'bg-violet-500' : 'bg-violet-300 hover:bg-violet-400'
                    }`}
                    style={{
                      left: `${Math.max(startOffset * 100, 0)}%`,
                      width: `${Math.min(width * 100, 100 - startOffset * 100)}%`,
                    }}
                    title={getSpanDisplayName(span)}
                  />
                )
              })}
            {playheadPct !== null && syncAudioToSelection && (
              <span
                className="absolute top-0 bottom-0 w-0.5 bg-rose-500 z-10 pointer-events-none"
                style={{ left: `${playheadPct}%` }}
              />
            )}
          </div>
          <div className="flex justify-between mt-1 text-[10px] text-gray-400 tabular-nums">
            <span>+0:00</span>
            <span>{formatRelativeOffset(stats.totalMs)}</span>
          </div>
        </div>
      )}

      <div className="flex flex-col lg:flex-row min-h-[420px] max-h-[560px]">
        <aside className="lg:w-80 shrink-0 border-b lg:border-b-0 lg:border-r border-gray-100 flex flex-col min-h-0">
          <div className="px-3 py-2 border-b border-gray-100 shrink-0">
            <p className="text-xs font-semibold text-gray-700">Spans ({allSpans.length})</p>
          </div>
          <div className="flex-1 overflow-y-auto py-1">
            {tree.filter((node) => node.span_id).map((node) => (
              <SpanTreeRow
                key={node.span_id!}
                node={node}
                depth={0}
                selectedSpanId={selectedSpanId}
                collapsedIds={collapsedIds}
                rootStartMs={rootStartMs}
                allSpans={allSpans}
                onSelect={setSelectedSpanId}
                onToggle={toggleCollapsed}
              />
            ))}
          </div>
        </aside>

        <main className="flex-1 min-w-0 min-h-0 bg-white">
          {!selected ? (
            <div className="h-full flex items-center justify-center p-8 text-sm text-gray-500">
              Select a span to inspect details.
            </div>
          ) : (
            <SpanDetailPanel
              span={selected}
              allSpans={allSpans}
              rootStartMs={rootStartMs}
              callStartMs={callStartMs}
            />
          )}
        </main>
      </div>
    </div>
  )
}
