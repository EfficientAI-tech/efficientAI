/**
 * Results dashboard v1 — pluggable data insights (grid card → optional drill).
 *
 * ## Add a new insight
 * 1. `resultsDashboardLayout.ts` — type + label (+ `ADDABLE_WIDGETS`).
 * 2. `buildInsightCardModel` in `resultsDashboardInsightCards.ts`.
 * 3. Register `capabilities` / `openDetail` here; lazy drill in `resultsDashboardInsightDrillHost.tsx`.
 *
 * ## Scale
 * - Grid: `dashboard-ops` (Redis-cached aggregates).
 * - Drills: `listEvaluatorResults` with `skip`/`limit` only.
 */
import type { ResultsWidget, ResultsWidgetType } from './resultsDashboardLayout'
import type { ChartModel } from './resultsDashboardSeries'
import { buildInsightCardModel } from './resultsDashboardInsightCards'
import type { InsightPanelContext } from './resultsDashboardInsightContext'

export type { InsightPanelContext } from './resultsDashboardInsightContext'

export type InsightCapabilities = {
  currency?: boolean
}

export type InsightDetailTarget =
  | { kind: 'usage'; widgetId: string }
  | { kind: 'tools'; widgetId: string }
  | { kind: 'metric_flow'; widgetId: string }
  | { kind: 'total_calls_flow'; widgetId: string }

export type InsightRegistration = {
  capabilities?: InsightCapabilities
  openDetail?: (widgetId: string) => InsightDetailTarget
}

const REGISTRY: Partial<Record<ResultsWidgetType, InsightRegistration>> = {
  usage: {
    capabilities: { currency: true },
    openDetail: (widgetId) => ({ kind: 'usage', widgetId }),
  },
  tools: {
    openDetail: (widgetId) => ({ kind: 'tools', widgetId }),
  },
  tool_calls: {
    openDetail: (widgetId) => ({ kind: 'tools', widgetId }),
  },
  total_calls: {
    openDetail: (widgetId) => ({ kind: 'total_calls_flow', widgetId }),
  },
  metric_usage: {
    openDetail: (widgetId) => ({ kind: 'metric_flow', widgetId }),
  },
}

export function insightCapabilities(type: ResultsWidgetType): InsightCapabilities | undefined {
  return REGISTRY[type]?.capabilities
}

export function buildRegisteredInsightCard(widget: ResultsWidget, ctx: InsightPanelContext): ChartModel {
  return buildInsightCardModel(widget, { ...ctx, widget })
}

export function resolveInsightDetail(widget: ResultsWidget): InsightDetailTarget | null {
  const entry = REGISTRY[widget.type]
  return entry?.openDetail ? entry.openDetail(widget.id) : null
}

export function registerResultsInsight(type: ResultsWidgetType, registration: InsightRegistration): void {
  REGISTRY[type] = registration
}

export function listRegisteredInsightTypes(): ResultsWidgetType[] {
  return Object.keys(REGISTRY) as ResultsWidgetType[]
}