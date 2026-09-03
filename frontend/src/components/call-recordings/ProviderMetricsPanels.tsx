import { useMemo } from 'react'
import {
  Activity,
  ArrowLeftRight,
  Brain,
  Gauge,
  Mic,
  Speaker,
} from 'lucide-react'
import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from 'recharts'
import { METRIC_COST_COLORS, STAGE_COLORS } from '../../lib/callDetailTheme'

export interface CostSlice {
  key: string
  label: string
  value: number
  color: string
}

export interface PipelineStage {
  key: string
  label: string
  ms: number
  color: string
  icon: typeof Mic
}

export interface TurnLatencyRow {
  turn: number
  stt?: number
  endpointing?: number
  llm?: number
  tts?: number
  total?: number
}

const COST_COLORS: Record<string, string> = METRIC_COST_COLORS

function parseVapiCostSlices(callData: Record<string, unknown>): CostSlice[] {
  const raw = callData as Record<string, any>
  const breakdown = raw.costBreakdown || raw.cost_breakdown || {}
  const fromBreakdown: CostSlice[] = [
    { key: 'stt', label: 'STT', value: breakdown.stt ?? 0, color: COST_COLORS.stt },
    { key: 'llm', label: 'LLM', value: breakdown.llm ?? 0, color: COST_COLORS.llm },
    { key: 'tts', label: 'TTS', value: breakdown.tts ?? 0, color: COST_COLORS.tts },
    { key: 'transport', label: 'Transport', value: breakdown.transport ?? 0, color: COST_COLORS.transport },
    { key: 'vapi', label: 'Vapi Platform', value: breakdown.vapi ?? 0, color: COST_COLORS.vapi },
  ]
  const analysisTotal =
    (breakdown.analysis?.summary ?? 0) +
    (breakdown.analysis?.success_evaluation ?? 0) +
    (breakdown.analysis?.structured_data ?? 0)
  if (analysisTotal > 0) {
    fromBreakdown.push({ key: 'analysis', label: 'Analysis', value: analysisTotal, color: COST_COLORS.analysis })
  }

  const slices = fromBreakdown.filter((s) => s.value > 0)
  if (slices.length) return slices

  for (const item of raw.costs || []) {
    if (!item || typeof item !== 'object') continue
    const type = String(item.type || 'other').toLowerCase()
    const key = type.includes('transcriber') ? 'stt' : type.includes('model') ? 'llm' : type.includes('voice') ? 'tts' : type.includes('vapi') ? 'vapi' : type
    const label = String(item.type || 'Cost')
    const value = Number(item.cost ?? 0)
    if (value <= 0) continue
    const existing = slices.find((s) => s.key === key)
    if (existing) existing.value += value
    else slices.push({ key, label, value, color: COST_COLORS[key] || COST_COLORS.other })
  }
  return slices
}

function parseVapiPipeline(callData: Record<string, unknown>): {
  stages: PipelineStage[]
  turns: TurnLatencyRow[]
  avgTurnMs: number | null
} {
  const raw = callData as Record<string, any>
  const perf = raw.artifact?.performanceMetrics || {}
  const stats = raw.analysis?.latency_stats || {}

  const stages: PipelineStage[] = [
    { key: 'transport_in', label: 'From Transport', ms: perf.fromTransportLatencyAverage ?? stats.from_transport_latency_avg ?? 0, color: STAGE_COLORS.s2s, icon: ArrowLeftRight },
    { key: 'stt', label: 'Transcriber', ms: perf.transcriberLatencyAverage ?? stats.transcriber_latency_avg ?? 0, color: STAGE_COLORS.stt, icon: Mic },
    { key: 'endpointing', label: 'Endpointing', ms: perf.endpointingLatencyAverage ?? stats.endpointing_latency_avg ?? 0, color: STAGE_COLORS.endpointing, icon: Gauge },
    { key: 'llm', label: 'LLM', ms: perf.modelLatencyAverage ?? stats.model_latency_avg ?? 0, color: STAGE_COLORS.llm, icon: Brain },
    { key: 'tts', label: 'Voice', ms: perf.voiceLatencyAverage ?? stats.voice_latency_avg ?? 0, color: STAGE_COLORS.tts, icon: Speaker },
    { key: 'transport_out', label: 'To Transport', ms: perf.toTransportLatencyAverage ?? stats.to_transport_latency_avg ?? 0, color: STAGE_COLORS.transport, icon: ArrowLeftRight },
  ].filter((s) => s.ms > 0)

  const turnRows: TurnLatencyRow[] = (perf.turnLatencies || []).map((turn: any, idx: number) => ({
    turn: Number(turn.turnNumber ?? turn.turn ?? idx + 1),
    stt: turn.transcriberLatency,
    endpointing: turn.endpointingLatency,
    llm: turn.modelLatency,
    tts: turn.voiceLatency,
    total: turn.turnLatency,
  }))

  const avgTurnMs =
    perf.turnLatencyAverage ??
    stats.turn_latency_avg ??
    (turnRows.length
      ? Math.round(turnRows.reduce((sum, t) => sum + (t.total ?? 0), 0) / turnRows.length)
      : null)

  return { stages, turns: turnRows, avgTurnMs }
}

function parseRetellCostSlices(callData: Record<string, unknown>): CostSlice[] {
  const raw = callData as Record<string, any>
  const colors = [STAGE_COLORS.stt, STAGE_COLORS.tts, STAGE_COLORS.llm, STAGE_COLORS.transport, STAGE_COLORS.s2s]
  return (raw.call_cost?.product_costs || []).map((item: any, idx: number) => ({
    key: String(item.product || idx),
    label: String(item.product || 'Product').replace(/_/g, ' '),
    value: Number(item.cost ?? 0),
    color: colors[idx % colors.length],
  })).filter((s: CostSlice) => s.value > 0)
}

export function ProviderCostPanel({
  callData,
  platform,
  totalCost,
  durationSec,
}: {
  callData: Record<string, unknown>
  platform?: string | null
  totalCost?: number | null
  durationSec?: number | null
}) {
  const slices = useMemo(() => {
    if (platform === 'retell') return parseRetellCostSlices(callData)
    return parseVapiCostSlices(callData)
  }, [callData, platform])

  const total =
    totalCost ??
    (slices.reduce((sum, s) => sum + s.value, 0) ||
      Number((callData as any).cost ?? (callData as any).call_cost?.combined_cost ?? 0))

  const topDriver = slices.length
    ? [...slices].sort((a, b) => b.value - a.value)[0]
    : null

  if (!slices.length && !total) {
    return <p className="py-12 text-center text-sm text-gray-500">No cost data available yet.</p>
  }

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-3 gap-3">
        <div className="rounded-xl border border-gray-200 bg-white p-4">
          <p className="text-xs font-medium text-gray-500">Total cost</p>
          <p className="mt-1 text-2xl font-bold text-gray-900">${total.toFixed(4)}</p>
        </div>
        <div className="rounded-xl border border-gray-200 bg-white p-4">
          <p className="text-xs font-medium text-gray-500">Duration</p>
          <p className="mt-1 text-2xl font-bold text-gray-900">
            {durationSec != null ? `${Math.round(durationSec)}s` : '—'}
          </p>
        </div>
        <div className="rounded-xl border border-gray-200 bg-white p-4">
          <p className="text-xs font-medium text-gray-500">Categories</p>
          <p className="mt-1 text-2xl font-bold text-gray-900">{slices.length}</p>
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-[220px_1fr]">
        <div className="relative flex items-center justify-center rounded-xl border border-gray-200 bg-white p-4">
          <ResponsiveContainer width="100%" height={200}>
            <PieChart>
              <Pie
                data={slices}
                dataKey="value"
                nameKey="label"
                cx="50%"
                cy="50%"
                innerRadius={52}
                outerRadius={78}
                paddingAngle={2}
                stroke="none"
              >
                {slices.map((slice) => (
                  <Cell key={slice.key} fill={slice.color} />
                ))}
              </Pie>
              <Tooltip formatter={(v: number) => `$${v.toFixed(4)}`} />
            </PieChart>
          </ResponsiveContainer>
          <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
            <p className="text-lg font-bold text-gray-900">${total.toFixed(2)}</p>
            <p className="text-[10px] uppercase tracking-wider text-gray-400">Total</p>
          </div>
        </div>

        <div className="space-y-2 rounded-xl border border-gray-200 bg-white p-4">
          {slices.map((slice) => {
            const pct = total > 0 ? (slice.value / total) * 100 : 0
            return (
              <div key={slice.key} className="flex items-center gap-3">
                <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ backgroundColor: slice.color }} />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center justify-between gap-2 text-sm">
                    <span className="truncate text-gray-700">{slice.label}</span>
                    <span className="shrink-0 font-medium text-gray-900">${slice.value.toFixed(4)}</span>
                  </div>
                  <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-gray-100">
                    <div className="h-full rounded-full" style={{ width: `${pct}%`, backgroundColor: slice.color }} />
                  </div>
                  <p className="mt-0.5 text-[10px] text-gray-400">{pct.toFixed(1)}% of total</p>
                </div>
              </div>
            )
          })}
        </div>
      </div>

      {topDriver ? (
        <div className="rounded-xl border border-violet-100 bg-violet-50/60 px-4 py-3 text-sm text-violet-900">
          <span className="font-medium">Top driver:</span> {topDriver.label} accounts for{' '}
          {total > 0 ? ((topDriver.value / total) * 100).toFixed(1) : '0'}% (${topDriver.value.toFixed(4)})
        </div>
      ) : null}

      <div className="grid gap-3 sm:grid-cols-3">
        {slices
          .filter((s) => ['stt', 'llm', 'tts'].includes(s.key))
          .map((slice) => {
            const breakdown = (callData as any).costBreakdown || (callData as any).cost_breakdown || {}
            const promptTokens = breakdown.llmPromptTokens ?? breakdown.llm_prompt_tokens
            const ttsChars = breakdown.ttsCharacters ?? breakdown.tts_characters
            const detail =
              slice.key === 'llm'
                ? promptTokens != null
                  ? `Prompt ${Number(promptTokens).toLocaleString()} tokens`
                  : 'Language model usage'
                : slice.key === 'tts'
                  ? ttsChars != null
                    ? `${Number(ttsChars).toLocaleString()} characters`
                    : 'Text-to-speech synthesis'
                  : 'Speech-to-text processing'
            return (
              <div key={slice.key} className="rounded-xl border border-gray-200 bg-white p-4">
                <p className="text-xs font-semibold uppercase tracking-wider text-gray-500">{slice.label}</p>
                <p className="mt-1 text-xl font-bold text-gray-900">${slice.value.toFixed(4)}</p>
                <p className="mt-2 text-xs text-gray-500">{detail}</p>
              </div>
            )
          })}
      </div>
    </div>
  )
}

export function ProviderLatencyPanel({
  callData,
  platform,
}: {
  callData: Record<string, unknown>
  platform?: string | null
}) {
  const { stages, turns, avgTurnMs } = useMemo(() => {
    if (platform === 'vapi') return parseVapiPipeline(callData)
    const raw = callData as Record<string, any>
    const latency = raw.latency || {}
    const stages: PipelineStage[] = [
      { key: 'asr', label: 'ASR', ms: latency.asr?.p50 ?? 0, color: STAGE_COLORS.stt, icon: Mic },
      { key: 'llm', label: 'LLM', ms: latency.llm?.p50 ?? 0, color: STAGE_COLORS.llm, icon: Brain },
      { key: 'tts', label: 'TTS', ms: latency.tts?.p50 ?? 0, color: STAGE_COLORS.tts, icon: Speaker },
      { key: 'e2e', label: 'E2E', ms: latency.e2e?.p50 ?? 0, color: STAGE_COLORS.endpointing, icon: Activity },
    ].filter((s) => s.ms > 0)
    return { stages, turns: [] as TurnLatencyRow[], avgTurnMs: latency.e2e?.p50 ?? null }
  }, [callData, platform])

  const pipelineTotal = stages.reduce((sum, s) => sum + s.ms, 0) || 1

  if (!stages.length && !turns.length) {
    return <p className="py-12 text-center text-sm text-gray-500">Latency data not available yet.</p>
  }

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-3">
        <div className="rounded-xl border border-gray-200 bg-white p-4">
          <p className="text-xs font-medium text-gray-500">Turns</p>
          <p className="mt-1 text-2xl font-bold text-gray-900">{turns.length || '—'}</p>
        </div>
        <div className="rounded-xl border border-gray-200 bg-white p-4">
          <p className="text-xs font-medium text-gray-500">Avg turn</p>
          <p className="mt-1 text-2xl font-bold text-gray-900">
            {avgTurnMs != null ? `${Math.round(avgTurnMs)}ms` : '—'}
          </p>
        </div>
      </div>

      {stages.length > 0 ? (
        <div className="rounded-xl border border-gray-200 bg-white p-4">
          <p className="mb-3 text-sm font-semibold text-gray-900">Pipeline breakdown</p>
          <div className="flex h-3 overflow-hidden rounded-full bg-gray-100">
            {stages.map((stage) => (
              <div
                key={stage.key}
                title={`${stage.label}: ${Math.round(stage.ms)}ms`}
                style={{ width: `${(stage.ms / pipelineTotal) * 100}%`, backgroundColor: stage.color }}
              />
            ))}
          </div>
          <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {stages.map((stage) => {
              const Icon = stage.icon
              return (
                <div key={stage.key} className="rounded-lg border border-gray-100 bg-gray-50/80 p-3">
                  <div className="flex items-center gap-2">
                    <span className="h-2 w-2 rounded-full" style={{ backgroundColor: stage.color }} />
                    <Icon className="h-3.5 w-3.5 text-gray-500" />
                    <span className="text-xs font-medium text-gray-600">{stage.label}</span>
                  </div>
                  <p className="mt-2 text-lg font-bold text-gray-900">{Math.round(stage.ms)}ms</p>
                </div>
              )
            })}
          </div>
        </div>
      ) : null}

      {turns.length > 0 ? (
        <div className="overflow-hidden rounded-xl border border-gray-200 bg-white">
          <div className="border-b border-gray-100 px-4 py-3">
            <p className="text-sm font-semibold text-gray-900">Latency per turn</p>
            <p className="text-xs text-gray-500">All values in milliseconds</p>
          </div>
          <div className="overflow-x-auto">
            <table className="min-w-full text-sm">
              <thead className="bg-gray-50 text-left text-[10px] font-semibold uppercase tracking-wider text-gray-500">
                <tr>
                  <th className="px-4 py-2">Turn</th>
                  <th className="px-4 py-2">Total</th>
                  <th className="px-4 py-2">STT</th>
                  <th className="px-4 py-2">Endpointing</th>
                  <th className="px-4 py-2">LLM</th>
                  <th className="px-4 py-2">Voice</th>
                </tr>
              </thead>
              <tbody>
                {turns.map((row) => (
                  <tr key={row.turn} className="border-t border-gray-100">
                    <td className="px-4 py-2.5 font-medium text-gray-900">#{row.turn}</td>
                    <td className="px-4 py-2.5 font-semibold text-gray-900">{row.total ?? '—'}ms</td>
                    <td className="px-4 py-2.5 text-gray-600">{row.stt ?? '—'}ms</td>
                    <td className="px-4 py-2.5 text-gray-600">{row.endpointing ?? '—'}ms</td>
                    <td className="px-4 py-2.5 text-gray-600">{row.llm ?? '—'}ms</td>
                    <td className="px-4 py-2.5 text-gray-600">{row.tts ?? '—'}ms</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : null}
    </div>
  )
}
