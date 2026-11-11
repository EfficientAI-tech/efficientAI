import type { CallImport, CallImportEvaluation } from '../../types/api'
import {
  evaluationListPollMs,
  evaluationRunPollMs,
  evaluationShouldPollRun,
  EVAL_PROGRESS_POLL_MS,
} from './evaluationBulkOperation'

export const IMPORT_LIST_ACTIVE_POLL_MS = 5000
export const IMPORT_DELETE_POLL_MS = 4000
export const IMPORT_FETCH_POLL_MS = 5000
export const IMPORT_PLATFORM_POLL_MS = 4000
export const IMPORT_DIARISE_POLL_MS = 4000

export type LatestEvalSnapshot = Pick<
  CallImport,
  | 'latest_evaluation_status'
  | 'latest_evaluation_total_rows'
  | 'latest_evaluation_completed_rows'
  | 'latest_evaluation_failed_rows'
  | 'latest_evaluation_bulk_operation'
  | 'any_evaluation_poll_active'
>

type ImportLifecycleHeader = {
  status?: CallImport['status'] | string
  source_format?: string | null
  discovery_status?: string | null
  latest_evaluation_status?: string | null
  platform_progress?: { is_active?: boolean } | null
  diarised_pending_rows?: number
  diarised_running_rows?: number
}

const ACTIVE_DISCOVERY = new Set(['queued', 'running'])

function diariseInFlight(header: ImportLifecycleHeader): number {
  return (header.diarised_pending_rows ?? 0) + (header.diarised_running_rows ?? 0)
}

function platformImportActive(header: ImportLifecycleHeader): boolean {
  if (header.platform_progress?.is_active) return true
  return ACTIVE_DISCOVERY.has((header.discovery_status || '').toLowerCase())
}

/** Non-eval work: delete, diarise, platform discovery/import, or fetch before any run. */
export function importBatchStillWorking(
  header: ImportLifecycleHeader | undefined,
): boolean {
  if (!header) return false
  if (header.status === 'deleting') return true
  if (diariseInFlight(header) > 0) return true
  if (platformImportActive(header)) return true
  const status = header.status
  return (
    (status === 'pending' || status === 'processing') &&
    !header.latest_evaluation_status
  )
}

function importLifecyclePollMs(
  header: ImportLifecycleHeader | undefined,
): number | false {
  if (!header || !importBatchStillWorking(header)) return false
  if (header.status === 'deleting') return IMPORT_DELETE_POLL_MS
  if (platformImportActive(header)) return IMPORT_PLATFORM_POLL_MS
  if (diariseInFlight(header) > 0) return IMPORT_DIARISE_POLL_MS
  return IMPORT_FETCH_POLL_MS
}

export function evaluationSnapshotFromLatest(
  snapshot: LatestEvalSnapshot | undefined,
): Pick<
  CallImportEvaluation,
  | 'status'
  | 'bulk_operation'
  | 'total_rows'
  | 'completed_rows'
  | 'failed_rows'
> | null {
  if (!snapshot?.latest_evaluation_status) return null
  const bulk = snapshot.latest_evaluation_bulk_operation
  const status = snapshot.latest_evaluation_status
  return {
    status: status as CallImportEvaluation['status'],
    bulk_operation:
      bulk === 'abort' || bulk === 'retry' || bulk === 'force_fail_pending'
        ? bulk
        : null,
    total_rows: snapshot.latest_evaluation_total_rows ?? 0,
    completed_rows: snapshot.latest_evaluation_completed_rows ?? 0,
    failed_rows: snapshot.latest_evaluation_failed_rows ?? 0,
  }
}

export function latestEvaluationShouldPoll(
  snapshot: LatestEvalSnapshot | undefined,
): boolean {
  if (snapshot?.any_evaluation_poll_active) return true
  const evalRow = evaluationSnapshotFromLatest(snapshot)
  if (!evalRow) return false
  return evaluationShouldPollRun(evalRow)
}

export function latestEvaluationPollMs(
  snapshot: LatestEvalSnapshot | undefined,
): number | false {
  if (snapshot?.any_evaluation_poll_active) {
    const evalRow = evaluationSnapshotFromLatest(snapshot)
    const fromLatest = evalRow ? evaluationRunPollMs(evalRow) : false
    return fromLatest || EVAL_PROGRESS_POLL_MS
  }
  const evalRow = evaluationSnapshotFromLatest(snapshot)
  if (!evalRow) return false
  return evaluationRunPollMs(evalRow)
}

export function importDetailHeaderPollMs(
  header: (ImportLifecycleHeader & LatestEvalSnapshot) | undefined,
  evaluations: CallImportEvaluation[],
): number | false {
  const lifecycleMs = importRowsPollMs(header)
  const evalMs =
    evaluations.length > 0
      ? evaluationListPollMs(evaluations)
      : latestEvaluationPollMs(header)
  if (lifecycleMs && evalMs) {
    return Math.min(lifecycleMs, evalMs)
  }
  return lifecycleMs || evalMs || false
}

/** Import header / list row: fetch, delete, platform, diarise, latest eval. */
export function importHeaderPollMs(
  header: (ImportLifecycleHeader & LatestEvalSnapshot) | undefined,
): number | false {
  if (!header) return false
  const lifecycle = importLifecyclePollMs(header)
  if (lifecycle) return lifecycle
  return latestEvaluationPollMs(header) || false
}

/** Row table on import detail: import lifecycle only (not eval scoring). */
export function importRowsPollMs(
  header: ImportLifecycleHeader | undefined,
): number | false {
  return importLifecyclePollMs(header)
}

export function callImportListPollMs(
  items: CallImport[],
  options?: { watchedPlatformImportIds?: Set<string> },
): number | false {
  if (!items.length) return false
  if (items.some((i) => i.status === 'deleting')) {
    return IMPORT_LIST_ACTIVE_POLL_MS
  }
  if (items.some((i) => i.any_evaluation_poll_active)) {
    return IMPORT_LIST_ACTIVE_POLL_MS
  }
  if (items.some((i) => latestEvaluationShouldPoll(i))) {
    return IMPORT_LIST_ACTIVE_POLL_MS
  }
  const activeImport = items.filter((item) => importBatchStillWorking(item))
  if (activeImport.length > 0) {
    const watched = options?.watchedPlatformImportIds
    if (watched && watched.size > 0) {
      const uncovered = activeImport.filter((item) => !watched.has(item.id))
      if (uncovered.length === 0) return false
    }
    return IMPORT_LIST_ACTIVE_POLL_MS
  }
  return false
}

export { evaluationListPollMs, evaluationRunPollMs, evaluationShouldPollRun }
