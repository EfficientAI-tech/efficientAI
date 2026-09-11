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
import {
  extractProviderCostSummary,
  formatProviderCostAmount,
  type ProviderCostUnit,
} from '../../lib/voiceProviderMetrics'

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

function parseElevenLabsCostSlices(callData: Record<string, unknown>): CostSlice[] {
  const raw = callData as Record<string, any>
  const metadata = raw.raw_data?.metadata
  const charging = metadata?.charging
  if (charging && typeof charging === 'object') {
    const slices: CostSlice[] = []
    const llmPrice = Number(charging.llm_price)
    const platformPrice = Number(charging.platform_price)
    if (llmPrice > 0) {
      slices.push({ key: 'llm', label: 'LLM', value: llmPrice, color: COST_COLORS.llm })
    }
    if (platformPrice > 0) {
      slices.push({ key: 'call', label: 'Voice', value: platformPrice, color: COST_COLORS.tts })
    }
    if (slices.length) return slices
  }
  const fiat = metadata?.cost_fiat
  if (typeof fiat === 'number' && fiat > 0) {
    return [{ key: 'total', label: 'Total', value: fiat, color: COST_COLORS.other }]
  }
  return []
}

function parseElevenLabsPipeline(callData: Record<string, unknown>): {
  stages: PipelineStage[]
  turns: TurnLatencyRow[]
  avgTurnMs: number | null
} {
  const raw = callData as Record<string, any>
  const transcript = raw.raw_data?.transcript
  if (!Array.isArray(transcript)) {
    return { stages: [], turns: [], avgTurnMs: null }
  }

  const turnRows: TurnLatencyRow[] = transcript
    .filter((entry: any) => entry?.role === 'agent' && entry?.conversation_turn_metrics?.metrics)
    .map((entry: any, idx: number) => {
      const metrics = entry.conversation_turn_metrics.metrics
      const sttMs = metrics.convai_turn_asr_latency?.elapsed_time
        ? Math.round(metrics.convai_turn_asr_latency.elapsed_time * 1000)
        : undefined
      const llmMs = metrics.convai_llm_service_ttfb?.elapsed_time
        ? Math.round(metrics.convai_llm_service_ttfb.elapsed_time * 1000)
        : undefined
      const ttsMs = metrics.convai_tts_service_ttfb?.elapsed_time
        ? Math.round(metrics.convai_tts_service_ttfb.elapsed_time * 1000)
        : undefined
      const parts = [sttMs, llmMs, ttsMs].filter((v): v is number => v !== undefined)
      return {
        turn: idx + 1,
        stt: sttMs,
        llm: llmMs,
        tts: ttsMs,
        total: parts.length ? parts.reduce((sum, value) => sum + value, 0) : undefined,
      }
    })
    .filter((row: TurnLatencyRow) => row.llm !== undefined || row.tts !== undefined || row.stt !== undefined)

  const average = (values: number[]) =>
    values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : 0

  const stages: PipelineStage[] = [
    {
      key: 'stt',
      label: 'ASR',
      ms: average(turnRows.map((row) => row.stt).filter((v): v is number => v !== undefined)),
      color: STAGE_COLORS.stt,
      icon: Mic,
    },
    {
      key: 'llm',
      label: 'LLM',
      ms: average(turnRows.map((row) => row.llm).filter((v): v is number => v !== undefined)),
      color: STAGE_COLORS.llm,
      icon: Brain,
    },
    {
      key: 'tts',
      label: 'TTS',
      ms: average(turnRows.map((row) => row.tts).filter((v): v is number => v !== undefined)),
      color: STAGE_COLORS.tts,
      icon: Speaker,
    },
  ].filter((stage) => stage.ms > 0)

  const avgTurnMs = turnRows.length
    ? Math.round(turnRows.reduce((sum, row) => sum + (row.total ?? 0), 0) / turnRows.length)
    : null

  return { stages, turns: turnRows, avgTurnMs }
}

function parseRetellCostSlices(callData: Record<string, unknown>): CostSlice[] {
  const raw = callData as Record<string, any>
  const colors = [STAGE_COLORS.stt, STAGE_COLORS.tts, STAGE_COLORS.llm, STAGE_COLORS.transport, STAGE_COLORS.s2s]
  return (raw.call_cost?.product_costs || []).map((item: any, idx: number) => ({
    key: String(item.product || idx),
    label: String(item.product || 'Product').replace(/_/g, ' '),
    value: Number(item.cost ?? 0) / 100,
    color: colors[idx % colors.length],
  })).filter((s: CostSlice) => s.value > 0)
}

function parseSmallestCostSlices(callData: Record<string, unknown>): CostSlice[] {
  const raw = (callData as Record<string, any>).raw_data || {}
  const rawCost = raw.callCost
  if (rawCost && typeof rawCost === 'object') {
    const slices: CostSlice[] = []
    const callCharge = Number(rawCost.callCharge ?? rawCost.call ?? 0)
    const llmCharge = Number(rawCost.llmCharge ?? rawCost.llm ?? 0)
    if (callCharge > 0) {
      slices.push({ key: 'call', label: 'Call', value: callCharge, color: COST_COLORS.transport })
    }
    if (llmCharge > 0) {
      slices.push({ key: 'llm', label: 'LLM', value: llmCharge, color: COST_COLORS.llm })
    }
    if (slices.length) return slices
    const total = Number(rawCost.total ?? rawCost.totalCredits ?? 0)
    if (total > 0) {
      return [{ key: 'total', label: 'Total', value: total, color: COST_COLORS.other }]
    }
  }
  const analysisCost = (callData as Record<string, any>).analysis?.cost
  if (typeof analysisCost === 'number' && analysisCost > 0) {
    return [{ key: 'total', label: 'Total', value: analysisCost, color: COST_COLORS.other }]
  }
  const topCost = Number(raw.cost ?? (callData as Record<string, any>).cost ?? 0)
  if (topCost > 0) {
    return [{ key: 'total', label: 'Total', value: topCost, color: COST_COLORS.other }]
  }
  return []
}

function parseRetellPipeline(callData: Record<string, unknown>): {
  stages: PipelineStage[]
  turns: TurnLatencyRow[]
  avgTurnMs: number | null
} {
  const raw = callData as Record<string, any>
  const latency = raw.latency || {}
  const stages: PipelineStage[] = [
    { key: 'asr', label: 'ASR', ms: latency.asr?.p50 ?? 0, color: STAGE_COLORS.stt, icon: Mic },
    { key: 'llm', label: 'LLM', ms: latency.llm?.p50 ?? 0, color: STAGE_COLORS.llm, icon: Brain },
    { key: 'tts', label: 'TTS', ms: latency.tts?.p50 ?? 0, color: STAGE_COLORS.tts, icon: Speaker },
    { key: 'e2e', label: 'E2E', ms: latency.e2e?.p50 ?? 0, color: STAGE_COLORS.endpointing, icon: Activity },
  ].filter((stage) => stage.ms > 0)
  return { stages, turns: [], avgTurnMs: latency.e2e?.p50 ?? null }
}

function parseSmallestPipeline(callData: Record<string, unknown>): {
  stages: PipelineStage[]
  turns: TurnLatencyRow[]
  avgTurnMs: number | null
} {
  const raw = callData as Record<string, any>
  const rawData = raw.raw_data || {}
  const stats = raw.analysis?.latency_stats || rawData.latencyStats || {}

  const readMs = (...keys: string[]) => {
    for (const key of keys) {
      const value = stats[key] ?? rawData[key]
      const parsed = Number(value)
      if (Number.isFinite(parsed) && parsed > 0) return parsed
    }
    return 0
  }

  const stages: PipelineStage[] = [
    {
      key: 'stt',
      label: 'ASR',
      ms: readMs('average_transcriber_latency', 'transcriberLatency', 'asrLatency', 'stt'),
      color: STAGE_COLORS.stt,
      icon: Mic,
    },
    {
      key: 'llm',
      label: 'LLM',
      ms: readMs('average_agent_latency', 'agentLatency', 'llmLatency', 'llm'),
      color: STAGE_COLORS.llm,
      icon: Brain,
    },
    {
      key: 'tts',
      label: 'TTS',
      ms: readMs('average_synthesizer_latency', 'synthesizerLatency', 'ttsLatency', 'tts'),
      color: STAGE_COLORS.tts,
      icon: Speaker,
    },
  ].filter((stage) => stage.ms > 0)

  const avgTurnMs = stages.length
    ? Math.round(stages.reduce((sum, stage) => sum + stage.ms, 0) / stages.length)
    : null

  return { stages, turns: [], avgTurnMs }
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
    if (platform === 'elevenlabs') return parseElevenLabsCostSlices(callData)
    if (platform === 'smallest') return parseSmallestCostSlices(callData)
    return parseVapiCostSlices(callData)
  }, [callData, platform])

  const costSummary = useMemo(
    () => extractProviderCostSummary(platform, callData),
    [callData, platform],
  )
  const costUnit: ProviderCostUnit = costSummary?.unit ?? 'usd'
  const total =
    totalCost ??
    costSummary?.total ??
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
          <p className="mt-1 text-2xl font-bold text-gray-900">{formatProviderCostAmount(total, costUnit)}</p>
          {platform === 'elevenlabs' && costSummary?.creditNote != null ? (
            <p className="mt-1 text-xs text-gray-500">
              {Math.round(costSummary.creditNote).toLocaleString()} credits
            </p>
          ) : null}
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
              <Tooltip formatter={(v: number) => formatProviderCostAmount(v, costUnit)} />
            </PieChart>
          </ResponsiveContainer>
          <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
            <p className="text-lg font-bold text-gray-900">
              {costUnit === 'credits' ? Math.round(total).toLocaleString() : `$${total.toFixed(2)}`}
            </p>
            <p className="text-[10px] uppercase tracking-wider text-gray-400">
              {costUnit === 'credits' ? 'Credits' : 'Total'}
            </p>
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
                    <span className="shrink-0 font-medium text-gray-900">
                      {formatProviderCostAmount(slice.value, costUnit)}
                    </span>
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
          {total > 0 ? ((topDriver.value / total) * 100).toFixed(1) : '0'}% ({formatProviderCostAmount(topDriver.value, costUnit)})
        </div>
      ) : null}

      <div className="grid gap-3 sm:grid-cols-3">
        {slices
          .filter((s) => ['stt', 'llm', 'tts', 'call'].includes(s.key))
          .map((slice) => {
            const breakdown = (callData as any).costBreakdown || (callData as any).cost_breakdown || {}
            const charging = (callData as any).raw_data?.metadata?.charging
            const promptTokens = breakdown.llmPromptTokens ?? breakdown.llm_prompt_tokens
            const ttsChars = breakdown.ttsCharacters ?? breakdown.tts_characters
            const ttsUsage = charging?.tts_usage
            const detail =
              slice.key === 'llm'
                ? promptTokens != null
                  ? `Prompt ${Number(promptTokens).toLocaleString()} tokens`
                  : 'Language model usage'
                : slice.key === 'tts' || slice.key === 'call'
                  ? ttsChars != null
                    ? `${Number(ttsChars).toLocaleString()} characters`
                    : ttsUsage?.total_characters != null
                      ? `${Number(ttsUsage.total_characters).toLocaleString()} characters`
                      : slice.key === 'call'
                        ? 'Voice platform usage'
                        : 'Text-to-speech synthesis'
                  : 'Speech-to-text processing'
            return (
              <div key={slice.key} className="rounded-xl border border-gray-200 bg-white p-4">
                <p className="text-xs font-semibold uppercase tracking-wider text-gray-500">{slice.label}</p>
                <p className="mt-1 text-xl font-bold text-gray-900">
                  {formatProviderCostAmount(slice.value, costUnit)}
                </p>
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
    if (platform === 'elevenlabs') return parseElevenLabsPipeline(callData)
    if (platform === 'retell') return parseRetellPipeline(callData)
    if (platform === 'smallest') return parseSmallestPipeline(callData)
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
