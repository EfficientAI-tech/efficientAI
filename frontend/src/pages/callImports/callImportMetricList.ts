import {
  metricListSurfaceForAgentMedium,
  type MetricSurface,
} from '../../lib/metricSurfaces'
import type { MetricRow } from '../evaluators/components/metricSelectionUtils'

export type CallImportMetricRow = MetricRow & {
  enabled_surfaces?: string[] | null
  supported_surfaces?: string[] | null
}

/** Eval surface for a call-import batch from ``content_modality``. */
export function callImportEvalSurface(contentModality?: string | null): MetricSurface {
  const medium = (contentModality || '').toLowerCase() === 'chat' ? 'chat' : 'voice'
  return metricListSurfaceForAgentMedium(medium)
}

/** Mirrors ``metric_enabled_for_eval_surface`` on the backend. */
export function metricEnabledForCallImportEvalSurface(
  enabledSurfaces: string[] | null | undefined,
  evalSurface: MetricSurface,
): boolean {
  const surfaces = enabledSurfaces ?? []
  if (surfaces.length === 0) {
    return evalSurface === 'agent' || evalSurface === 'chat_agent'
  }
  return surfaces.includes(evalSurface)
}

/**
 * Metrics eligible for Run Evaluation on this import. Does not filter by
 * agent/scenario links — scoped metrics stay selectable on call imports.
 */
export function metricsForCallImportRunEvaluation(
  metrics: CallImportMetricRow[],
  evalSurface: MetricSurface,
): CallImportMetricRow[] {
  return metrics.filter((m) =>
    metricEnabledForCallImportEvalSurface(m.enabled_surfaces, evalSurface),
  )
}
