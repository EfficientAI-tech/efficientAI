import type { CallImport, CallImportEvaluation } from '../../types/api'
import {
  evaluationListPollMs,
  evaluationRunPollMs,
  evaluationShouldPollRun,
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
>

type ImportLifecycleHeader = {
  status?: CallImport['status'] | string
  source_format?: string | null
  platform_progress?: { is_active?: boolean } | null
  diarised_pending_rows?: number
  diarised_running_rows?: number
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
  const evalRow = evaluationSnapshotFromLatest(snapshot)
  if (!evalRow) return false
  return evaluationShouldPollRun(evalRow)
}

export function latestEvaluationPollMs(
  snapshot: LatestEvalSnapshot | undefined,
): number | false {
  const evalRow = evaluationSnapshotFromLatest(snapshot)
  if (!evalRow) return false
  return evaluationRunPollMs(evalRow)
}

/** Import header / list row: fetch, delete, platform, diarise, latest eval. */
export function importHeaderPollMs(
  header: (ImportLifecycleHeader & LatestEvalSnapshot) | undefined,
): number | false {
  if (!header) return false
  if (header.status === 'deleting') return IMPORT_DELETE_POLL_MS
  const platform = (header.source_format || '').toLowerCase() === 'platform'
  if (
    platform &&
    (header.status === 'pending' ||
      header.status === 'processing' ||
      header.platform_progress?.is_active)
  ) {
    return IMPORT_PLATFORM_POLL_MS
  }
  if (header.status === 'pending' || header.status === 'processing') {
    return IMPORT_FETCH_POLL_MS
  }
  const diariseInFlight =
    (header.diarised_pending_rows ?? 0) + (header.diarised_running_rows ?? 0)
  if (diariseInFlight > 0) return IMPORT_DIARISE_POLL_MS
  const evalPoll = latestEvaluationPollMs(header)
  if (evalPoll) return evalPoll
  if (
    header.status === 'completed' ||
    header.status === 'failed' ||
    header.status === 'mapped' ||
    header.status === 'partial'
  ) {
    return false
  }
  return false
}

/** Row table on import detail: import lifecycle only (not eval scoring). */
export function importRowsPollMs(
  header: ImportLifecycleHeader | undefined,
): number | false {
  if (!header) return false
  if (header.status === 'deleting') return IMPORT_DELETE_POLL_MS
  const platform = (header.source_format || '').toLowerCase() === 'platform'
  if (
    platform &&
    (header.status === 'pending' ||
      header.status === 'processing' ||
      header.platform_progress?.is_active)
  ) {
    return IMPORT_PLATFORM_POLL_MS
  }
  if (header.status === 'pending' || header.status === 'processing') {
    return IMPORT_FETCH_POLL_MS
  }
  const diariseInFlight =
    (header.diarised_pending_rows ?? 0) + (header.diarised_running_rows ?? 0)
  if (diariseInFlight > 0) return IMPORT_DIARISE_POLL_MS
  if (
    header.status === 'completed' ||
    header.status === 'failed' ||
    header.status === 'mapped'
  ) {
    return false
  }
  return false
}

export function callImportListPollMs(
  items: CallImport[],
  options?: { watchedPlatformImportIds?: Set<string> },
): number | false {
  if (!items.length) return false
  if (items.some((i) => i.status === 'deleting')) {
    return IMPORT_LIST_ACTIVE_POLL_MS
  }
  if (items.some((i) => latestEvaluationShouldPoll(i))) {
    return IMPORT_LIST_ACTIVE_POLL_MS
  }
  const activeImport = items.filter(
    (i) => i.status === 'pending' || i.status === 'processing',
  )
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
