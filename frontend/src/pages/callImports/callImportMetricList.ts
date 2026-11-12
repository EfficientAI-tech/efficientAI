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

/** Deterministic diarized-vs-production transcript agreement metrics. */
export const TRANSCRIPT_AGREEMENT_SCORING_METHODS = new Set(['user_wer', 'user_cer'])

export function isTranscriptAgreementMetric(metric: {
  scoring_method?: string | null
}): boolean {
  return TRANSCRIPT_AGREEMENT_SCORING_METHODS.has(
    (metric.scoring_method || '').trim().toLowerCase(),
  )
}

/** Whether this batch maps a production transcript column (best-effort). */
export function callImportHasProductionTranscriptMapping(data: {
  parameter_mapping?: Record<string, string> | null
  column_mapping?: Record<string, string | null> | null
  content_modality?: string | null
}): boolean {
  const pm = data.parameter_mapping || {}
  if (Object.values(pm).some((v) => typeof v === 'string' && v.trim())) {
    return true
  }
  const legacy = (data.column_mapping?.transcript || '').trim()
  return legacy.length > 0
}

export function callImportHasEvalRecordings(data: {
  content_modality?: string | null
  source_format?: string | null
}): boolean {
  if ((data.content_modality || '').toLowerCase() === 'chat') {
    return false
  }
  return true
}

export function metricsForCallImportRunEvaluation(
  metrics: CallImportMetricRow[],
  evalSurface: MetricSurface,
): CallImportMetricRow[] {
  return metrics.filter((m) =>
    metricEnabledForCallImportEvalSurface(m.enabled_surfaces, evalSurface),
  )
}
