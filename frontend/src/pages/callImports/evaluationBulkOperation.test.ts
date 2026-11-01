import { describe, expect, it } from 'vitest'
import {
  bulkCancelResponseKeepsBulkOperation,
  evaluationRunPollMs,
  evaluationShouldPollRun,
} from './evaluationBulkOperation'

describe('evaluationRunPollMs', () => {
  it('polls during bulk retry on a partial run', () => {
    const evaluation = {
      status: 'partial',
      bulk_operation: 'retry' as const,
      total_rows: 10209,
      completed_rows: 66,
      failed_rows: 10143,
    }
    expect(evaluationShouldPollRun(evaluation)).toBe(true)
    expect(evaluationRunPollMs(evaluation)).toBe(5000)
  })

  it('does not poll a finished partial run with no bulk op', () => {
    const evaluation = {
      status: 'partial',
      bulk_operation: null,
      total_rows: 100,
      completed_rows: 90,
      failed_rows: 10,
    }
    expect(evaluationShouldPollRun(evaluation)).toBe(false)
    expect(evaluationRunPollMs(evaluation)).toBe(false)
  })

  it('polls when rows are in flight even if status is still partial', () => {
    const evaluation = {
      status: 'partial',
      bulk_operation: null,
      total_rows: 100,
      completed_rows: 10,
      failed_rows: 20,
    }
    expect(evaluationShouldPollRun(evaluation)).toBe(true)
    expect(evaluationRunPollMs(evaluation)).toBe(3000)
  })
})

describe('bulkCancelResponseKeepsBulkOperation', () => {
  it('keeps bulk UI when worker enqueued with zero eval targets', () => {
    expect(
      bulkCancelResponseKeepsBulkOperation({
        target_count: 0,
        worker_enqueued: true,
      }),
    ).toBe(true)
  })

  it('clears bulk UI on idempotent no-op', () => {
    expect(
      bulkCancelResponseKeepsBulkOperation({
        target_count: 0,
        worker_enqueued: false,
      }),
    ).toBe(false)
  })
})
