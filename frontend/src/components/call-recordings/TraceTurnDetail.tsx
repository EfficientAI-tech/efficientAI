import { LayerResponseDonut, TraceSection, TurnTotalsBar } from './TraceCharts'
import { formatMs, type PipelineMode, type TraceToolCall } from './traceUtils'

type ComponentKind = 'stt' | 'llm' | 'tts' | 's2s' | 'tool' | 'retrieval'

const STAGE_LABELS: Record<ComponentKind, string> = {
  stt: 'STT',
  llm: 'LLM',
  tts: 'TTS',
  s2s: 'S2S',
  tool: 'Tool',
  retrieval: 'Retrieval',
}

export interface TraceTurnRow {
  turnNumber: number
  offsetMs: number
  sttMs?: number | null
  llmMs?: number | null
  ttsMs?: number | null
  s2sMs?: number | null
  totalMs?: number | null
  talkOver?: boolean
  interrupted?: boolean
  incomplete?: boolean
  models: Partial<Record<ComponentKind, string>>
  toolCalls?: TraceToolCall[]
  retrievals?: Array<{ source?: string; documents?: number; latency_ms?: number | null }>
  spans: Array<{
    id: string
    kind: ComponentKind | null
    name: string
    model?: string
    durationMs: number | null
  }>
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

interface ComponentAggregates {
  [key: string]: { p50?: number; p90?: number; p95?: number } | undefined
}

function formatMsLocal(value?: number | null): string {
  return formatMs(value)
}

function StageChip({ label }: { label: string }) {
  return (
    <span className="inline-flex rounded-md border border-primary-300 bg-primary-50/60 px-2 py-0.5 text-xs font-semibold text-primary-800">
      {label}
    </span>
  )
}

function RetrievalTable({ rows }: { rows: TraceTurnRow[] }) {
  const withRetrieval = rows.filter((row) => (row.retrievals?.length ?? 0) > 0)
  if (withRetrieval.length === 0) return null

  return (
    <TraceSection title="Retrieval" subtitle="RAG / knowledge lookups on each turn">
      <div className="overflow-hidden rounded-lg border border-primary-200 bg-white">
        <table className="min-w-full text-sm">
          <thead>
            <tr className="border-b border-gray-100 bg-gray-50/80 text-left text-[10px] font-semibold uppercase tracking-wider text-gray-400">
              <th className="px-4 py-2.5">Turn</th>
              <th className="px-4 py-2.5">Source</th>
              <th className="px-4 py-2.5 text-right">Docs</th>
              <th className="px-4 py-2.5 text-right">Duration</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {withRetrieval.flatMap((row) =>
              (row.retrievals ?? []).map((hit, index) => (
                <tr key={`${row.turnNumber}-ret-${index}`}>
                  <td className="px-4 py-2.5 font-medium text-gray-700">T{row.turnNumber}</td>
                  <td className="px-4 py-2.5 font-mono text-xs text-gray-800">{hit.source ?? '—'}</td>
                  <td className="px-4 py-2.5 text-right tabular-nums text-gray-800">
                    {hit.documents != null ? hit.documents : '—'}
                  </td>
                  <td className="px-4 py-2.5 text-right tabular-nums text-gray-800">
                    {formatMsLocal(hit.latency_ms)}
                  </td>
                </tr>
              )),
            )}
          </tbody>
        </table>
      </div>
    </TraceSection>
  )
}

function ToolCallTable({ rows }: { rows: TraceTurnRow[] }) {
  const withTools = rows.filter((row) => (row.toolCalls?.length ?? 0) > 0)
  if (withTools.length === 0) return null

  return (
    <TraceSection title="Tool calls" subtitle="Tools the agent called on each turn">
      <div className="overflow-hidden rounded-lg border border-primary-200 bg-white">
        <table className="min-w-full text-sm">
          <thead>
            <tr className="border-b border-gray-100 bg-gray-50/80 text-left text-[10px] font-semibold uppercase tracking-wider text-gray-400">
              <th className="px-4 py-2.5">Turn</th>
              <th className="px-4 py-2.5">Tool</th>
              <th className="px-4 py-2.5 text-right">Duration</th>
              <th className="px-4 py-2.5">Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {withTools.flatMap((row) =>
              (row.toolCalls ?? []).map((call, index) => (
                <tr key={`${row.turnNumber}-${call.name}-${index}`}>
                  <td className="px-4 py-2.5 font-medium text-gray-700">T{row.turnNumber}</td>
                  <td className="px-4 py-2.5 font-mono text-xs text-gray-800">{call.name}</td>
                  <td className="px-4 py-2.5 text-right tabular-nums text-gray-800">{formatMsLocal(call.latencyMs)}</td>
                  <td className="px-4 py-2.5">
                    {call.error ? (
                      <span className="inline-flex rounded-md border border-rose-200 bg-rose-50 px-2 py-0.5 text-xs font-semibold text-rose-800">
                        Error
                      </span>
                    ) : (
                      <span className="text-xs text-gray-500">Ok</span>
                    )}
                  </td>
                </tr>
              )),
            )}
          </tbody>
        </table>
      </div>
    </TraceSection>
  )
}

function ChatPipelineStageTable({
  models,
  aggregates,
}: {
  models: PipelineModels
  aggregates?: ComponentAggregates | null
}) {
  const stats = aggregates?.llm_ttfb_ms
  const meta = models.llm
  if (!meta?.model && !meta?.provider && !stats) return null

  return (
    <div className="overflow-hidden rounded-lg border border-primary-200 bg-white">
      <table className="min-w-full text-sm">
        <thead>
          <tr className="border-b border-gray-100 bg-gray-50/80 text-left text-[10px] font-semibold uppercase tracking-wider text-gray-400">
            <th className="px-4 py-2.5">Stage</th>
            <th className="px-4 py-2.5">Provider</th>
            <th className="px-4 py-2.5">Model</th>
            <th className="px-4 py-2.5 text-right">p50</th>
            <th className="px-4 py-2.5 text-right">p90</th>
            <th className="px-4 py-2.5 text-right">p95</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td className="px-4 py-2.5">
              <StageChip label="LLM" />
            </td>
            <td className="px-4 py-2.5 capitalize text-gray-700">{meta?.provider ?? '—'}</td>
            <td className="px-4 py-2.5 font-mono text-xs text-gray-600">{meta?.model ?? '—'}</td>
            <td className="px-4 py-2.5 text-right tabular-nums font-semibold text-primary-800">
              {formatMsLocal(stats?.p50)}
            </td>
            <td className="px-4 py-2.5 text-right tabular-nums text-gray-800">{formatMsLocal(stats?.p90)}</td>
            <td className="px-4 py-2.5 text-right tabular-nums text-gray-800">{formatMsLocal(stats?.p95)}</td>
          </tr>
        </tbody>
      </table>
    </div>
  )
}

function PipelineStageTable({
  models,
  aggregates,
}: {
  models: PipelineModels
  aggregates?: ComponentAggregates | null
}) {
  const rows = (['stt', 'llm', 'tts', 's2s'] as const)
    .map((kind) => {
      const meta = models[kind]
      const stats = aggregates?.[`${kind}_ttfb_ms`]
      if (!meta?.model && !meta?.provider && !stats) return null
      return { kind, meta, stats }
    })
    .filter(Boolean) as Array<{
      kind: ComponentKind
      meta?: ComponentMeta
      stats?: { p50?: number; p90?: number; p95?: number }
    }>

  if (rows.length === 0) return null

  return (
    <div className="overflow-hidden rounded-lg border border-primary-200 bg-white">
      <table className="min-w-full text-sm">
        <thead>
          <tr className="border-b border-gray-100 bg-gray-50/80 text-left text-[10px] font-semibold uppercase tracking-wider text-gray-400">
            <th className="px-4 py-2.5">Stage</th>
            <th className="px-4 py-2.5">Provider</th>
            <th className="px-4 py-2.5">Model</th>
            <th className="px-4 py-2.5 text-right">p50</th>
            <th className="px-4 py-2.5 text-right">p90</th>
            <th className="px-4 py-2.5 text-right">p95</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100">
          {rows.map(({ kind, meta, stats }) => (
            <tr key={kind}>
              <td className="px-4 py-2.5">
                <StageChip label={STAGE_LABELS[kind]} />
              </td>
              <td className="px-4 py-2.5 capitalize text-gray-700">{meta?.provider ?? '—'}</td>
              <td className="px-4 py-2.5 font-mono text-xs text-gray-600">{meta?.model ?? '—'}</td>
              <td className="px-4 py-2.5 text-right tabular-nums font-semibold text-primary-800">{formatMsLocal(stats?.p50)}</td>
              <td className="px-4 py-2.5 text-right tabular-nums text-gray-800">{formatMsLocal(stats?.p90)}</td>
              <td className="px-4 py-2.5 text-right tabular-nums text-gray-800">{formatMsLocal(stats?.p95)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export default function TraceTurnDetail({
  rows,
  pipelineModels,
  pipelineMode,
  componentAggregates,
}: {
  rows: TraceTurnRow[]
  pipelineModels: PipelineModels
  pipelineMode?: PipelineMode | null
  componentAggregates?: ComponentAggregates | null
}) {
  if (rows.length === 0) {
    return <p className="py-12 text-center text-sm text-gray-500">No turn data</p>
  }

  const barRows = rows
    .filter((r) => r.totalMs != null && r.totalMs > 0)
    .map((r) => ({
      turn: `T${r.turnNumber}`,
      total: r.totalMs!,
      talkOver: r.talkOver,
      interrupted: r.interrupted,
      incomplete: r.incomplete,
    }))

  return (
    <div className="space-y-8">
      <TraceSection title="Session overview" subtitle="Stage breakdown and per-turn response latency">
        <div className="grid gap-4 md:grid-cols-2">
          <LayerResponseDonut rows={rows} />
          {barRows.length > 0 ? (
            <TurnTotalsBar rows={barRows} />
          ) : (
            <div className="flex items-center justify-center rounded-lg border border-gray-200 bg-white p-4 text-sm text-gray-500">
              No per-turn response data
            </div>
          )}
        </div>
      </TraceSection>

      <ToolCallTable rows={rows} />

      <RetrievalTable rows={rows} />

      <TraceSection
        title="Pipeline"
        subtitle={
          pipelineMode === 'chat'
            ? 'Chat model and LLM time to first token'
            : 'Models and TTFB percentiles per stage (p50 / p90 / p95)'
        }
      >
        {pipelineMode === 'chat' ? (
          <ChatPipelineStageTable models={pipelineModels} aggregates={componentAggregates} />
        ) : (
          <PipelineStageTable models={pipelineModels} aggregates={componentAggregates} />
        )}
      </TraceSection>
    </div>
  )
}
