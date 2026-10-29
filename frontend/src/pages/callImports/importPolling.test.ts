import { describe, expect, it } from 'vitest'
import {
  callImportListPollMs,
  importHeaderPollMs,
  importRowsPollMs,
  latestEvaluationShouldPoll,
} from './importPolling'

describe('importPolling', () => {
  it('polls import header during latest eval bulk retry', () => {
    const header = {
      status: 'completed' as const,
      latest_evaluation_status: 'partial',
      latest_evaluation_total_rows: 100,
      latest_evaluation_completed_rows: 10,
      latest_evaluation_failed_rows: 90,
      latest_evaluation_bulk_operation: 'retry' as const,
    }
    expect(latestEvaluationShouldPoll(header)).toBe(true)
    expect(importHeaderPollMs(header)).toBe(5000)
    expect(importRowsPollMs(header)).toBe(false)
  })

  it('polls call import list when latest eval has in-flight rows', () => {
    const items = [
      {
        id: '1',
        status: 'completed' as const,
        latest_evaluation_status: 'running',
        latest_evaluation_total_rows: 50,
        latest_evaluation_completed_rows: 10,
        latest_evaluation_failed_rows: 5,
        latest_evaluation_bulk_operation: null,
      },
    ] as Parameters<typeof callImportListPollMs>[0]
    expect(callImportListPollMs(items)).toBe(5000)
  })

  it('does not poll idle completed import', () => {
    const header = {
      status: 'completed' as const,
      latest_evaluation_status: 'partial',
      latest_evaluation_total_rows: 10,
      latest_evaluation_completed_rows: 8,
      latest_evaluation_failed_rows: 2,
      latest_evaluation_bulk_operation: null,
    }
    expect(importHeaderPollMs(header)).toBe(false)
    expect(callImportListPollMs([header as never])).toBe(false)
  })
})
