import { describe, expect, it } from 'vitest'
import {
  buildStudioResultTableColumns,
  childrenInStudioGroups,
  studioTableMetricIds,
} from './studioRunTableColumns'
import type { StudioRunResult } from './MetricsStudioScorePanel'

describe('studioRunTableColumns', () => {
  it('collapses categorization children to parent columns', () => {
    const parentId = 'parent-1'
    const childA = 'child-a'
    const childB = 'child-b'
    const standalone = 'metric-bool'

    const run = {
      selected_metric_ids: [childA, childB, standalone],
      selected_metric_groups: {
        [parentId]: [childA, childB],
      },
    }

    expect(childrenInStudioGroups(run)).toEqual(new Set([childA, childB]))

    const ids = studioTableMetricIds(run, {
      [parentId]: 'Intent',
      [standalone]: 'Politeness',
    }, [])

    expect(ids.map((x) => x.metricId)).toEqual([parentId, standalone])
  })

  it('adds rationale column on parent when rationale lives on parent score', () => {
    const parentId = 'parent-1'
    const childA = 'child-a'
    const run = {
      selected_metric_ids: [childA],
      selected_metric_groups: { [parentId]: [childA] },
    }
    const results: StudioRunResult[] = [
      {
        id: 'row-1',
        status: 'completed',
        source_kind: 'call_import_row',
        source_ref: 'ref',
        metric_scores: {
          [parentId]: {
            type: 'category',
            value: 'Billing',
            rationale: 'Caller asked about invoice.',
          },
        },
      },
    ]
    const columns = buildStudioResultTableColumns(
      run,
      { [parentId]: 'Topic' },
      results,
      [{ id: parentId, capture_rationale: true }],
    )
    expect(columns.map((c) => c.columnKey)).toEqual([parentId, `${parentId}:rationale`])
  })
})