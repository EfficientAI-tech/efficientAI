import type { EvaluatorResultRow } from '../../../types/api'

/** Shared list slice for drill leaves (paginated `skip`/`limit` on live data). */
export type RunListBase = {
  agentId?: string
  suiteId?: string
  scenarioId?: string
  since?: string
  until?: string
  /** IANA zone used for dashboard-ops chart days (must match drill day bounds). */
  chartTimeZone?: string
  playground: boolean
  sampleOn: boolean
  sampleRows: EvaluatorResultRow[]
}

/** Every full-page insight drill implements this. */
export type InsightDrillBaseProps = {
  runListBase: RunListBase
  onBack: () => void
  onOpenResult: (resultId: string) => void
}

export type InsightDetailState =
  | { kind: 'usage'; widgetId: string }
  | { kind: 'tools'; widgetId: string }
  | { kind: 'metric_flow'; widgetId: string; agentId?: string; metricId?: string; scenarioId?: string }
  | { kind: 'total_calls_flow'; widgetId: string; agentId?: string }
  | { kind: 'widget'; widgetId: string }
  | { kind: 'metric'; metricId: string }
  | { kind: 'agent'; agentId: string }
  | null