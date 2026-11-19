import type { StudioRunResult } from './MetricsStudioScorePanel'
import type { StudioResultTableColumn } from './MetricsStudioResultsTable'
import {
  studioMetricRationale,
  type StudioMetricScoreEntry,
} from './studioResultScoreDisplay'
import { asArray } from '../../../lib/safeData'

type StudioRunMetricSelection = {
  selected_metric_ids?: string[]
  selected_metric_groups?: Record<string, string[]> | null
}

type MetricRationaleFlag = {
  id?: string
  capture_rationale?: boolean
  children?: Array<{ id?: string; capture_rationale?: boolean }>
}

/** Child label ids collapsed under a categorization parent for this run. */
export function childrenInStudioGroups(
  run: StudioRunMetricSelection | undefined,
): Set<string> {
  const set = new Set<string>()
  const groups = run?.selected_metric_groups
  if (!groups || typeof groups !== 'object') return set
  for (const childIds of Object.values(groups)) {
    if (!Array.isArray(childIds)) continue
    for (const cid of childIds) {
      if (typeof cid === 'string' && cid) set.add(cid)
    }
  }
  return set
}

export function parentIdsFromStudioGroups(run: StudioRunMetricSelection | undefined): string[] {
  const groups = run?.selected_metric_groups
  if (!groups || typeof groups !== 'object') return []
  return Object.keys(groups).filter((id) => typeof id === 'string' && id)
}

/**
 * Table column metric ids — parents for categorization groups, standalone
 * leaf metrics otherwise (mirrors call import evaluation displayMetrics).
 */
export function studioTableMetricIds(
  run: StudioRunMetricSelection | undefined,
  metricNameById: Record<string, string>,
  results: StudioRunResult[],
): Array<{ metricId: string; name: string }> {
  const suppressedChildren = childrenInStudioGroups(run)
  const ordered: { metricId: string; name: string }[] = []
  const seen = new Set<string>()

  const push = (metricId: string) => {
    if (!metricId || seen.has(metricId) || suppressedChildren.has(metricId)) return
    seen.add(metricId)
    ordered.push({
      metricId,
      name: metricNameById[metricId] || metricId.slice(0, 8),
    })
  }

  for (const parentId of parentIdsFromStudioGroups(run)) {
    push(parentId)
  }

  for (const id of asArray<string>(run?.selected_metric_ids)) {
    push(id)
  }

  if (ordered.length === 0) {
    for (const row of results) {
      for (const metricId of Object.keys(row.metric_scores ?? {})) {
        push(metricId)
      }
    }
  }

  return ordered
}

export function metricExpectsRationale(metricId: string, metrics: MetricRationaleFlag[]): boolean {
  for (const m of metrics) {
    if (m.id === metricId) {
      return (
        !!m.capture_rationale || (m.children ?? []).some((c) => !!c.capture_rationale)
      )
    }
    for (const child of m.children ?? []) {
      if (child.id === metricId) {
        return !!child.capture_rationale || !!m.capture_rationale
      }
    }
  }
  return false
}

export function buildStudioResultTableColumns(
  run: StudioRunMetricSelection | undefined,
  metricNameById: Record<string, string>,
  results: StudioRunResult[],
  metrics: MetricRationaleFlag[],
): StudioResultTableColumn[] {
  const base = studioTableMetricIds(run, metricNameById, results)
  const columns: StudioResultTableColumn[] = []
  for (const { metricId, name } of base) {
    columns.push({
      columnKey: metricId,
      metricId,
      name,
    })
    const hasRationale =
      metricExpectsRationale(metricId, metrics) ||
      results.some((row) =>
        studioMetricRationale(row.metric_scores?.[metricId] as StudioMetricScoreEntry | undefined),
      )
    if (hasRationale) {
      columns.push({
        columnKey: `${metricId}:rationale`,
        metricId,
        name,
        isRationale: true,
      })
    }
  }
  return columns
}