import type {
  CallImportMetricAggregate,
  DashboardOpsCostByAgent,
  EvaluatorResultRow,
  EvaluatorResultsDashboardOpsResponse,
} from '../../../types/api'

export const LAYER_LLM = '#ca8a04'
export const LAYER_STT = '#a16207'
export const LAYER_TTS = '#d6d3d1'
export const SERIES_OTHER = '#9ca3af'
const MODEL_COLORS = [LAYER_LLM, LAYER_STT, '#854d0e', '#eab308', '#fde68a', SERIES_OTHER]

export interface ChartSeries {
  key: string
  color: string
  stack?: string
}

export interface ChartModel {
  headline: string
  caption?: string
  data: Array<Record<string, string | number>>
  series: ChartSeries[]
  horizontal?: boolean
}

type ScoreEntry = {
  value?: unknown
  type?: string
  metric_name?: string
  selection_mode?: string
  chosen_child_name?: string
  selected_child_names?: string[]
  skipped?: boolean
  error?: string
}

export function isCategoricalMetric(metric: CallImportMetricAggregate): boolean {
  return (metric.value_counts?.length ?? 0) > 0 && metric.mean == null
}

export function formatUsd(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return '—'
  return value.toLocaleString(undefined, { style: 'currency', currency: 'USD', maximumFractionDigits: 2 })
}

export function formatDayLabel(isoDay: string): string {
  const [year, month, day] = isoDay.slice(0, 10).split('-').map(Number)
  if (!year || !month || !day) return isoDay
  return new Date(year, month - 1, day).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

function dayParts(iso: string): { day: string; sortKey: string } {
  const sortKey = new Date(iso).toISOString().slice(0, 10)
  return { day: formatDayLabel(sortKey), sortKey }
}

export function extractCategorizationLabels(
  scores: Record<string, ScoreEntry> | null | undefined,
  metricId: string,
  childIdsByParent: Map<string, string[]>,
  childNamesById: Map<string, string>,
): string[] {
  if (!scores) return []
  const entry = scores[metricId]
  if (entry && !entry.skipped && !entry.error) {
    if (entry.selection_mode === 'multi_label' && Array.isArray(entry.selected_child_names)) {
      return entry.selected_child_names.map((label) => String(label).trim()).filter(Boolean)
    }
    const chosen = entry.chosen_child_name ?? entry.value
    if (chosen != null && String(chosen).trim()) return [String(chosen).trim()]
  }
  const labels: string[] = []
  for (const childId of childIdsByParent.get(metricId) ?? []) {
    const child = scores[childId]
    if (!child || child.skipped || child.error) continue
    if (child.value === true || child.value === 'true' || child.value === 1 || child.value === '1') {
      labels.push(childNamesById.get(childId) ?? child.metric_name ?? childId)
    }
  }
  return labels
}

export function buildCategorySeries(
  results: EvaluatorResultRow[],
  metrics: CallImportMetricAggregate[],
  childIdsByParent: Map<string, string[]>,
  childNamesById: Map<string, string>,
): Map<string, { labels: string[]; data: Array<Record<string, string | number>> }> {
  const series = new Map<string, { labels: string[]; data: Array<Record<string, string | number>> }>()
  const completed = results.filter((row) => row.status === 'completed' && row.metric_scores)
  for (const metric of metrics.filter(isCategoricalMetric)) {
    const labelSet = new Set(metric.value_counts.map((count) => count.label))
    const dayMap = new Map<string, { day: string; sortKey: string; counts: Record<string, number> }>()
    for (const row of completed) {
      const labels = extractCategorizationLabels(
        row.metric_scores as Record<string, ScoreEntry> | null,
        metric.metric_id,
        childIdsByParent,
        childNamesById,
      )
      if (!labels.length) continue
      const { day, sortKey } = dayParts(row.timestamp)
      const bucket = dayMap.get(sortKey) ?? { day, sortKey, counts: {} }
      for (const label of labels) {
        labelSet.add(label)
        bucket.counts[label] = (bucket.counts[label] ?? 0) + 1
      }
      dayMap.set(sortKey, bucket)
    }
    const labels = Array.from(labelSet)
    const data = Array.from(dayMap.values())
      .sort((a, b) => a.sortKey.localeCompare(b.sortKey))
      .map(({ day, counts }) => {
        const point: Record<string, string | number> = { day }
        for (const label of labels) point[label] = counts[label] ?? 0
        return point
      })
    if (data.length && labels.length) series.set(metric.metric_id, { labels, data })
  }
  return series
}

function layerSeries(): ChartSeries[] {
  return [
    { key: 'llm', color: LAYER_LLM, stack: 'cost' },
    { key: 'stt', color: LAYER_STT, stack: 'cost' },
    { key: 'tts', color: LAYER_TTS, stack: 'cost' },
  ]
}

function sumLayers(rows: Array<{ llm_usd: number; stt_usd: number; tts_usd: number }>): number {
  return rows.reduce((sum, row) => sum + row.llm_usd + row.stt_usd + row.tts_usd, 0)
}

export function agentCostCard(ops: EvaluatorResultsDashboardOpsResponse | undefined, display: string): ChartModel {
  const agents = [...(ops?.cost_by_agent ?? [])].sort((a, b) => b.total_usd - a.total_usd)
  const total = agents.reduce((sum, agent) => sum + agent.total_usd, 0)
  if (display === 'bar') {
    return {
      headline: formatUsd(total),
      caption: 'Top agents by layer',
      data: agents.slice(0, 6).map((agent) => ({
        name: agent.agent_name,
        llm: agent.llm_usd,
        stt: agent.stt_usd,
        tts: agent.tts_usd,
      })),
      series: layerSeries(),
    }
  }
  const byDay = new Map<string, { llm: number; stt: number; tts: number }>()
  for (const row of ops?.cost_by_agent_day ?? []) {
    const bucket = byDay.get(row.day) ?? { llm: 0, stt: 0, tts: 0 }
    bucket.llm += row.llm_usd
    bucket.stt += row.stt_usd
    bucket.tts += row.tts_usd
    byDay.set(row.day, bucket)
  }
  return {
    headline: formatUsd(total),
    caption: 'Daily cost by layer',
    data: Array.from(byDay.entries())
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([day, layers]) => ({ day: formatDayLabel(day), llm: layers.llm, stt: layers.stt, tts: layers.tts })),
    series: layerSeries(),
  }
}

export function agentCostDetail(
  ops: EvaluatorResultsDashboardOpsResponse | undefined,
  role: string | null,
  focusAgentId: string | null,
): ChartModel {
  const rows = (ops?.cost_by_agent_day ?? []).filter((row) => {
    if (focusAgentId && row.agent_id !== focusAgentId) return false
    if (role && row.role !== role) return false
    return true
  })
  const agent = ops?.cost_by_agent.find((item) => item.agent_id === focusAgentId)
  const byDay = new Map<string, { llm: number; stt: number; tts: number }>()
  for (const row of rows) {
    const bucket = byDay.get(row.day) ?? { llm: 0, stt: 0, tts: 0 }
    bucket.llm += row.llm_usd
    bucket.stt += row.stt_usd
    bucket.tts += row.tts_usd
    byDay.set(row.day, bucket)
  }
  return {
    headline: formatUsd(sumLayers(rows)),
    caption: agent ? `${agent.agent_name} daily cost` : 'Daily cost by layer',
    data: Array.from(byDay.entries())
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([day, layers]) => ({ day: formatDayLabel(day), llm: layers.llm, stt: layers.stt, tts: layers.tts })),
    series: layerSeries(),
  }
}

export function modelsForAgent(
  agent: DashboardOpsCostByAgent | undefined,
  role: string | null,
): Array<{ model: string; cost_usd: number }> {
  if (!agent) return []
  const totals = new Map<string, number>()
  for (const spend of agent.models) {
    if (role && spend.role !== role) continue
    totals.set(spend.model, (totals.get(spend.model) ?? 0) + spend.cost_usd)
  }
  return Array.from(totals.entries())
    .map(([model, cost_usd]) => ({ model, cost_usd }))
    .sort((a, b) => b.cost_usd - a.cost_usd)
}

function modelPalette(keys: string[]): ChartSeries[] {
  return keys.map((key, index) => ({
    key,
    color: key === 'Other' ? SERIES_OTHER : MODEL_COLORS[index % MODEL_COLORS.length],
    stack: 'cost',
  }))
}

export function pivotModelDays(
  rows: Array<{ day: string; model: string; cost_usd: number }>,
  focusModel: string | null,
): { keys: string[]; data: Array<Record<string, string | number>>; total: number; topModel: string | null } {
  const scoped = focusModel ? rows.filter((row) => row.model === focusModel) : rows
  const totals = new Map<string, number>()
  for (const row of scoped) totals.set(row.model, (totals.get(row.model) ?? 0) + row.cost_usd)
  const ranked = Array.from(totals.entries()).sort((a, b) => b[1] - a[1])
  const top = focusModel ? ranked.map(([model]) => model) : ranked.slice(0, 5).map(([model]) => model)
  const topSet = new Set(top)
  const includeOther = !focusModel && ranked.length > top.length
  const byDay = new Map<string, Record<string, number>>()
  for (const row of scoped) {
    const key = topSet.has(row.model) ? row.model : 'Other'
    const bucket = byDay.get(row.day) ?? {}
    bucket[key] = (bucket[key] ?? 0) + row.cost_usd
    byDay.set(row.day, bucket)
  }
  const keys = includeOther ? [...top, 'Other'] : top
  const data = Array.from(byDay.entries())
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([day, values]) => ({ day: formatDayLabel(day), ...values }))
  const total = scoped.reduce((sum, row) => sum + row.cost_usd, 0)
  return { keys, data, total, topModel: ranked[0]?.[0] ?? null }
}

export function modelCostCard(ops: EvaluatorResultsDashboardOpsResponse | undefined): ChartModel {
  const pivot = pivotModelDays(ops?.cost_by_model_day ?? [], null)
  return {
    headline: formatUsd(pivot.total),
    caption: pivot.topModel ? `Top model ${pivot.topModel}` : 'Most expensive models',
    data: pivot.data,
    series: modelPalette(pivot.keys),
  }
}

export function modelCostDetail(
  ops: EvaluatorResultsDashboardOpsResponse | undefined,
  focusModel: string | null,
): ChartModel {
  const pivot = pivotModelDays(ops?.cost_by_model_day ?? [], focusModel)
  return {
    headline: formatUsd(pivot.total),
    caption: focusModel ?? 'Daily model cost',
    data: pivot.data,
    series: modelPalette(pivot.keys),
  }
}

function topAgentIds(rows: Array<{ agent_id: string; calls: number }>, limit = 5): string[] {
  const totals = new Map<string, number>()
  for (const row of rows) totals.set(row.agent_id, (totals.get(row.agent_id) ?? 0) + row.calls)
  return Array.from(totals.entries())
    .sort((a, b) => b[1] - a[1])
    .slice(0, limit)
    .map(([id]) => id)
}

export function toolCallCard(ops: EvaluatorResultsDashboardOpsResponse | undefined, display: string): ChartModel {
  const rows = ops?.tool_calls_by_agent_day ?? []
  const total = rows.reduce((sum, row) => sum + row.calls, 0)
  const names = new Map(rows.map((row) => [row.agent_id, row.agent_name]))
  if (display === 'bar') {
    const totals = new Map<string, number>()
    for (const row of rows) totals.set(row.agent_name, (totals.get(row.agent_name) ?? 0) + row.calls)
    return {
      headline: total.toLocaleString(),
      caption: 'Production tool calls',
      data: Array.from(totals.entries())
        .sort((a, b) => b[1] - a[1])
        .slice(0, 6)
        .map(([name, calls]) => ({ name, calls })),
      series: [{ key: 'calls', color: LAYER_LLM }],
      horizontal: true,
    }
  }
  const leaders = new Set(topAgentIds(rows))
  const byDay = new Map<string, Record<string, number>>()
  for (const row of rows) {
    if (!leaders.has(row.agent_id)) continue
    const bucket = byDay.get(row.day) ?? {}
    const name = names.get(row.agent_id) || row.agent_name
    bucket[name] = (bucket[name] ?? 0) + row.calls
    byDay.set(row.day, bucket)
  }
  const keys = topAgentIds(rows).map((id) => names.get(id) || id)
  return {
    headline: total.toLocaleString(),
    caption: 'Agents over time',
    data: Array.from(byDay.entries())
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([day, values]) => ({ day: formatDayLabel(day), ...values })),
    series: keys.map((key, index) => ({ key, color: MODEL_COLORS[index % MODEL_COLORS.length] })),
  }
}

export function toolCallDetail(
  ops: EvaluatorResultsDashboardOpsResponse | undefined,
  mode: 'calls' | 'errors',
  focusAgentId: string | null,
): ChartModel {
  if (focusAgentId) {
    const tools = (ops?.tool_calls_by_tool ?? []).filter((row) => row.agent_id === focusAgentId)
    const agentName = tools[0]?.agent_name ?? ops?.tool_calls_by_agent_day.find((row) => row.agent_id === focusAgentId)?.agent_name
    const key = mode === 'errors' ? 'errors' : 'calls'
    const total = tools.reduce((sum, row) => sum + row[key], 0)
    return {
      headline: total.toLocaleString(),
      caption: agentName ? `${agentName} by tool` : 'Calls by tool',
      data: tools.map((row) => ({ name: row.tool, calls: row.calls, errors: row.errors })),
      series: [{ key, color: mode === 'errors' ? '#dc2626' : LAYER_LLM }],
      horizontal: true,
    }
  }
  const rows = ops?.tool_calls_by_agent_day ?? []
  const names = new Map(rows.map((row) => [row.agent_id, row.agent_name]))
  const leaders = new Set(topAgentIds(rows))
  const byDay = new Map<string, Record<string, number>>()
  for (const row of rows) {
    if (!leaders.has(row.agent_id)) continue
    const bucket = byDay.get(row.day) ?? {}
    const name = names.get(row.agent_id) || row.agent_name
    bucket[name] = (bucket[name] ?? 0) + (mode === 'errors' ? row.errors : row.calls)
    byDay.set(row.day, bucket)
  }
  const keys = topAgentIds(rows).map((id) => names.get(id) || id)
  const total = rows.reduce((sum, row) => sum + (mode === 'errors' ? row.errors : row.calls), 0)
  return {
    headline: total.toLocaleString(),
    caption: mode === 'errors' ? 'Tool errors over time' : 'Tool calls over time',
    data: Array.from(byDay.entries())
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([day, values]) => ({ day: formatDayLabel(day), ...values })),
    series: keys.map((key, index) => ({
      key,
      color: mode === 'errors' ? '#dc2626' : MODEL_COLORS[index % MODEL_COLORS.length],
    })),
  }
}

export function modelTotals(ops: EvaluatorResultsDashboardOpsResponse | undefined): Array<{ model: string; cost_usd: number }> {
  const totals = new Map<string, number>()
  for (const row of ops?.cost_by_model_day ?? []) {
    totals.set(row.model, (totals.get(row.model) ?? 0) + row.cost_usd)
  }
  return Array.from(totals.entries())
    .map(([model, cost_usd]) => ({ model, cost_usd }))
    .sort((a, b) => b.cost_usd - a.cost_usd)
}

export function toolAgentTotals(ops: EvaluatorResultsDashboardOpsResponse | undefined): Array<{ agent_id: string; agent_name: string; calls: number }> {
  const totals = new Map<string, { agent_name: string; calls: number }>()
  for (const row of ops?.tool_calls_by_agent_day ?? []) {
    const current = totals.get(row.agent_id) ?? { agent_name: row.agent_name, calls: 0 }
    current.calls += row.calls
    totals.set(row.agent_id, current)
  }
  return Array.from(totals.entries())
    .map(([agent_id, value]) => ({ agent_id, agent_name: value.agent_name, calls: value.calls }))
    .sort((a, b) => b.calls - a.calls)
}

export function shareSeries(data: Array<Record<string, string | number>>, labels: string[]): Array<Record<string, string | number>> {
  return data.map((point) => {
    const total = labels.reduce((sum, label) => sum + (Number(point[label]) || 0), 0)
    const next: Record<string, string | number> = { day: point.day }
    for (const label of labels) {
      const count = Number(point[label]) || 0
      next[label] = total ? Math.round((count / total) * 100) : 0
    }
    return next
  })
}

export function categoryColors(labels: string[]): ChartSeries[] {
  return labels.map((label, index) => ({
    key: label,
    color: MODEL_COLORS[index % MODEL_COLORS.length],
    stack: 'labels',
  }))
}
