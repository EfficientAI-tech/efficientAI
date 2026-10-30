import { MOCK_AGENTS } from './mockCatalog'

export type DashboardSection =
  | 'overview'
  | 'usage'
  | 'model'
  | 'tool-calls'
  | 'tools'
  | 'tool'
  | 'agent'
  | 'failures'
  | 'tree'

export type FailureKind = 'tool' | 'outcome'

const SECTIONS: DashboardSection[] = [
  'overview',
  'usage',
  'model',
  'tool-calls',
  'tools',
  'tool',
  'agent',
  'failures',
  'tree',
]

export function parseDashboardSection(value: string | null): DashboardSection {
  return SECTIONS.includes(value as DashboardSection) ? (value as DashboardSection) : 'overview'
}

export function parseFailureKind(value: string | null): FailureKind | null {
  return value === 'tool' || value === 'outcome' ? value : null
}

export const SECTION_LABELS: Record<DashboardSection, string> = {
  overview: 'Dashboard',
  usage: 'Usage',
  model: 'Model',
  'tool-calls': 'Tool calls',
  tools: 'Tools',
  tool: 'Tool',
  agent: 'Agent',
  failures: 'Failures',
  tree: 'Metric tree',
}

export const WIDGET_COLORS: Record<string, string> = {
  cost: '#0d9488',
  tool_calls: '#7c3aed',
  tool_use: '#E01E5A',
  failures: '#e11d48',
  total_calls: '#2563eb',
  avg_duration: '#0891b2',
  metric_usage: '#ca8a04',
  scenarios: '#db2777',
  closing_quality: '#4f46e5',
  early_ending: '#ea580c',
  talk_ratio: '#059669',
  rag_failures: '#c026d3',
  silence_duration: '#0284c7',
  longest_pause: '#b45309',
}

export const TOP_BAR_COLOR = '#64748b'

export const AGENT_COLORS: Record<string, string> = {
  'mock-agent-support-eu': '#6366f1',
  'mock-agent-sales-outbound': '#14b8a6',
  'mock-agent-billing': '#f97316',
}

export const CHART_PALETTE = [
  '#2563eb',
  '#E01E5A',
  '#0d9488',
  '#ca8a04',
  '#7c3aed',
  '#ea580c',
  '#0891b2',
  '#16a34a',
  '#db2777',
  '#336791',
]

export function withAlpha(hex: string, alpha: number) {
  const raw = hex.replace('#', '')
  const full = raw.length === 3 ? raw.split('').map((char) => `${char}${char}`).join('') : raw
  const value = Number.parseInt(full, 16)
  if (Number.isNaN(value)) return hex
  const r = (value >> 16) & 255
  const g = (value >> 8) & 255
  const b = value & 255
  return `rgba(${r}, ${g}, ${b}, ${alpha})`
}

export function agentChartSeries(): Array<{ key: string; label: string; color?: string }> {
  return MOCK_AGENTS.map((agent) => ({
    key: agent.id,
    label: agent.name,
    color: AGENT_COLORS[agent.id],
  }))
}
