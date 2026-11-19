export type ResultsChartType = 'line' | 'bar' | 'area'

export type ResultsWidgetType =
  | 'total_calls'
  | 'avg_duration'
  | 'metric_usage'
  | 'scenarios_by_agent'
  | 'usage'
  | 'tools'
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

/** How many charts ship visible in a fresh layout — users can add more with no cap. */
export const DEFAULT_DASHBOARD_WIDGET_COUNT = 5

export const WIDGET_LABELS: Record<ResultsWidgetType, string> = {
  total_calls: 'Total calls',
  avg_duration: 'Avg duration / call',
  metric_usage: 'Metric usage',
  scenarios_by_agent: 'Scenarios / agent',
  usage: 'Usage',
  tools: 'Tools & tool calls',
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

const STORAGE_KEY = 'resultsDashboardLayout.v9'

export const ADDABLE_WIDGETS: ResultsWidgetType[] = [
  'total_calls',
  'tools',
  'usage',
  'completion',
  'avg_duration',
  'metric_usage',
  'lowest_metrics',
  'scenarios_by_agent',
]

function seed(type: ResultsWidgetType, display: ResultsChartType): ResultsWidget {
  return { id: type, type, display }
}

export const DEFAULT_RESULTS_WIDGETS: ResultsWidget[] = [
  seed('total_calls', 'bar'),
  seed('metric_usage', 'bar'),
  seed('tools', 'line'),
  seed('completion', 'line'),
  seed('avg_duration', 'line'),
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

function mergeToolWidgetType(type: ResultsWidgetType): ResultsWidgetType {
  return type === 'tool_calls' ? 'tools' : type
}

function sanitize(raw: unknown): ResultsWidget[] {
  if (!Array.isArray(raw)) return DEFAULT_RESULTS_WIDGETS.map((item) => ({ ...item }))
  const widgets: ResultsWidget[] = []
  const seen = new Set<string>()
  for (const item of raw) {
    if (!item || typeof item !== 'object') continue
    const candidate = item as Partial<ResultsWidget>
    if (!isWidgetType(candidate.type) || typeof candidate.id !== 'string') continue
    const type = mergeToolWidgetType(candidate.type)
    const id = type === 'tools' && (candidate.id === 'tool_calls' || candidate.type === 'tool_calls') ? 'tools' : candidate.id
    if (id === 'tools' && candidate.id !== 'tools' && seen.has('tools')) continue
    if (seen.has(id)) continue
    seen.add(id)
    widgets.push({
      id,
      type,
      display: isChartType(candidate.display) ? candidate.display : 'line',
      hidden: Boolean(candidate.hidden),
      metricId: typeof candidate.metricId === 'string' ? candidate.metricId : null,
    })
  }
  return widgets.length ? widgets : DEFAULT_RESULTS_WIDGETS.map((item) => ({ ...item }))
}

function hideScenariosByAgent(widgets: ResultsWidget[]): ResultsWidget[] {
  return widgets.map((widget) =>
    widget.type === 'scenarios_by_agent' && !widget.hidden
      ? { ...widget, hidden: true }
      : widget,
  )
}

export function readResultsDashboardLayout(): ResultsWidget[] {
  if (typeof window === 'undefined') return DEFAULT_RESULTS_WIDGETS.map((item) => ({ ...item }))
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw) {
      const current = sanitize(JSON.parse(raw))
      if (current.length) return current
    }
    const legacy = localStorage.getItem('resultsDashboardLayout.v8')
    if (legacy) {
      const migrated = hideScenariosByAgent(sanitize(JSON.parse(legacy)))
      writeResultsDashboardLayout(migrated)
      return migrated
    }
    return DEFAULT_RESULTS_WIDGETS.map((item) => ({ ...item }))
  } catch {
    return DEFAULT_RESULTS_WIDGETS.map((item) => ({ ...item }))
  }
}

export function writeResultsDashboardLayout(widgets: ResultsWidget[]) {
  if (typeof window === 'undefined') return
  localStorage.setItem(STORAGE_KEY, JSON.stringify(widgets))
}

export function visibleWidgets(widgets: ResultsWidget[]): ResultsWidget[] {
  return widgets.filter((widget) => !widget.hidden)
}