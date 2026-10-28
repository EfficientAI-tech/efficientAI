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

export function evaluationTerminalStatus(status?: string): boolean {
  return (
    status === 'completed' ||
    status === 'failed' ||
    status === 'cancelled' ||
    status === 'partial'
  )
}

/** Poll the open evaluation run (row table / side panel on eval detail). */
export function evaluationRunPollMs(
  evaluation:
    | Pick<CallImportEvaluation, 'status' | 'bulk_operation' | 'total_rows'>
    | undefined,
): number | false {
  if (!evaluation) return false
  if (evaluationTerminalStatus(evaluation.status)) return false
  if (evaluation.bulk_operation) return EVALUATION_BULK_OPERATION_POLL_MS
  const status = evaluation.status
  if (status !== 'pending' && status !== 'running') return false
  const totalRows = evaluation.total_rows ?? 0
  return totalRows > EVAL_LARGE_ROW_THRESHOLD
    ? EVAL_PROGRESS_POLL_LARGE_MS
    : EVAL_PROGRESS_POLL_MS
}

/** Poll the evaluations list on import detail (evaluations / insights tabs only). */
export function evaluationListPollMs(
  evaluations: CallImportEvaluation[],
  options?: { slowCadenceMs?: number },
): number | false {
  const active = evaluations.filter(
    (row) => !evaluationTerminalStatus(row.status),
  )
  if (!active.length) return false
  if (active.some((row) => row.bulk_operation)) {
    return EVALUATION_BULK_OPERATION_POLL_MS
  }
  if (
    !active.some(
      (row) => row.status === 'pending' || row.status === 'running',
    )
  ) {
    return false
  }
  return options?.slowCadenceMs ?? 3000
}
