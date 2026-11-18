/**
 * Results dashboard v1 — pluggable data insights (grid card → optional drill).
 *
 * ## Add a new insight (plug-and-play)
 * 1. `resultsDashboardLayout.ts` — `ResultsWidgetType`, label, optional `ADDABLE_WIDGETS`.
 * 2. `resultsDashboardSeries.ts` (or a colocated module) — `buildCard` → `ChartModel`.
 * 3. Register below with `buildCard`, optional `capabilities`, optional `openDetail`.
 * 4. If drill is a new screen — add a branch in `ResultsDashboardTab` detail renderer once
 *    (same pattern as `UsageWidgetDetail` / `ToolsMergedDetail`).
 *
 * ## Scale (production)
 * - Grid cards: single `dashboard-ops` aggregate (Redis-cached), not full run lists.
 * - Drill leaves: `listEvaluatorResults` with `skip`/`limit` only.
 * - Detail-only list fetch (500 cap) when a drill is open — grid stays ops-only.
 *
 * Unregistered types use `panelModel` fallback in the dashboard tab until migrated.
 */
import type { CallImportMetricAggregate, EvaluatorResultsDashboardOpsResponse } from '../../../types/api'
import type { ResultsWidget, ResultsWidgetType } from './resultsDashboardLayout'
import type { ChartModel } from './resultsDashboardSeries'
import {
  mergedToolsCard,
  metricUsageAgentsCard,
  totalCallsByAgentCard,
  usageCard,
} from './resultsDashboardSeries'

export type InsightPanelContext = {
  ops: EvaluatorResultsDashboardOpsResponse | undefined
  aggregateTotal: number
  aggregateCompleted: number
  agentRows: Array<{ id: string; name: string; total: number }>
  primaryMetric: CallImportMetricAggregate | null
  usageCurrency?: 'USD' | 'INR'
  usageInrRate?: number
}

export type InsightCapabilities = {
  currency?: boolean
}

/** Detail routes owned by the insight; extend when adding new drill flows. */
export type InsightDetailTarget =
  | { kind: 'usage'; widgetId: string }
  | { kind: 'tools'; widgetId: string }
  | { kind: 'metric_flow'; widgetId: string }
  | { kind: 'total_calls_flow'; widgetId: string }

export type InsightRegistration = {
  buildCard: (widget: ResultsWidget, ctx: InsightPanelContext) => ChartModel
  capabilities?: InsightCapabilities
  openDetail?: (widgetId: string) => InsightDetailTarget
}

const REGISTRY: Partial<Record<ResultsWidgetType, InsightRegistration>> = {
  usage: {
    capabilities: { currency: true },
    buildCard: (_widget, ctx) =>
      usageCard(ctx.ops, {
        currency: ctx.usageCurrency,
        inrRate: ctx.usageInrRate,
      }),
    openDetail: (widgetId) => ({ kind: 'usage', widgetId }),
  },
  tools: {
    buildCard: (_widget, ctx) => mergedToolsCard(ctx.ops),
    openDetail: (widgetId) => ({ kind: 'tools', widgetId }),
  },
  tool_calls: {
    buildCard: (_widget, ctx) => mergedToolsCard(ctx.ops),
    openDetail: (widgetId) => ({ kind: 'tools', widgetId }),
  },
  total_calls: {
    buildCard: (_widget, ctx) =>
      totalCallsByAgentCard(
        ctx.agentRows.map((row) => ({ name: row.name, total: row.total })),
        ctx.aggregateTotal,
      ),
    openDetail: (widgetId) => ({ kind: 'total_calls_flow', widgetId }),
  },
  metric_usage: {
    buildCard: (_widget, ctx) => metricUsageAgentsCard(ctx.agentRows.map((row) => ({ name: row.name, total: row.total }))),
    openDetail: (widgetId) => ({ kind: 'metric_flow', widgetId }),
  },
}

export function insightCapabilities(type: ResultsWidgetType): InsightCapabilities | undefined {
  return REGISTRY[type]?.capabilities
}

export function buildRegisteredInsightCard(
  widget: ResultsWidget,
  ctx: InsightPanelContext,
): ChartModel | null {
  const entry = REGISTRY[widget.type]
  return entry ? entry.buildCard(widget, ctx) : null
}

/** Widget card click — registered insights supply their drill route; others fall back to generic widget detail. */
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