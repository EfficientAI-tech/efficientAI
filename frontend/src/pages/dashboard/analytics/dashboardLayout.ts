import { create } from 'zustand'
import type { Currency } from './mockUsage'

export type ChartType = 'line' | 'area' | 'bar' | 'stacked' | 'donut' | 'distribution'
export type WidgetDisplay = 'number' | ChartType

export type WidgetType =
  | 'cost'
  | 'tool_calls'
  | 'tool_use'
  | 'failures'
  | 'total_calls'
  | 'avg_duration'
  | 'metric_usage'
  | 'scenarios'
  | 'closing_quality'
  | 'early_ending'
  | 'talk_ratio'
  | 'rag_failures'
  | 'silence_duration'
  | 'longest_pause'

export type AgentTableColumn = 'agent' | 'metrics' | 'scenarios' | 'calls' | 'cost' | 'tools'
export type LayoutZone = 'topBar' | 'rail' | `row:${number}`

export interface WidgetInstance {
  id: string
  type: WidgetType
  display: WidgetDisplay
  hidden?: boolean
  agentId?: string | null
}

export const CHART_TYPE_LABELS: Record<ChartType, string> = {
  line: 'Line',
  area: 'Area',
  bar: 'Bar',
  stacked: 'Stacked',
  donut: 'Donut',
  distribution: 'Distribution',
}

export type WidgetCategory = 'Trends' | 'Usage' | 'Failures' | 'Funnel' | 'Index'

export const WIDGET_META: Record<
  WidgetType,
  { label: string; defaultDisplay: WidgetDisplay; category: WidgetCategory; rail?: boolean }
> = {
  cost: { label: 'Total cost', defaultDisplay: 'number', category: 'Trends' },
  tool_calls: { label: 'Tool calls', defaultDisplay: 'number', category: 'Usage' },
  tool_use: { label: 'Tools', defaultDisplay: 'number', category: 'Usage' },
  failures: { label: 'Failures', defaultDisplay: 'number', category: 'Failures' },
  total_calls: { label: 'Total calls', defaultDisplay: 'bar', category: 'Trends' },
  avg_duration: { label: 'Avg duration / call', defaultDisplay: 'line', category: 'Trends' },
  metric_usage: { label: 'Metric usage', defaultDisplay: 'line', category: 'Trends' },
  scenarios: { label: 'Scenarios / agent', defaultDisplay: 'stacked', category: 'Funnel' },
  closing_quality: { label: 'Closing quality', defaultDisplay: 'number', category: 'Index', rail: true },
  early_ending: { label: 'Early ending', defaultDisplay: 'number', category: 'Index', rail: true },
  talk_ratio: { label: 'Talk ratio', defaultDisplay: 'number', category: 'Index', rail: true },
  rag_failures: { label: 'RAG failures', defaultDisplay: 'number', category: 'Index', rail: true },
  silence_duration: { label: 'Silence duration', defaultDisplay: 'number', category: 'Index', rail: true },
  longest_pause: { label: 'Longest pause', defaultDisplay: 'number', category: 'Index', rail: true },
}

export const WIDGET_TYPES = Object.keys(WIDGET_META) as WidgetType[]

export const AGENT_TABLE_COLUMNS: Array<{ id: AgentTableColumn; label: string }> = [
  { id: 'agent', label: 'Agents' },
  { id: 'metrics', label: 'No. of metrics' },
  { id: 'scenarios', label: 'No. of scenarios' },
  { id: 'calls', label: 'Calls' },
  { id: 'cost', label: 'Cost' },
  { id: 'tools', label: 'Tool calls' },
]

let widgetSeq = 1

export function makeWidget(type: WidgetType, display?: WidgetDisplay): WidgetInstance {
  widgetSeq += 1
  return {
    id: `${type}-${widgetSeq}`,
    type,
    display: display ?? WIDGET_META[type].defaultDisplay,
  }
}

export interface DashboardLayoutV2 {
  topBar: WidgetInstance[]
  rows: WidgetInstance[][]
  rail: WidgetInstance[]
  tableColumns: AgentTableColumn[]
  currency: Currency
}

function seed(type: WidgetType, display?: WidgetDisplay): WidgetInstance {
  return { id: type, type, display: display ?? WIDGET_META[type].defaultDisplay }
}

export const DEFAULT_LAYOUT: DashboardLayoutV2 = {
  topBar: [seed('cost', 'number'), seed('tool_calls', 'number'), seed('tool_use', 'number'), seed('failures', 'number')],
  rows: [
    [seed('total_calls', 'bar'), seed('avg_duration', 'line'), seed('metric_usage', 'line')],
    [seed('scenarios', 'stacked')],
  ],
  rail: [
    seed('closing_quality', 'number'),
    seed('early_ending', 'number'),
    seed('talk_ratio', 'number'),
    seed('rag_failures', 'number'),
  ],
  tableColumns: ['agent', 'metrics', 'scenarios'],
  currency: 'USD',
}

const STORAGE_KEY = 'dashboardLayout.v2.2'

function normalizeRows(rows: WidgetInstance[][]): WidgetInstance[][] {
  const next: WidgetInstance[][] = []
  for (const row of rows) {
    const visible = row.filter(Boolean)
    for (let i = 0; i < visible.length; i += 3) {
      next.push(visible.slice(i, i + 3))
    }
  }
  return next.length ? next : [[]]
}

function cloneLayout(layout: DashboardLayoutV2): DashboardLayoutV2 {
  return {
    topBar: layout.topBar.map((item) => ({ ...item })),
    rows: layout.rows.map((row) => row.map((item) => ({ ...item }))),
    rail: layout.rail.map((item) => ({ ...item })),
    tableColumns: [...layout.tableColumns],
    currency: layout.currency,
  }
}

function readLayout(): DashboardLayoutV2 {
  if (typeof window === 'undefined') return cloneLayout(DEFAULT_LAYOUT)
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return cloneLayout(DEFAULT_LAYOUT)
    const parsed = JSON.parse(raw) as Partial<DashboardLayoutV2>
    return {
      topBar: Array.isArray(parsed.topBar) ? parsed.topBar : DEFAULT_LAYOUT.topBar,
      rows: Array.isArray(parsed.rows) ? normalizeRows(parsed.rows) : DEFAULT_LAYOUT.rows,
      rail: Array.isArray(parsed.rail) ? parsed.rail : DEFAULT_LAYOUT.rail,
      tableColumns:
        Array.isArray(parsed.tableColumns) && parsed.tableColumns.length
          ? parsed.tableColumns
          : DEFAULT_LAYOUT.tableColumns,
      currency: parsed.currency === 'INR' ? 'INR' : 'USD',
    }
  } catch {
    return cloneLayout(DEFAULT_LAYOUT)
  }
}

interface LayoutState extends DashboardLayoutV2 {
  setCurrency: (currency: Currency) => void
  setDisplay: (id: string, display: WidgetDisplay) => void
  setAgent: (id: string, agentId: string | null) => void
  setHidden: (id: string, hidden: boolean) => void
  removeWidget: (id: string) => void
  addWidget: (type: WidgetType, zone: LayoutZone) => void
  moveWidget: (id: string, dest: { zone: LayoutZone; index: number }) => void
  setTableColumns: (columns: AgentTableColumn[]) => void
  reset: () => void
}

function persist(state: DashboardLayoutV2) {
  if (typeof window === 'undefined') return
  localStorage.setItem(
    STORAGE_KEY,
    JSON.stringify({
      topBar: state.topBar,
      rows: state.rows,
      rail: state.rail,
      tableColumns: state.tableColumns,
      currency: state.currency,
    }),
  )
}

export function locateWidget(
  state: Pick<DashboardLayoutV2, 'topBar' | 'rows' | 'rail'>,
  id: string,
): { zone: LayoutZone; index: number; widget: WidgetInstance } | null {
  const top = state.topBar.findIndex((item) => item.id === id)
  if (top >= 0) return { zone: 'topBar', index: top, widget: state.topBar[top] }
  const rail = state.rail.findIndex((item) => item.id === id)
  if (rail >= 0) return { zone: 'rail', index: rail, widget: state.rail[rail] }
  for (let row = 0; row < state.rows.length; row += 1) {
    const index = state.rows[row].findIndex((item) => item.id === id)
    if (index >= 0) return { zone: `row:${row}`, index, widget: state.rows[row][index] }
  }
  return null
}

function findWidget(
  state: DashboardLayoutV2,
  id: string,
): { zone: LayoutZone; index: number; widget: WidgetInstance } | null {
  return locateWidget(state, id)
}

function takeWidget(state: DashboardLayoutV2, id: string): WidgetInstance | null {
  const found = findWidget(state, id)
  if (!found) return null
  if (found.zone === 'topBar') state.topBar.splice(found.index, 1)
  else if (found.zone === 'rail') state.rail.splice(found.index, 1)
  else {
    const row = Number(found.zone.slice(4))
    state.rows[row]?.splice(found.index, 1)
  }
  return found.widget
}

function insertWidget(state: DashboardLayoutV2, widget: WidgetInstance, dest: { zone: LayoutZone; index: number }) {
  if (dest.zone === 'topBar') {
    widget.display = 'number'
    state.topBar.splice(Math.min(dest.index, state.topBar.length), 0, widget)
    return
  }
  if (dest.zone === 'rail') {
    state.rail.splice(Math.min(dest.index, state.rail.length), 0, widget)
    return
  }
  const row = Number(dest.zone.slice(4))
  if (!state.rows[row]) state.rows[row] = []
  state.rows[row].splice(Math.min(dest.index, state.rows[row].length), 0, widget)
  state.rows = normalizeRows(state.rows)
}

function mapWidget(state: DashboardLayoutV2, id: string, patch: Partial<WidgetInstance>): DashboardLayoutV2 {
  const next = cloneLayout(state)
  const found = findWidget(next, id)
  if (!found) return next
  Object.assign(found.widget, patch)
  return next
}

export function defaultChartType(kind: string | undefined): ChartType {
  const key = (kind ?? '').toLowerCase()
  if (key === 'count' || key === 'boolean') return 'bar'
  if (key === 'category') return 'stacked'
  if (key === 'duration' || key === 'ratio' || key === 'rating' || key === 'number') return 'line'
  return 'line'
}

const initial = readLayout()

export const useDashboardLayout = create<LayoutState>((set, get) => ({
  ...initial,
  setCurrency: (currency) => {
    const next = { ...get(), currency }
    persist(next)
    set({ currency })
  },
  setDisplay: (id, display) => {
    const next = mapWidget(get(), id, { display })
    persist(next)
    set({ topBar: next.topBar, rows: next.rows, rail: next.rail })
  },
  setAgent: (id, agentId) => {
    const next = mapWidget(get(), id, { agentId })
    persist(next)
    set({ topBar: next.topBar, rows: next.rows, rail: next.rail })
  },
  setHidden: (id, hidden) => {
    const next = mapWidget(get(), id, { hidden })
    persist(next)
    set({ topBar: next.topBar, rows: next.rows, rail: next.rail })
  },
  removeWidget: (id) => {
    const next = cloneLayout(get())
    takeWidget(next, id)
    next.rows = normalizeRows(next.rows)
    persist(next)
    set({ topBar: next.topBar, rows: next.rows, rail: next.rail })
  },
  addWidget: (type, zone) => {
    const next = cloneLayout(get())
    insertWidget(next, makeWidget(type), { zone, index: 999 })
    persist(next)
    set({ topBar: next.topBar, rows: next.rows, rail: next.rail })
  },
  moveWidget: (id, dest) => {
    const next = cloneLayout(get())
    const found = findWidget(next, id)
    if (!found) return
    const widget = takeWidget(next, id)
    if (!widget) return
    const index = found.zone === dest.zone && found.index < dest.index ? dest.index - 1 : dest.index
    insertWidget(next, widget, { zone: dest.zone, index })
    persist(next)
    set({ topBar: next.topBar, rows: next.rows, rail: next.rail })
  },
  setTableColumns: (tableColumns) => {
    const next = { ...get(), tableColumns }
    persist(next)
    set({ tableColumns })
  },
  reset: () => {
    const next = cloneLayout(DEFAULT_LAYOUT)
    persist(next)
    set(next)
  },
}))
