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
export const DEFAULT_DASHBOARD_WIDGET_COUNT = 4

export const WIDGET_LABELS: Record<ResultsWidgetType, string> = {
  total_calls: 'Total calls',
  avg_duration: 'Avg duration / call',
  metric_usage: 'Agents',
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

const STORAGE_KEY = 'resultsDashboardLayout.v11'

export const ADDABLE_WIDGETS: ResultsWidgetType[] = [
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

function layoutSignature(widgets: ResultsWidget[]): string {
  return widgets
    .map((widget) =>
      [widget.id, widget.type, widget.display, widget.hidden ? '1' : '0', widget.metricId ?? ''].join(':'),
    )
    .join('|')
}

function hadVisibleTotalCalls(raw: unknown): boolean {
  if (!Array.isArray(raw)) return false
  return raw.some((item) => {
    if (!item || typeof item !== 'object') return false
    const candidate = item as Partial<ResultsWidget>
    return candidate.type === 'total_calls' && !candidate.hidden
  })
}

function sanitize(raw: unknown, options?: { promoteTotalCalls?: boolean }): ResultsWidget[] {
  if (!Array.isArray(raw)) return DEFAULT_RESULTS_WIDGETS.map((item) => ({ ...item }))
  const promoteTotalCalls = options?.promoteTotalCalls !== false
  const widgets: ResultsWidget[] = []
  const seen = new Set<string>()
  let visibleCalls: ResultsWidget | null = null
  for (const item of raw) {
    if (!item || typeof item !== 'object') continue
    const candidate = item as Partial<ResultsWidget>
    if (!isWidgetType(candidate.type) || typeof candidate.id !== 'string') continue
    const type = mergeToolWidgetType(candidate.type)
    const display = isChartType(candidate.display) ? candidate.display : 'line'
    const hidden = Boolean(candidate.hidden)
    if (type === 'total_calls') {
      if (promoteTotalCalls && !hidden) {
        visibleCalls = { id: 'metric_usage', type: 'metric_usage', display, hidden: false }
      }
      continue
    }
    const id = type === 'tools' && (candidate.id === 'tool_calls' || candidate.type === 'tool_calls') ? 'tools' : candidate.id
    if (id === 'tools' && candidate.id !== 'tools' && seen.has('tools')) continue
    if (seen.has(id)) continue
    seen.add(id)
    widgets.push({
      id,
      type,
      display,
      hidden,
      metricId: typeof candidate.metricId === 'string' ? candidate.metricId : null,
    })
  }
  if (visibleCalls) {
    const agents = widgets.find((widget) => widget.type === 'metric_usage')
    if (!agents) {
      widgets.unshift(visibleCalls)
    } else if (agents.hidden) {
      agents.hidden = false
      agents.display = visibleCalls.display
    }
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
    const legacyV10 = localStorage.getItem('resultsDashboardLayout.v10')
    const legacyV9 = localStorage.getItem('resultsDashboardLayout.v9')
    if (legacyV10) {
      const parsedV10 = JSON.parse(legacyV10)
      let fromV10 = sanitize(parsedV10)
      if (legacyV9) {
        const parsedV9 = JSON.parse(legacyV9)
        const untouched =
          layoutSignature(sanitize(parsedV9, { promoteTotalCalls: false }))
          === layoutSignature(sanitize(parsedV10, { promoteTotalCalls: false }))
        if (untouched && hadVisibleTotalCalls(parsedV9)) {
          fromV10 = sanitize(parsedV9)
        } else if (
          hadVisibleTotalCalls(parsedV9)
          && !fromV10.some((widget) => widget.type === 'metric_usage')
        ) {
          const recovered = sanitize(parsedV9).find((widget) => widget.type === 'metric_usage' && !widget.hidden)
          if (recovered) fromV10 = [recovered, ...fromV10]
        }
      }
      writeResultsDashboardLayout(fromV10)
      return fromV10
    }
    if (legacyV9) {
      const migrated = sanitize(JSON.parse(legacyV9))
      writeResultsDashboardLayout(migrated)
      return migrated
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