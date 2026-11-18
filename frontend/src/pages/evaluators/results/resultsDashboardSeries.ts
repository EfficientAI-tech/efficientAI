import type {
  CallImportMetricAggregate,
  DashboardOpsCostByAgent,
  EvaluatorResultRow,
  EvaluatorResultsDashboardOpsResponse,
} from '../../../types/api'
import { formatChartDayLabel, resultLocalDayKey } from './resultsDateRange'
import { formatUsageCostUsd, getUsageDisplayCurrency, type UsageDisplayCurrency } from '../../../lib/usageCurrency'

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
  stacked?: boolean
}

const AGENT_BAR_COLORS = ['#2563eb', '#0d9488', '#f97316', '#7c3aed', '#ca8a04']

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

export function roundCost(value: number): number {
  return Math.round(value * 10000) / 10000
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
  const sortKey = resultLocalDayKey(iso)
  return { day: formatChartDayLabel(sortKey), sortKey }
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
      .map(({ day, sortKey, counts }) => {
        const point: Record<string, string | number> = { day, sortKey }
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

function topAgentIds(
  rows: Array<{ agent_id: string; calls: number; errors?: number }>,
  limit = 5,
  mode: 'calls' | 'errors' = 'calls',
): string[] {
  const totals = new Map<string, number>()
  for (const row of rows) {
    const value = mode === 'errors' ? (row.errors ?? 0) : row.calls
    totals.set(row.agent_id, (totals.get(row.agent_id) ?? 0) + value)
  }
  return Array.from(totals.entries())
    .filter(([, value]) => value > 0)
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
  const leaders = new Set(topAgentIds(rows, 5, mode))
  const byDay = new Map<string, Record<string, number>>()
  for (const row of rows) {
    if (!leaders.has(row.agent_id)) continue
    const bucket = byDay.get(row.day) ?? {}
    const name = names.get(row.agent_id) || row.agent_name
    bucket[name] = (bucket[name] ?? 0) + (mode === 'errors' ? row.errors : row.calls)
    byDay.set(row.day, bucket)
  }
  const keys = topAgentIds(rows, 5, mode).map((id) => names.get(id) || id)
  const total = rows.reduce((sum, row) => sum + (mode === 'errors' ? row.errors : row.calls), 0)
  return {
    headline: total.toLocaleString(),
    caption: mode === 'errors' ? 'Tool failures over time' : 'Tool calls over time',
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

export function toolAgentTotals(
  ops: EvaluatorResultsDashboardOpsResponse | undefined,
  mode: 'calls' | 'errors' = 'calls',
): Array<{ agent_id: string; agent_name: string; calls: number; errors: number }> {
  const totals = new Map<string, { agent_name: string; calls: number; errors: number }>()
  for (const row of ops?.tool_calls_by_agent_day ?? []) {
    const current = totals.get(row.agent_id) ?? { agent_name: row.agent_name, calls: 0, errors: 0 }
    current.calls += row.calls
    current.errors += row.errors
    totals.set(row.agent_id, current)
  }
  const pick = mode === 'errors' ? (value: { errors: number }) => value.errors : (value: { calls: number }) => value.calls
  return Array.from(totals.entries())
    .map(([agent_id, value]) => ({ agent_id, agent_name: value.agent_name, calls: value.calls, errors: value.errors }))
    .filter((row) => pick(row) > 0)
    .sort((a, b) => pick(b) - pick(a))
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

const LAYER_ORDER = ['llm', 'stt', 'tts', 's2s']

export function usageCard(
  ops: EvaluatorResultsDashboardOpsResponse | undefined,
  options?: { currency?: UsageDisplayCurrency; inrRate?: number },
): ChartModel {
  const totals = new Map<string, number>()
  for (const row of ops?.model_layers ?? []) {
    totals.set(row.usage_kind, (totals.get(row.usage_kind) ?? 0) + row.cost_usd)
  }
  const total = Array.from(totals.values()).reduce((sum, value) => sum + value, 0)
  const currency = options?.currency ?? getUsageDisplayCurrency()
  const inrRate = options?.inrRate ?? 95
  return {
    headline: formatUsageCostUsd(total, currency, inrRate),
    caption: 'Spend by layer',
    data: LAYER_ORDER.filter((kind) => totals.has(kind)).map((kind) => ({
      name: kind.toUpperCase(),
      cost: totals.get(kind) ?? 0,
    })),
    series: [{ key: 'cost', color: LAYER_LLM }],
    horizontal: true,
  }
}

export function usageHasS2S(ops: EvaluatorResultsDashboardOpsResponse | undefined): boolean {
  return (ops?.model_layers ?? []).some((row) => row.usage_kind === 's2s')
}

export function usageFacts(ops: EvaluatorResultsDashboardOpsResponse | undefined): { most: string; least: string; highest: string } {
  const totals = new Map<string, number>()
  for (const row of ops?.model_layers ?? []) {
    if (row.cost_usd <= 0) continue
    totals.set(row.model, (totals.get(row.model) ?? 0) + row.cost_usd)
  }
  const ranked = Array.from(totals.entries()).sort((a, b) => b[1] - a[1])
  return {
    most: ranked[0]?.[0] ?? '—',
    least: ranked[ranked.length - 1]?.[0] ?? '—',
    highest: ranked[0] ? formatUsd(ranked[0][1]) : '—',
  }
}

export function usageDetail(
  ops: EvaluatorResultsDashboardOpsResponse | undefined,
  view: string,
  focus: string | null,
): ChartModel {
  const layers = ops?.model_layers ?? []
  if (view === 'price_minute' || view === 'price_million') {
    const rateKey = view === 'price_minute' ? 'usd_per_minute' : 'usd_per_million_tokens'
    const priced = new Set(
      layers.filter((row) => (row[rateKey] ?? 0) > 0).map((row) => row.model),
    )
    const history = (ops?.cost_by_model_day ?? []).filter((row) => priced.has(row.model) && (!focus || row.model === focus))
    const models = Array.from(new Set(history.map((row) => row.model)))
    const byDay = new Map<string, Record<string, number>>()
    for (const row of history) {
      const bucket = byDay.get(row.day) ?? {}
      bucket[row.model] = roundCost((bucket[row.model] ?? 0) + row.cost_usd)
      byDay.set(row.day, bucket)
    }
    const spent = history.reduce((sum, row) => sum + row.cost_usd, 0)
    return {
      headline: formatUsd(spent),
      caption: view === 'price_minute' ? 'Daily spend, priced per minute' : 'Daily spend, priced per 1M tokens',
      data: Array.from(byDay.entries()).sort(([a], [b]) => a.localeCompare(b)).map(([day, values]) => ({
        day: formatDayLabel(day),
        ...values,
      })),
      series: models.map((model, index) => ({ key: model, color: AGENT_BAR_COLORS[index % AGENT_BAR_COLORS.length] })),
    }
  }
  const models = layers.filter((row) => row.usage_kind === view && row.cost_usd > 0 && (!focus || row.model === focus))
  const agents = ops?.cost_by_agent ?? []
  const data = models.map((model) => {
    const point: Record<string, string | number> = { name: model.model }
    for (const agent of agents) {
      point[agent.agent_name] = roundCost(agent.models
        .filter((spend) => spend.model === model.model)
        .reduce((sum, spend) => sum + spend.cost_usd, 0))
    }
    return point
  })
  const stacked = data.reduce((sum, point) => (
    sum + agents.reduce((agentSum, agent) => agentSum + (Number(point[agent.agent_name]) || 0), 0)
  ), 0)
  const layerTotal = models.reduce((sum, row) => sum + row.cost_usd, 0)
  const total = stacked > 0 ? stacked : layerTotal
  return {
    headline: formatUsd(total),
    caption: `${view.toUpperCase()} models`,
    data,
    series: agents.map((agent, index) => ({
      key: agent.agent_name,
      color: AGENT_BAR_COLORS[index % AGENT_BAR_COLORS.length],
      stack: 'agents',
    })),
    stacked: true,
  }
}

export function toolsCard(ops: EvaluatorResultsDashboardOpsResponse | undefined): ChartModel {
  const providers = ops?.providers ?? []
  return {
    headline: providers.length.toLocaleString(),
    caption: 'Products in use',
    data: providers.slice(0, 6).map((row) => ({ name: row.provider, calls: row.calls })),
    series: [{ key: 'calls', color: LAYER_LLM }],
    horizontal: true,
  }
}

export function toolFacts(ops: EvaluatorResultsDashboardOpsResponse | undefined): { most: string; least: string; empty: string } {
  const providers = ops?.providers ?? []
  return {
    most: providers[0]?.provider ?? '—',
    least: providers[providers.length - 1]?.provider ?? '—',
    empty: (ops?.calls_with_no_tools ?? 0).toLocaleString(),
  }
}

export type ToolInsightMode = 'calls' | 'errors'

function resolveToolAgentFocusId(
  ops: EvaluatorResultsDashboardOpsResponse | undefined,
  focus: string | null,
): string | null {
  if (!focus) return null
  const row = ops?.tool_calls_by_agent_day.find(
    (item) => item.agent_id === focus || item.agent_name === focus,
  )
  return row?.agent_id ?? null
}

export function toolErrorsByUseCase(
  ops: EvaluatorResultsDashboardOpsResponse | undefined,
  focus: string | null,
): ChartModel {
  const totals = new Map<string, number>()
  for (const row of ops?.tool_calls_by_tool ?? []) {
    if (focus && row.tool !== focus && row.agent_id !== focus && row.agent_name !== focus) continue
    totals.set(row.tool, (totals.get(row.tool) ?? 0) + row.errors)
  }
  const ranked = Array.from(totals.entries()).sort((a, b) => b[1] - a[1])
  const total = ranked.reduce((sum, item) => sum + item[1], 0)
  return {
    headline: total.toLocaleString(),
    caption: 'Tool failures by use case',
    data: ranked.map(([name, errors]) => ({ name, errors })),
    series: [{ key: 'errors', color: '#dc2626' }],
    horizontal: true,
  }
}

export function platformToolDetail(
  ops: EvaluatorResultsDashboardOpsResponse | undefined,
  view: string,
  focus: string | null,
  mode: ToolInsightMode = 'calls',
): ChartModel {
  if (view === 'per_call') {
    const rows = (ops?.tool_calls_per_run ?? []).filter((row) => !focus || row.agent_id === focus || row.agent_name === focus)
    const avg = rows.length ? rows.reduce((sum, row) => sum + row.avg_per_run, 0) / rows.length : 0
    return {
      headline: avg.toLocaleString(undefined, { maximumFractionDigits: 2 }),
      caption: 'Use cases per call by agent',
      data: rows.map((row) => ({ name: row.agent_name, avg: row.avg_per_run })),
      series: [{ key: 'avg', color: LAYER_LLM }],
      horizontal: true,
    }
  }
  if (view === 'use_cases') {
    if (mode === 'errors') return toolErrorsByUseCase(ops, focus)
    const totals = new Map<string, number>()
    for (const row of ops?.tool_calls_by_tool ?? []) {
      if (focus && row.tool !== focus && row.agent_id !== focus && row.agent_name !== focus) continue
      totals.set(row.tool, (totals.get(row.tool) ?? 0) + row.calls)
    }
    const ranked = Array.from(totals.entries()).sort((a, b) => b[1] - a[1])
    return {
      headline: ranked.reduce((sum, item) => sum + item[1], 0).toLocaleString(),
      caption: 'Use cases',
      data: ranked.map(([name, calls]) => ({ name, calls })),
      series: [{ key: 'calls', color: LAYER_LLM }],
      horizontal: true,
    }
  }
  const rows = (ops?.tool_calls_by_agent_day ?? []).filter((row) => !focus || row.agent_id === focus || row.agent_name === focus)
  const byDay = new Map<string, Record<string, number>>()
  const keys = new Set<string>()
  const metricKey = mode === 'errors' ? 'errors' : 'calls'
  for (const row of rows) {
    const bucket = byDay.get(row.day) ?? {}
    bucket[row.agent_name] = (bucket[row.agent_name] ?? 0) + row[metricKey]
    byDay.set(row.day, bucket)
    keys.add(row.agent_name)
  }
  const seriesKeys = Array.from(keys)
  return {
    headline: rows.reduce((sum, row) => sum + row[metricKey], 0).toLocaleString(),
    caption: mode === 'errors' ? 'Tool failures over time by agent' : 'Usage over time by agent',
    data: Array.from(byDay.entries()).sort(([a], [b]) => a.localeCompare(b)).map(([day, values]) => ({
      day: formatDayLabel(day),
      ...values,
    })),
    series: seriesKeys.map((key, index) => ({ key, color: MODEL_COLORS[index % MODEL_COLORS.length] })),
  }
}

export function toolsDetail(
  ops: EvaluatorResultsDashboardOpsResponse | undefined,
  view: string,
  focus: string | null,
  mode: ToolInsightMode = 'calls',
): ChartModel {
  if (mode === 'errors' && view === 'share') return toolErrorsByUseCase(ops, focus)
  if (view === 'over_time') {
    const rows = (ops?.provider_by_day ?? []).filter((row) => !focus || row.provider === focus)
    const byDay = new Map<string, Record<string, number>>()
    const keys = new Set<string>()
    for (const row of rows) {
      const bucket = byDay.get(row.day) ?? {}
      bucket[row.provider] = (bucket[row.provider] ?? 0) + row.calls
      byDay.set(row.day, bucket)
      keys.add(row.provider)
    }
    const seriesKeys = Array.from(keys)
    return {
      headline: rows.reduce((sum, row) => sum + row.calls, 0).toLocaleString(),
      caption: 'Usage over time',
      data: Array.from(byDay.entries()).sort(([a], [b]) => a.localeCompare(b)).map(([day, values]) => ({
        day: formatDayLabel(day),
        ...values,
      })),
      series: seriesKeys.map((key, index) => ({ key, color: MODEL_COLORS[index % MODEL_COLORS.length] })),
    }
  }
  if (view === 'by_agent') {
    if (mode === 'errors') {
      const ranked = toolAgentTotals(ops, 'errors')
      return {
        headline: ranked.reduce((sum, row) => sum + row.errors, 0).toLocaleString(),
        caption: 'Tool failures by agent',
        data: ranked.map((row) => ({ name: row.agent_name, errors: row.errors })),
        series: [{ key: 'errors', color: '#dc2626' }],
        horizontal: true,
      }
    }
    const rows = (ops?.provider_by_agent ?? []).filter((row) => !focus || row.provider === focus || row.agent_name === focus || row.agent_id === focus)
    const byAgent = new Map<string, Record<string, number>>()
    const keys = new Set<string>()
    for (const row of rows) {
      const bucket = byAgent.get(row.agent_name) ?? {}
      bucket[row.provider] = (bucket[row.provider] ?? 0) + row.calls
      byAgent.set(row.agent_name, bucket)
      keys.add(row.provider)
    }
    const seriesKeys = Array.from(keys)
    return {
      headline: rows.reduce((sum, row) => sum + row.calls, 0).toLocaleString(),
      caption: 'By agent',
      data: Array.from(byAgent.entries()).map(([name, values]) => ({ name, ...values })),
      series: seriesKeys.map((key, index) => ({ key, color: MODEL_COLORS[index % MODEL_COLORS.length], stack: 'tools' })),
    }
  }
  const providers = (ops?.providers ?? []).filter((row) => !focus || row.provider === focus)
  return {
    headline: providers.reduce((sum, row) => sum + row.calls, 0).toLocaleString(),
    caption: 'Share of tool traffic',
    data: providers.map((row) => ({ name: row.provider, calls: row.calls })),
    series: [{ key: 'calls', color: LAYER_LLM }],
    horizontal: true,
  }
}

export function scenarioStack(
  rows: Array<{ agentName: string; scenarioName: string; count: number }>,
): ChartModel {
  const scenarioTotals = new Map<string, number>()
  for (const row of rows) scenarioTotals.set(row.scenarioName, (scenarioTotals.get(row.scenarioName) ?? 0) + row.count)
  const top = Array.from(scenarioTotals.entries()).sort((a, b) => b[1] - a[1]).slice(0, 4).map(([name]) => name)
  const topSet = new Set(top)
  const byAgent = new Map<string, Record<string, number>>()
  for (const row of rows) {
    const key = topSet.has(row.scenarioName) ? row.scenarioName : 'Other'
    const bucket = byAgent.get(row.agentName) ?? {}
    bucket[key] = (bucket[key] ?? 0) + row.count
    byAgent.set(row.agentName, bucket)
  }
  const keys = scenarioTotals.size > top.length ? [...top, 'Other'] : top
  const total = rows.reduce((sum, row) => sum + row.count, 0)
  return {
    headline: total.toLocaleString(),
    caption: 'Scenario runs by agent',
    data: Array.from(byAgent.entries()).map(([name, values]) => ({ name, ...values })),
    series: keys.map((key, index) => ({
      key,
      color: key === 'Other' ? SERIES_OTHER : MODEL_COLORS[index % MODEL_COLORS.length],
      stack: 'scenarios',
    })),
  }
}

export function formatDuration(seconds: number | null): string {
  if (seconds == null || Number.isNaN(seconds)) return '—'
  const whole = Math.round(seconds)
  const minutes = Math.floor(whole / 60)
  const remain = whole % 60
  if (minutes <= 0) return `${remain}s`
  return `${minutes}m ${remain.toString().padStart(2, '0')}s`
}

export function totalCallsByAgentCard(
  agentRows: Array<{ name: string; total: number }>,
  aggregateTotal: number,
): ChartModel {
  return {
    headline: formatHeadlineNumber(aggregateTotal),
    caption: 'Calls by agent',
    data: agentRows.slice(0, 8).map((row) => ({ name: row.name, total: row.total })),
    series: [{ key: 'total', color: LAYER_LLM }],
    horizontal: true,
  }
}

export function metricUsageAgentsCard(
  agentRows: Array<{ name: string; total: number }>,
): ChartModel {
  const top = agentRows.slice(0, 6)
  return {
    headline: top.length.toLocaleString(),
    caption: 'Agents with runs',
    data: top.map((row) => ({ name: row.name, total: row.total })),
    series: [{ key: 'total', color: LAYER_LLM }],
    horizontal: true,
  }
}

/** Counts and whole numbers — no trailing decimals. */
function formatHeadlineNumber(value: number): string {
  if (!value) return '—'
  return value.toLocaleString()
}

/** Scores, means, and other floats — drop IEEE noise; at most 4 decimal places. */
export function formatChartNumber(value: number | string | null | undefined): string {
  if (value == null || value === '') return '—'
  const num = typeof value === 'number' ? value : Number(value)
  if (!Number.isFinite(num)) return String(value)
  if (Math.abs(num - Math.round(num)) < 1e-9) {
    return Math.round(num).toLocaleString()
  }
  const rounded = Math.round(num * 10_000) / 10_000
  return rounded.toLocaleString(undefined, { maximumFractionDigits: 4, minimumFractionDigits: 0 })
}

export function mergedToolsCard(ops: EvaluatorResultsDashboardOpsResponse | undefined): ChartModel {
  const calls = (ops?.tool_calls_by_agent_day ?? []).reduce((sum, row) => sum + row.calls, 0)
  const products = ops?.providers?.length ?? 0
  return {
    headline: calls.toLocaleString(),
    caption: `${products} product${products === 1 ? '' : 's'} · calls and tool use in pre-prod runs`,
    data: (ops?.providers ?? []).slice(0, 5).map((row) => ({ name: row.provider, calls: row.calls })),
    series: [{ key: 'calls', color: LAYER_LLM }],
    horizontal: true,
  }
}

export const MERGED_TOOLS_VIEWS = [
  { id: 'over_time', label: 'Over time' },
  { id: 'per_call', label: 'Per call' },
  { id: 'use_cases', label: 'Use cases' },
  { id: 'share', label: 'Share' },
  { id: 'by_agent', label: 'By agent' },
] as const

export type MergedToolsViewId = (typeof MERGED_TOOLS_VIEWS)[number]['id']

export function mergedToolsDetail(
  ops: EvaluatorResultsDashboardOpsResponse | undefined,
  view: MergedToolsViewId,
  focus: string | null,
  mode: ToolInsightMode = 'calls',
): ChartModel {
  if (mode === 'errors') {
    if (view === 'per_call') {
      return {
        headline: '—',
        caption: 'Per-call averages are call-volume only · switch to Calls',
        data: [],
        series: [],
      }
    }
    if (view === 'use_cases' || view === 'share') {
      return view === 'use_cases'
        ? platformToolDetail(ops, 'use_cases', focus, mode)
        : toolErrorsByUseCase(ops, focus)
    }
    const agentId = resolveToolAgentFocusId(ops, focus)
    if (view === 'over_time' || view === 'by_agent') {
      return toolCallDetail(ops, 'errors', agentId)
    }
  }
  if (view === 'per_call') return platformToolDetail(ops, 'per_call', focus, mode)
  if (view === 'use_cases') return platformToolDetail(ops, 'use_cases', focus, mode)
  if (view === 'over_time') {
    const agentSeries = platformToolDetail(ops, 'over_time', focus, mode)
    if (agentSeries.data.length) return agentSeries
    return toolsDetail(ops, 'over_time', focus, mode)
  }
  if (view === 'share') return toolsDetail(ops, 'share', focus, mode)
  if (view === 'by_agent') return toolsDetail(ops, 'by_agent', focus, mode)
  return platformToolDetail(ops, 'over_time', focus, mode)
}

export function totalToolErrors(ops: EvaluatorResultsDashboardOpsResponse | undefined): number {
  return (ops?.tool_calls_by_agent_day ?? []).reduce((sum, row) => sum + row.errors, 0)
}

/** Daily mean scores for the metric using score_days already scoped to the dashboard date filter. */
export function scoreTrendForWindow(
  scoreDays: EvaluatorResultsDashboardOpsResponse['score_days'],
  metricId: string,
  dateRange: { start: string; end: string } | null,
): { points: Array<{ day: string; value: number }>; note: string } {
  const rows = (scoreDays ?? [])
    .filter((row) => row.metric_id === metricId && row.score_count > 0)
    .sort((a, b) => a.day.localeCompare(b.day))
  const note = dateRange
    ? `Daily mean · ${dateRange.start} → ${dateRange.end}`
    : rows.length === 1
      ? `Daily mean · ${rows[0].day}`
      : 'Daily mean · all time'
  return {
    note,
    points: rows.map((row) => ({
      day: formatDayLabel(row.day),
      value: Number((row.score_sum / row.score_count).toFixed(2)),
    })),
  }
}

/** @deprecated use scoreTrendForWindow */
export const last7DayScoreTrend = scoreTrendForWindow
