import { describe, expect, it } from 'vitest'
import {
  callImportListPollMs,
  IMPORT_DIARISE_POLL_MS,
  IMPORT_FETCH_POLL_MS,
  IMPORT_PLATFORM_POLL_MS,
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

  it('polls call import list when older eval still active but latest is idle', () => {
    const items = [
      {
        id: '1',
        status: 'completed' as const,
        latest_evaluation_status: 'completed',
        latest_evaluation_total_rows: 10,
        latest_evaluation_completed_rows: 10,
        latest_evaluation_failed_rows: 0,
        latest_evaluation_bulk_operation: null,
        any_evaluation_poll_active: true,
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

  it('does not poll a finished production-transcript run left on processing', () => {
    const header = {
      id: 'prod',
      status: 'processing' as const,
      latest_evaluation_status: 'completed',
      latest_evaluation_transcript_source: 'production',
      latest_evaluation_total_rows: 778,
      latest_evaluation_completed_rows: 778,
      latest_evaluation_failed_rows: 0,
      latest_evaluation_bulk_operation: null,
      any_evaluation_poll_active: false,
    }
    expect(importHeaderPollMs(header)).toBe(false)
    expect(importRowsPollMs(header)).toBe(false)
    expect(callImportListPollMs([header as never])).toBe(false)
  })

  it('polls a processing import that has no evaluation yet', () => {
    const header = {
      id: 'fetch',
      status: 'processing' as const,
      latest_evaluation_status: null,
    }
    expect(importHeaderPollMs(header)).toBe(IMPORT_FETCH_POLL_MS)
    expect(callImportListPollMs([header as never])).toBe(5000)
  })

  it('polls the list when an older eval is active on a processing import', () => {
    const items = [
      {
        id: '1',
        status: 'processing' as const,
        latest_evaluation_status: 'completed',
        latest_evaluation_total_rows: 12,
        latest_evaluation_completed_rows: 12,
        latest_evaluation_failed_rows: 0,
        latest_evaluation_bulk_operation: null,
        any_evaluation_poll_active: true,
      },
    ] as Parameters<typeof callImportListPollMs>[0]
    expect(callImportListPollMs(items)).toBe(5000)
  })

  it('keeps polling detail while platform import or diarise is in flight', () => {
    const finishedEval = {
      status: 'processing' as const,
      latest_evaluation_status: 'completed',
      latest_evaluation_total_rows: 10,
      latest_evaluation_completed_rows: 10,
      latest_evaluation_failed_rows: 0,
      latest_evaluation_bulk_operation: null,
    }
    const platform = {
      ...finishedEval,
      platform_progress: { is_active: true },
    }
    expect(importHeaderPollMs(platform)).toBe(IMPORT_PLATFORM_POLL_MS)
    expect(importRowsPollMs(platform)).toBe(IMPORT_PLATFORM_POLL_MS)

    const diarise = {
      ...finishedEval,
      diarised_pending_rows: 4,
      diarised_running_rows: 1,
    }
    expect(importHeaderPollMs(diarise)).toBe(IMPORT_DIARISE_POLL_MS)
    expect(importRowsPollMs(diarise)).toBe(IMPORT_DIARISE_POLL_MS)
  })
})
