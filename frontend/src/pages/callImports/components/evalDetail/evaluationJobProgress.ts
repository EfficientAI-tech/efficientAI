import type {
  EvaluationMetricClustersState,
  EvaluationPromptImprovementsState,
  EvaluationUserInsightsState,
} from '../../../../types/api'

export type JobProgressView = {
  phaseLabel: string
  statsLine: string | null
  metaLine: string | null
  pct: number
  indeterminate: boolean
}

const EVAL_ANALYSIS_BATCH_SIZE = 500

function formatRowStat(completed: number, total: number): string | null {
  if (total <= 0) return null
  const shown = Math.min(Math.max(completed, 0), total)
  return `${shown.toLocaleString()} / ${total.toLocaleString()} calls processed`
}

function formatBatchStat(completed: number, total: number): string | null {
  if (total <= 0) return null
  return `Batch ${Math.min(completed, total)} / ${total}`
}

function pctOf(done: number, total: number): number {
  if (total <= 0) return 0
  return Math.min(100, Math.max(0, Math.round((done / total) * 100)))
}

function transcriptLabel(source: string | null | undefined): string | null {
  if (source === 'production') return 'Using production transcripts'
  if (source === 'diarised') return 'Using diarised transcripts'
  return null
}

export function getUserInsightsJobProgress(
  state: EvaluationUserInsightsState,
): JobProgressView {
  const progress = state.progress
  const completedBatches = progress?.completed_batches ?? 0
  const totalBatches =
    progress?.total_batches ||
    (progress?.total_rows
      ? Math.ceil(progress.total_rows / EVAL_ANALYSIS_BATCH_SIZE)
      : 0)
  const completedRows = progress?.completed_rows ?? 0
  const totalRows = progress?.total_rows ?? 0
  const phase = progress?.phase
  const inFlightMeta = { metaLine: transcriptLabel(state.transcript_source) }

  if (phase === 'completed') {
    return {
      phaseLabel: 'Finalizing insights…',
      statsLine: formatRowStat(totalRows, totalRows),
      metaLine: inFlightMeta.metaLine,
      pct: 100,
      indeterminate: false,
    }
  }

  if (phase === 'synthesis' || (totalBatches > 0 && completedBatches >= totalBatches)) {
    return {
      phaseLabel: 'Synthesizing insight blocks from extracted patterns…',
      statsLine: formatRowStat(completedRows, totalRows),
      metaLine:
        totalBatches > 0
          ? `${formatBatchStat(completedBatches, totalBatches)} extracted`
          : inFlightMeta.metaLine,
      pct: 92,
      indeterminate: false,
    }
  }

  if (totalBatches > 0) {
    const nextBatch = Math.min(completedBatches + 1, totalBatches)
    // Within a single-batch run the batch counter never moves, so drive the
    // bar from row progress (falling back to batches for long runs).
    const done = totalRows > 0 ? completedRows / totalRows : pctOf(completedBatches, totalBatches) / 100
    return {
      phaseLabel: `Extracting themes from transcripts (batch ${nextBatch} of ${totalBatches})…`,
      statsLine: formatRowStat(completedRows, totalRows),
      metaLine: inFlightMeta.metaLine,
      // Extraction covers ~90% of wall clock; synthesis takes the rest.
      pct: Math.max(3, Math.min(90, Math.round(done * 100 * 0.9))),
      indeterminate: false,
    }
  }

  if (totalRows > 0) {
    return {
      phaseLabel: 'Preparing user insights job…',
      statsLine: formatRowStat(0, totalRows),
      metaLine: inFlightMeta.metaLine,
      pct: 2,
      indeterminate: true,
    }
  }

  return {
    phaseLabel: 'Starting user insights job…',
    statsLine: null,
    metaLine: inFlightMeta.metaLine,
    pct: 0,
    indeterminate: true,
  }
}

export function getMetricClustersJobProgress(
  state: EvaluationMetricClustersState,
): JobProgressView {
  const progress = state.progress
  const completedBatches = progress?.completed_batches ?? 0
  const totalBatches =
    progress?.total_batches ||
    (progress?.total_rows
      ? Math.ceil(progress.total_rows / EVAL_ANALYSIS_BATCH_SIZE)
      : 0)
  const completedRows = progress?.completed_rows ?? 0
  const totalRows = progress?.total_rows ?? 0
  const phase = progress?.phase
  const metricName = progress?.current_metric_name
  const metricIdx = progress?.current_metric_index ?? 0
  const totalMetrics = progress?.total_metrics ?? 0
  // Batch progress alone never moves inside a single 500-row page, so derive
  // the row-driven fraction from rows when available.
  const rowPct = pctOf(
    completedRows,
    totalRows,
  )

  if (phase === 'completed') {
    return {
      phaseLabel: 'Finalizing failure diagnostics…',
      statsLine: formatRowStat(totalRows, totalRows),
      metaLine: null,
      pct: 100,
      indeterminate: false,
    }
  }

  if (phase === 'discovery') {
    return {
      phaseLabel: 'Discovering cross-metric problem themes…',
      statsLine: formatRowStat(completedRows, totalRows),
      metaLine: formatBatchStat(completedBatches, totalBatches),
      pct: 96,
      indeterminate: false,
    }
  }

  if (phase === 'synthesis') {
    const synthPct = totalMetrics > 0 ? pctOf(metricIdx, totalMetrics) : 0
    const synthLabel =
      metricName && totalMetrics > 0
        ? `Synthesizing clusters for ${metricName} (${Math.max(metricIdx, 1)}/${totalMetrics})…`
        : metricName
          ? `Synthesizing clusters for ${metricName}…`
          : 'Synthesizing per-metric clusters…'
    return {
      phaseLabel: synthLabel,
      statsLine: formatRowStat(completedRows, totalRows),
      metaLine: formatBatchStat(completedBatches, totalBatches),
      pct: Math.max(80, Math.min(94, Math.round(80 + synthPct * 0.14))),
      indeterminate: false,
    }
  }

  if (totalBatches > 0) {
    const nextBatch = Math.min(completedBatches + 1, totalBatches)
    const done = totalRows > 0 ? completedRows / totalRows : rowPct / 100
    return {
      phaseLabel: `Clustering flagged calls (batch ${nextBatch} of ${totalBatches})…`,
      statsLine: formatRowStat(completedRows, totalRows),
      metaLine:
        progress?.total_selected_calls != null
          ? `${progress.completed_selected_calls ?? 0} / ${progress.total_selected_calls} flagged in current metric`
          : null,
      pct: Math.max(3, Math.min(80, Math.round(done * 100 * 0.8))),
      indeterminate: false,
    }
  }

  return {
    phaseLabel: 'Starting failure diagnostics…',
    statsLine: null,
    metaLine:
      state.provider || state.model
        ? [state.provider, state.model].filter(Boolean).join(' · ')
        : null,
    pct: 0,
    indeterminate: true,
  }
}

export function getPromptImprovementsJobProgress(
  state: EvaluationPromptImprovementsState,
  clusterGroupCount: number,
): JobProgressView {
  const progress = state.progress as
    | { completed_groups?: number; total_groups?: number; current_metric_name?: string }
    | null
    | undefined
  const totalGroups = progress?.total_groups || clusterGroupCount
  const completedGroups = progress?.completed_groups ?? 0
  const suggestionCount = state.suggestions?.length ?? 0
  const currentMetric = progress?.current_metric_name

  if (totalGroups > 0) {
    const nextGroup = Math.min(completedGroups + 1, totalGroups)
    return {
      phaseLabel: currentMetric
        ? `Drafting prompt edits for ${currentMetric} (${nextGroup} of ${totalGroups})…`
        : `Drafting prompt edits (group ${nextGroup} of ${totalGroups})…`,
      statsLine: `${completedGroups} of ${totalGroups} metric group${totalGroups === 1 ? '' : 's'} done`,
      metaLine:
        suggestionCount > 0
          ? `${suggestionCount} suggestion${suggestionCount === 1 ? '' : 's'} so far`
          : state.imported_agent_name
            ? `Agent: ${state.imported_agent_name}`
            : null,
      pct: Math.max(3, pctOf(completedGroups, totalGroups)),
      indeterminate: false,
    }
  }

  return {
    phaseLabel: 'Generating prompt improvement suggestions…',
    statsLine: suggestionCount > 0 ? `${suggestionCount} suggestions drafted` : null,
    metaLine: null,
    pct: 0,
    indeterminate: true,
  }
}
