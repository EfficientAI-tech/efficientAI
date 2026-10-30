import { aggregateCalls } from './callMetrics'
import { globalMetricById, isGlobalMetricId, type GlobalMetricId } from './globalMetrics'
import {
  AGENT_METRICS,
  MOCK_AGENTS,
  MOCK_INTEGRATIONS,
  MOCK_METRICS,
  MOCK_TOOLS,
  SCENARIOS,
  integrationById,
  metricsForAgent,
} from './mockCatalog'
import type { MockCall } from './mockCalls'
import {
  MOCK_MODELS,
  modelById,
  modelsByKind,
  usageModels,
  type ModelKind,
} from './mockUsage'
import { toDayStamp } from './timeBuckets'

export function toolsOnCall(call: MockCall): Array<{ name: string; failed: boolean; integration?: string }> {
  return call.turns
    .map((turn) => turn.toolCall)
    .filter((tool): tool is { name: string; failed: boolean; integration?: string } => Boolean(tool))
}

export function outcomeNotAchieved(call: MockCall): boolean {
  const resolution = call.metric_scores['mock-metric-resolution']
  if (resolution?.failed) return true
  const outcome = call.metric_scores['mock-metric-outcome']
  if (outcome && String(outcome.value) !== 'resolved') return true
  return false
}

export function agentName(agentId: string): string {
  return MOCK_AGENTS.find((agent) => agent.id === agentId)?.name ?? agentId
}

export function dailySeries(
  calls: MockCall[],
  value: (call: MockCall) => number,
): Array<{ day: string; value: number }> {
  const map = new Map<string, number>()
  for (const call of calls) {
    const day = toDayStamp(call.startedAt)
    map.set(day, (map.get(day) ?? 0) + value(call))
  }
  return [...map.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([day, amount]) => ({ day, value: amount }))
}

export function costSummary(calls: MockCall[]) {
  const totalUsd = calls.reduce((sum, call) => sum + call.usage.costUsd, 0)
  const byDay = dailySeries(calls, (call) => call.usage.costUsd)
  return {
    totalUsd,
    callCount: calls.length,
    byDay,
    sparkline: byDay.map((row) => row.value),
  }
}

export interface ModelUsageRow {
  modelId: string
  name: string
  kind: ModelKind
  usage: number
  unit: string
  costUsd: number
  avgLatencyMs: number
  callCount: number
  byAgent: Array<{ agentId: string; agentName: string; usage: number; costUsd: number }>
}

function usageAmount(kind: ModelKind, minutes: number, tokens: number): number {
  return kind === 'llm' ? tokens : minutes
}

export function modelUsageRows(calls: MockCall[]): ModelUsageRow[] {
  const map = new Map<
    string,
    {
      usage: number
      costUsd: number
      latency: number
      latencyN: number
      callIds: Set<string>
      byAgent: Map<string, { usage: number; costUsd: number }>
    }
  >()
  for (const call of calls) {
    for (const piece of usageModels(call.usage)) {
      const model = modelById(piece.modelId)
      if (!model) continue
      const amount = usageAmount(model.kind, piece.minutes, piece.tokens)
      let row = map.get(piece.modelId)
      if (!row) {
        row = {
          usage: 0,
          costUsd: 0,
          latency: 0,
          latencyN: 0,
          callIds: new Set(),
          byAgent: new Map(),
        }
        map.set(piece.modelId, row)
      }
      row.usage += amount
      row.costUsd += piece.costUsd
      row.latency += piece.latencyMs
      row.latencyN += 1
      row.callIds.add(call.id)
      const agent = row.byAgent.get(call.agentId) ?? { usage: 0, costUsd: 0 }
      agent.usage += amount
      agent.costUsd += piece.costUsd
      row.byAgent.set(call.agentId, agent)
    }
  }
  return MOCK_MODELS.map((model) => {
    const row = map.get(model.id)
    return {
      modelId: model.id,
      name: model.name,
      kind: model.kind,
      usage: row?.usage ?? 0,
      unit: model.unit === 'per_1m_tokens' ? 'tokens' : 'min',
      costUsd: row?.costUsd ?? 0,
      avgLatencyMs: row && row.latencyN ? row.latency / row.latencyN : 0,
      callCount: row?.callIds.size ?? 0,
      byAgent: [...(row?.byAgent.entries() ?? [])].map(([agentId, stats]) => ({
        agentId,
        agentName: agentName(agentId),
        usage: stats.usage,
        costUsd: stats.costUsd,
      })),
    }
  }).filter((row) => row.callCount > 0 || row.usage > 0)
}

export function modelUsageByKind(calls: MockCall[]): Record<ModelKind, ModelUsageRow[]> {
  const rows = modelUsageRows(calls)
  return {
    stt: rows.filter((row) => row.kind === 'stt'),
    tts: rows.filter((row) => row.kind === 'tts'),
    llm: rows.filter((row) => row.kind === 'llm'),
    s2s: rows.filter((row) => row.kind === 's2s'),
  }
}

export function modelStats(calls: MockCall[]) {
  const rows = modelUsageRows(calls)
  const used = rows.filter((row) => row.usage > 0)
  const mostUsed = [...used].sort((a, b) => b.usage - a.usage)[0] ?? null
  const leastUsed = [...used].sort((a, b) => a.usage - b.usage)[0] ?? null
  const lowestLatency = [...used].sort((a, b) => a.avgLatencyMs - b.avgLatencyMs)[0] ?? null
  const highestCost = [...used].sort((a, b) => b.costUsd - a.costUsd)[0] ?? null
  return { mostUsed, leastUsed, lowestLatency, highestCost, rows }
}

export function callsForModel(calls: MockCall[], modelId: string): MockCall[] {
  return calls
    .filter((call) => usageModels(call.usage).some((piece) => piece.modelId === modelId))
    .sort((a, b) => b.usage.tokens - a.usage.tokens)
}

export function modelUsageOverTime(calls: MockCall[], modelId: string): Array<{ day: string; value: number }> {
  const model = modelById(modelId)
  const kind = model?.kind ?? 'llm'
  return dailySeries(calls.filter((call) => usageModels(call.usage).some((piece) => piece.modelId === modelId)), (call) => {
    const piece = usageModels(call.usage).find((item) => item.modelId === modelId)
    if (!piece) return 0
    return usageAmount(kind, piece.minutes, piece.tokens)
  })
}

export interface ToolUsageRow {
  id?: string
  name: string
  color?: string
  count: number
  failed: number
  byAgent: Array<{ agentId: string; agentName: string; count: number }>
}

export function toolUsageRows(calls: MockCall[]): ToolUsageRow[] {
  const map = new Map<string, { count: number; failed: number; byAgent: Map<string, number> }>()
  for (const name of MOCK_TOOLS) {
    map.set(name, { count: 0, failed: 0, byAgent: new Map() })
  }
  for (const call of calls) {
    for (const tool of toolsOnCall(call)) {
      const row = map.get(tool.name) ?? { count: 0, failed: 0, byAgent: new Map() }
      row.count += 1
      if (tool.failed) row.failed += 1
      row.byAgent.set(call.agentId, (row.byAgent.get(call.agentId) ?? 0) + 1)
      map.set(tool.name, row)
    }
  }
  return [...map.entries()].map(([name, row]) => ({
    name,
    count: row.count,
    failed: row.failed,
    byAgent: [...row.byAgent.entries()].map(([agentId, count]) => ({
      agentId,
      agentName: agentName(agentId),
      count,
    })),
  }))
}

export function toolCallTotal(calls: MockCall[]): number {
  return calls.reduce((sum, call) => sum + toolsOnCall(call).length, 0)
}

export function distinctToolsUsed(calls: MockCall[]): number {
  return toolUsageRows(calls).filter((row) => row.count > 0).length
}

export function integrationUsageRows(calls: MockCall[]): ToolUsageRow[] {
  const map = new Map<string, { count: number; failed: number; byAgent: Map<string, number> }>()
  for (const item of MOCK_INTEGRATIONS) {
    map.set(item.id, { count: 0, failed: 0, byAgent: new Map() })
  }
  for (const call of calls) {
    for (const tool of toolsOnCall(call)) {
      const id = tool.integration ?? 'postgres'
      const row = map.get(id) ?? { count: 0, failed: 0, byAgent: new Map() }
      row.count += 1
      if (tool.failed) row.failed += 1
      row.byAgent.set(call.agentId, (row.byAgent.get(call.agentId) ?? 0) + 1)
      map.set(id, row)
    }
  }
  return [...map.entries()].map(([id, row]) => ({
    id,
    name: integrationById(id)?.name ?? id,
    color: integrationById(id)?.color,
    count: row.count,
    failed: row.failed,
    byAgent: [...row.byAgent.entries()].map(([agentId, count]) => ({
      agentId,
      agentName: agentName(agentId),
      count,
    })),
  }))
}

export function distinctIntegrationsUsed(calls: MockCall[]): number {
  return integrationUsageRows(calls).filter((row) => row.count > 0).length
}

export function callsForIntegration(calls: MockCall[], integrationId: string): MockCall[] {
  return calls.filter((call) =>
    toolsOnCall(call).some((tool) => (tool.integration ?? '') === integrationId || integrationById(tool.integration ?? '')?.name === integrationId),
  )
}

export function toolCallsOverTime(calls: MockCall[]): Array<{ day: string; [agentId: string]: string | number }> {
  const days = new Map<string, Record<string, number>>()
  for (const call of calls) {
    const day = toDayStamp(call.startedAt)
    const row = days.get(day) ?? {}
    row[call.agentId] = (row[call.agentId] ?? 0) + toolsOnCall(call).length
    days.set(day, row)
  }
  return [...days.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([day, counts]) => ({ day, ...counts }))
}

export function toolsPerCallByAgent(calls: MockCall[]): Array<{ agentId: string; agentName: string; avg: number; total: number; calls: number }> {
  const map = new Map<string, { total: number; calls: number }>()
  for (const call of calls) {
    const row = map.get(call.agentId) ?? { total: 0, calls: 0 }
    row.total += toolsOnCall(call).length
    row.calls += 1
    map.set(call.agentId, row)
  }
  return [...map.entries()].map(([agentId, row]) => ({
    agentId,
    agentName: agentName(agentId),
    avg: row.calls ? row.total / row.calls : 0,
    total: row.total,
    calls: row.calls,
  }))
}

export function toolUseStats(calls: MockCall[]) {
  const rows = toolUsageRows(calls).filter((row) => row.count > 0)
  const mostUsed = [...rows].sort((a, b) => b.count - a.count)[0] ?? null
  const leastUsed = [...rows].sort((a, b) => a.count - b.count)[0] ?? null
  let maxInCall: { agentId: string; agentName: string; count: number; callId: string } | null = null
  let noToolCalls = 0
  for (const call of calls) {
    const count = toolsOnCall(call).length
    if (count === 0) noToolCalls += 1
    if (!maxInCall || count > maxInCall.count) {
      maxInCall = { agentId: call.agentId, agentName: call.agentName, count, callId: call.id }
    }
  }
  return { mostUsed, leastUsed, maxInCall, noToolCalls, rows }
}

export function integrationUseStats(calls: MockCall[]) {
  const rows = integrationUsageRows(calls).filter((row) => row.count > 0)
  const mostUsed = [...rows].sort((a, b) => b.count - a.count)[0] ?? null
  const leastUsed = [...rows].sort((a, b) => a.count - b.count)[0] ?? null
  let maxInCall: { agentId: string; agentName: string; count: number; callId: string } | null = null
  let noToolCalls = 0
  for (const call of calls) {
    const count = toolsOnCall(call).length
    if (count === 0) noToolCalls += 1
    if (!maxInCall || count > maxInCall.count) {
      maxInCall = { agentId: call.agentId, agentName: call.agentName, count, callId: call.id }
    }
  }
  return { mostUsed, leastUsed, maxInCall, noToolCalls, rows }
}

export function callsForTool(calls: MockCall[], toolName: string): MockCall[] {
  return calls.filter((call) => toolsOnCall(call).some((tool) => tool.name === toolName))
}

export function toolUsageOverTime(calls: MockCall[], toolName: string): Array<{ day: string; value: number }> {
  return dailySeries(calls, (call) => toolsOnCall(call).filter((tool) => tool.name === toolName).length)
}

export function integrationUsageOverTime(calls: MockCall[], integrationId: string): Array<{ day: string; value: number }> {
  return dailySeries(
    calls,
    (call) =>
      toolsOnCall(call).filter((tool) => {
        const id = tool.integration ?? ''
        return id === integrationId || integrationById(id)?.name === integrationId
      }).length,
  )
}

export function integrationUsageOverTimeMulti(
  calls: MockCall[],
  integrationIds: string[],
): Array<{ day: string; [id: string]: string | number }> {
  const days = new Map<string, Record<string, number>>()
  for (const call of calls) {
    const day = toDayStamp(call.startedAt)
    const row = days.get(day) ?? {}
    for (const tool of toolsOnCall(call)) {
      const id = tool.integration ?? ''
      if (!integrationIds.includes(id) && !integrationIds.includes(integrationById(id)?.name ?? '')) continue
      const key = integrationIds.includes(id) ? id : integrationById(id)?.name ?? id
      row[key] = (row[key] ?? 0) + 1
    }
    days.set(day, row)
  }
  return [...days.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([day, counts]) => ({ day, ...counts }))
}

export function failureOverTime(calls: MockCall[]): Array<{ day: string; tools: number; outcomes: number }> {
  const days = new Map<string, { tools: number; outcomes: number }>()
  for (const call of calls) {
    const day = toDayStamp(call.startedAt)
    const row = days.get(day) ?? { tools: 0, outcomes: 0 }
    row.tools += call.computed.toolCallFailures
    if (outcomeNotAchieved(call)) row.outcomes += 1
    days.set(day, row)
  }
  return [...days.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([day, row]) => ({ day, ...row }))
}

export function failureSummary(calls: MockCall[]) {
  const toolFailures = calls.reduce((sum, call) => sum + call.computed.toolCallFailures, 0)
  const outcomesNotAchieved = calls.filter(outcomeNotAchieved).length
  return { toolFailures, outcomesNotAchieved }
}

export function durationStats(calls: MockCall[]) {
  if (calls.length === 0) {
    return {
      avg: 0,
      median: 0,
      longest: null as MockCall | null,
      shortest: null as MockCall | null,
      silenceAvg: 0,
      longestPause: 0,
      longestPauseCall: null as MockCall | null,
    }
  }
  const sorted = [...calls].sort((a, b) => a.durationSeconds - b.durationSeconds)
  const mid = Math.floor(sorted.length / 2)
  const median =
    sorted.length % 2 === 0
      ? (sorted[mid - 1].durationSeconds + sorted[mid].durationSeconds) / 2
      : sorted[mid].durationSeconds
  const longestPauseCall = [...calls].sort((a, b) => b.computed.silenceMaxSeconds - a.computed.silenceMaxSeconds)[0]
  return {
    avg: calls.reduce((sum, call) => sum + call.durationSeconds, 0) / calls.length,
    median,
    longest: sorted[sorted.length - 1],
    shortest: sorted[0],
    silenceAvg: calls.reduce((sum, call) => sum + call.computed.silenceAvgSeconds, 0) / calls.length,
    longestPause: longestPauseCall?.computed.silenceMaxSeconds ?? 0,
    longestPauseCall,
  }
}

export function durationByDayByAgent(calls: MockCall[]): Array<{ day: string; [agentId: string]: string | number }> {
  const days = new Map<string, Map<string, { sum: number; n: number }>>()
  for (const call of calls) {
    const day = toDayStamp(call.startedAt)
    const agents = days.get(day) ?? new Map()
    const row = agents.get(call.agentId) ?? { sum: 0, n: 0 }
    row.sum += call.durationSeconds
    row.n += 1
    agents.set(call.agentId, row)
    days.set(day, agents)
  }
  return [...days.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([day, agents]) => {
      const point: { day: string; [agentId: string]: string | number } = { day }
      for (const [agentId, row] of agents) point[agentId] = row.n ? row.sum / row.n : 0
      return point
    })
}

export function callsByAgent(calls: MockCall[]): Array<{ agentId: string; agentName: string; count: number }> {
  const map = new Map<string, number>()
  for (const call of calls) map.set(call.agentId, (map.get(call.agentId) ?? 0) + 1)
  return MOCK_AGENTS.map((agent) => ({
    agentId: agent.id,
    agentName: agent.name,
    count: map.get(agent.id) ?? 0,
  })).filter((row) => row.count > 0)
}

export function callsOverTimeByAgent(calls: MockCall[]): Array<{ day: string; [agentId: string]: string | number }> {
  const days = new Map<string, Record<string, number>>()
  for (const call of calls) {
    const day = toDayStamp(call.startedAt)
    const row = days.get(day) ?? {}
    row[call.agentId] = (row[call.agentId] ?? 0) + 1
    days.set(day, row)
  }
  return [...days.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([day, counts]) => ({ day, ...counts }))
}

export interface MetricUsageRow {
  id: string
  name: string
  group: 'global' | 'local'
  count: number
}

export function metricUsageRows(calls: MockCall[]): MetricUsageRow[] {
  const local = MOCK_METRICS.map((metric) => ({
    id: metric.id,
    name: metric.name,
    group: 'local' as const,
    count: calls.filter((call) => Boolean(call.metric_scores[metric.id])).length,
  }))
  const global: MetricUsageRow[] = [
    { id: 'avg_duration', name: 'Avg duration', group: 'global', count: calls.length },
    { id: 'closing_quality', name: 'Closing quality', group: 'global', count: calls.length },
    { id: 'early_ending', name: 'Early ending', group: 'global', count: calls.filter((call) => call.endedEarly).length },
    { id: 'silence_duration', name: 'Silence duration', group: 'global', count: calls.length },
    { id: 'tool_call_failures', name: 'Tool call failures', group: 'global', count: calls.filter((call) => call.computed.toolCallFailures > 0).length },
    { id: 'rag_call_failures', name: 'RAG call failures', group: 'global', count: calls.filter((call) => call.computed.ragCallFailures > 0).length },
    { id: 'talk_ratio', name: 'Talk ratio', group: 'global', count: calls.length },
  ]
  return [...global, ...local]
}

export function metricUsageOverTime(
  calls: MockCall[],
  metricIds: string[],
): Array<{ day: string; [metricId: string]: string | number }> {
  const days = new Map<string, Record<string, number>>()
  for (const call of calls) {
    const day = toDayStamp(call.startedAt)
    const row = days.get(day) ?? {}
    for (const id of metricIds) {
      const used = isGlobalMetricId(id) ? true : Boolean(call.metric_scores[id])
      if (used) row[id] = (row[id] ?? 0) + 1
    }
    days.set(day, row)
  }
  return [...days.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([day, counts]) => ({ day, ...counts }))
}

export function scenarioStats(calls: MockCall[]) {
  const byAgent = MOCK_AGENTS.map((agent) => {
    const scoped = calls.filter((call) => call.agentId === agent.id)
    const counts = new Map<string, number>()
    for (const call of scoped) {
      if (!call.scenarioId) continue
      counts.set(call.scenarioId, (counts.get(call.scenarioId) ?? 0) + 1)
    }
    return {
      agentId: agent.id,
      agentName: agent.name,
      total: scoped.filter((call) => call.scenarioId).length,
      byScenario: [...counts.entries()].map(([scenarioId, count]) => ({
        scenarioId,
        name: SCENARIOS.find((scenario) => scenario.id === scenarioId)?.name ?? scenarioId,
        count,
      })),
    }
  })
  const richest = [...SCENARIOS].sort((a, b) => b.metricIds.length - a.metricIds.length)
  const mostFrequent = SCENARIOS.map((scenario) => ({
    ...scenario,
    count: calls.filter((call) => call.scenarioId === scenario.id).length,
  })).sort((a, b) => b.count - a.count)
  const stacked = byAgent.map((row) => {
    const point: Record<string, string | number> = { agent: row.agentName, agentId: row.agentId }
    for (const item of row.byScenario) point[item.name] = item.count
    return point
  })
  return { byAgent, richest, mostFrequent, stacked, total: calls.filter((call) => call.scenarioId).length }
}

export function agentTableRows(calls: MockCall[]) {
  return MOCK_AGENTS.map((agent) => {
    const scoped = calls.filter((call) => call.agentId === agent.id)
    const scenarios = new Set(scoped.map((call) => call.scenarioId).filter(Boolean))
    return {
      agentId: agent.id,
      agentName: agent.name,
      metrics: metricsForAgent(agent.id).length,
      scenarios: Math.max(scenarios.size, SCENARIOS.filter((scenario) => scenario.agentId === agent.id).length),
      calls: scoped.length,
      costUsd: scoped.reduce((sum, call) => sum + call.usage.costUsd, 0),
      tools: toolCallTotal(scoped),
    }
  })
}

export function metricTreeValues(calls: MockCall[]): Record<string, { value: number | null; display: string }> {
  const result: Record<string, { value: number | null; display: string }> = {}
  for (const metric of MOCK_METRICS) {
    const values = calls
      .map((call) => call.metric_scores[metric.id]?.value)
      .map((value) => (typeof value === 'number' ? value : typeof value === 'boolean' ? (value ? 1 : 0) : null))
      .filter((value): value is number => value != null)
    const avg = values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : null
    result[metric.id] = {
      value: avg,
      display: avg == null ? '—' : metric.kind === 'boolean' || metric.kind === 'rating' ? `${Math.round(avg * 100)}%` : avg.toFixed(2),
    }
  }
  const globalIds: GlobalMetricId[] = [
    'avg_duration',
    'closing_quality',
    'early_ending',
    'silence_duration',
    'longest_pause',
    'tool_call_failures',
    'rag_call_failures',
    'talk_ratio',
  ]
  for (const id of globalIds) {
    const def = globalMetricById(id)
    if (!def) continue
    const agg = aggregateCalls(calls, id, def.failRule)
    result[id] = {
      value: agg.avg,
      display:
        id === 'avg_duration' && agg.avg != null
          ? `${Math.round(agg.avg)}s`
          : agg.avg == null
            ? '—'
            : agg.avg.toFixed(2),
    }
  }
  const north = [result['mock-metric-resolution']?.value, result['mock-metric-outcome']?.value].filter(
    (value): value is number => value != null,
  )
  const northAvg = north.length ? north.reduce((sum, value) => sum + value, 0) / north.length : null
  result['north-star'] = {
    value: northAvg,
    display: northAvg == null ? '—' : `${Math.round(northAvg * 100)}%`,
  }
  return result
}

export function agentDashboardStats(calls: MockCall[], agentId: string) {
  const scoped = calls.filter((call) => call.agentId === agentId)
  const metricCounts = metricUsageRows(scoped).filter((row) => row.group === 'local' && row.count > 0)
  const mostUsedMetric = [...metricCounts].sort((a, b) => b.count - a.count)[0] ?? null
  const tools = toolUsageRows(scoped).filter((row) => row.count > 0)
  const scenarios = scenarioStats(scoped)
  const agentScenarios = SCENARIOS.filter((scenario) => scenario.agentId === agentId)
  const scenarioMetricCount = new Set(agentScenarios.flatMap((scenario) => scenario.metricIds)).size
  return {
    calls: scoped,
    callCount: scoped.length,
    usageOverTime: dailySeries(scoped, () => 1),
    metricsAssigned: (AGENT_METRICS[agentId] ?? []).length,
    mostUsedMetric,
    metricCounts,
    tools,
    toolCount: tools.length,
    scenarioCount: agentScenarios.length,
    scenarioMetricCount,
    scenarios,
    costUsd: scoped.reduce((sum, call) => sum + call.usage.costUsd, 0),
  }
}

export { modelsByKind }
