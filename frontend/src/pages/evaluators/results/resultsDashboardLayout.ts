export type ResultsChartType = 'line' | 'bar' | 'area'

export type ResultsWidgetType =
  | 'agent_cost'
  | 'model_cost'
  | 'tool_calls'
  | 'volume'
  | 'completion'
  | 'avg_score'
  | 'lowest_metrics'
  | 'agents'
  | 'scenarios'
  | 'metric_trend'

export interface ResultsWidget {
  id: string
  type: ResultsWidgetType
  display: ResultsChartType
  hidden?: boolean
  metricId?: string | null
}

export const MAX_VISIBLE_WIDGETS = 6

export const WIDGET_LABELS: Record<ResultsWidgetType, string> = {
  agent_cost: 'Agent cost',
  model_cost: 'Model cost',
  tool_calls: 'Tool calls',
  volume: 'Run volume',
  completion: 'Completion rate',
  avg_score: 'Average score',
  lowest_metrics: 'Lowest scores',
  agents: 'Agents',
  scenarios: 'Scenarios',
  metric_trend: 'Metric trend',
}

const CHART_TYPES: ResultsChartType[] = ['line', 'bar', 'area']

export const CHART_TYPE_LABELS: Record<ResultsChartType, string> = {
  line: 'Line',
  bar: 'Bar',
  area: 'Area',
}

const STORAGE_KEY = 'resultsDashboardLayout.v2'

function seed(type: ResultsWidgetType, display: ResultsChartType): ResultsWidget {
  return { id: type, type, display }
}

export const DEFAULT_RESULTS_WIDGETS: ResultsWidget[] = [
  seed('agent_cost', 'bar'),
  seed('model_cost', 'area'),
  seed('tool_calls', 'line'),
  seed('avg_score', 'line'),
  seed('completion', 'line'),
  seed('lowest_metrics', 'bar'),
]

export function copyResultsWidgets(widgets: ResultsWidget[]): ResultsWidget[] {
  return widgets.map((widget) => ({ ...widget }))
}

function isChartType(value: unknown): value is ResultsChartType {
  return typeof value === 'string' && CHART_TYPES.includes(value as ResultsChartType)
}

function isWidgetType(value: unknown): value is ResultsWidgetType {
  return typeof value === 'string' && value in WIDGET_LABELS
}

function sanitize(raw: unknown): ResultsWidget[] {
  if (!Array.isArray(raw)) return DEFAULT_RESULTS_WIDGETS.map((item) => ({ ...item }))
  const widgets: ResultsWidget[] = []
  const seen = new Set<string>()
  for (const item of raw) {
    if (!item || typeof item !== 'object') continue
    const candidate = item as Partial<ResultsWidget>
    if (!isWidgetType(candidate.type) || typeof candidate.id !== 'string') continue
    if (seen.has(candidate.id)) continue
    seen.add(candidate.id)
    widgets.push({
      id: candidate.id,
      type: candidate.type,
      display: isChartType(candidate.display) ? candidate.display : 'line',
      hidden: Boolean(candidate.hidden),
      metricId: typeof candidate.metricId === 'string' ? candidate.metricId : null,
    })
  }
  return widgets.length ? widgets : DEFAULT_RESULTS_WIDGETS.map((item) => ({ ...item }))
}

export function readResultsDashboardLayout(): ResultsWidget[] {
  if (typeof window === 'undefined') return DEFAULT_RESULTS_WIDGETS.map((item) => ({ ...item }))
  try {
    return sanitize(JSON.parse(localStorage.getItem(STORAGE_KEY) || 'null'))
  } catch {
    return DEFAULT_RESULTS_WIDGETS.map((item) => ({ ...item }))
  }
}

export function writeResultsDashboardLayout(widgets: ResultsWidget[]) {
  if (typeof window === 'undefined') return
  localStorage.setItem(STORAGE_KEY, JSON.stringify(widgets))
}

export function visibleWidgets(widgets: ResultsWidget[]): ResultsWidget[] {
  return widgets.filter((widget) => !widget.hidden).slice(0, MAX_VISIBLE_WIDGETS)
}
