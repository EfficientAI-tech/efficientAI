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
      return 'Force-failing pending rows…'
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
      return 'Marking pending rows as failed. Other actions stay disabled until this finishes.'
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
