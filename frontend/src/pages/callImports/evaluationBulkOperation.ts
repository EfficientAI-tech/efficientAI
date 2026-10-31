import type { CallImportEvaluation } from '../../types/api'

export type BulkEvaluationOperation = NonNullable<
  CallImportEvaluation['bulk_operation']
>

export function evaluationBulkOperationLabel(
  op: BulkEvaluationOperation,
): string {
  switch (op) {
    case 'abort':
      return 'Aborting run…'
    case 'force_fail_pending':
      return 'Processing bulk operation…'
    case 'retry':
      return 'Retrying failed rows…'
  }
}

export function evaluationBulkOperationDescription(
  op: BulkEvaluationOperation,
): string {
  switch (op) {
    case 'abort':
      return 'Stopping in-flight and queued rows. Other actions stay disabled until this finishes.'
    case 'force_fail_pending':
      return 'A background operation is in progress. Other actions stay disabled until it finishes.'
    case 'retry':
      return 'Re-enqueuing rows for evaluation. Other actions stay disabled until this finishes.'
  }
}

export function evaluationHasActiveBulkOperation(
  evaluation: Pick<CallImportEvaluation, 'bulk_operation'>,
): boolean {
  return evaluation.bulk_operation != null
}

/** Poll cadence while a bulk background operation is in flight. */
export const EVALUATION_BULK_OPERATION_POLL_MS = 5000

const EVAL_PROGRESS_POLL_MS = 3000
const EVAL_PROGRESS_POLL_LARGE_MS = 10000
const EVAL_LARGE_ROW_THRESHOLD = 5000

export { EVAL_PROGRESS_POLL_MS }

export function evaluationTerminalStatus(status?: string): boolean {
  return (
    status === 'completed' ||
    status === 'failed' ||
    status === 'cancelled' ||
    status === 'partial'
  )
}

/** Rows not yet counted as completed or failed on the parent run. */
export function evaluationRowsInFlight(
  evaluation: Pick<
    CallImportEvaluation,
    'total_rows' | 'completed_rows' | 'failed_rows'
  >,
): number {
  const total = evaluation.total_rows ?? 0
  const accounted =
    (evaluation.completed_rows ?? 0) + (evaluation.failed_rows ?? 0)
  return Math.max(0, total - accounted)
}

export function evaluationShouldPollRun(
  evaluation:
    | Pick<
        CallImportEvaluation,
        | 'status'
        | 'bulk_operation'
        | 'total_rows'
        | 'completed_rows'
        | 'failed_rows'
      >
    | undefined,
): boolean {
  if (!evaluation) return false
  if (evaluation.bulk_operation) return true
  if (evaluationRowsInFlight(evaluation) > 0) return true
  if (evaluationTerminalStatus(evaluation.status)) return false
  const status = evaluation.status
  return status === 'pending' || status === 'running'
}

/** Poll the open evaluation run (row table / side panel on eval detail). */
export function evaluationRunPollMs(
  evaluation:
    | Pick<
        CallImportEvaluation,
        | 'status'
        | 'bulk_operation'
        | 'total_rows'
        | 'completed_rows'
        | 'failed_rows'
      >
    | undefined,
): number | false {
  if (!evaluationShouldPollRun(evaluation)) return false
  if (evaluation!.bulk_operation) return EVALUATION_BULK_OPERATION_POLL_MS
  const totalRows = evaluation!.total_rows ?? 0
  return totalRows > EVAL_LARGE_ROW_THRESHOLD
    ? EVAL_PROGRESS_POLL_LARGE_MS
    : EVAL_PROGRESS_POLL_MS
}

/** Poll the evaluations list on import detail (evaluations / insights tabs only). */
export function evaluationListPollMs(
  evaluations: CallImportEvaluation[],
  options?: { slowCadenceMs?: number },
): number | false {
  if (evaluations.some((row) => row.bulk_operation)) {
    return EVALUATION_BULK_OPERATION_POLL_MS
  }
  if (evaluations.some((row) => evaluationRowsInFlight(row) > 0)) {
    const largest = Math.max(
      0,
      ...evaluations.map((row) => row.total_rows ?? 0),
    )
    return largest > EVAL_LARGE_ROW_THRESHOLD
      ? EVAL_PROGRESS_POLL_LARGE_MS
      : options?.slowCadenceMs ?? 3000
  }
  const active = evaluations.filter(
    (row) => !evaluationTerminalStatus(row.status),
  )
  if (!active.length) return false
  if (
    !active.some(
      (row) => row.status === 'pending' || row.status === 'running',
    )
  ) {
    return false
  }
  return options?.slowCadenceMs ?? 3000
}

/** Keep optimistic bulk UI / polling after cancel API when a worker was queued. */
export function bulkCancelResponseKeepsBulkOperation(data: {
  target_count: number
  worker_enqueued?: boolean
}): boolean {
  return data.target_count > 0 || data.worker_enqueued === true
}
