import { describe, expect, it } from 'vitest'
import {
  buildMetricStudioRunPayload,
  buildStudioSources,
  canAdvanceWizardStep,
  draftParentIdsToDelete,
  filterImportBatches,
  matchesRecordingSearch,
  matchesSimulatedSearch,
  singleDraftParentIdToPromote,
  type StudioRunFormState,
} from './studioRunSelection'

const baseState: StudioRunFormState = {
  metricIds: [],
  selectedImportRowIds: new Set(),
  selectedRecordingIds: new Set(),
  selectedSimulatedIds: new Set(),
  importRows: [
    { id: 'row-aaa-111', conversation_id: 'conv-001', row_index: 0 },
    { id: 'row-bbb-222', conversation_id: 'other', row_index: 1 },
  ],
  recordings: [
    { id: 'call-xyz', label: 'Playground test', subtitle: 'call-xyz', kind: 'playground' },
  ],
  simulatedItems: [
    { id: 'sim-uuid', result_id: 'res-42', name: 'Scenario A' },
  ],
  runName: '',
  transcriptSource: 'diarised',
  llmProvider: '',
  llmModel: '',
  llmCredentialId: '',
  llmConfig: {},
}

describe('canAdvanceWizardStep', () => {
  it('blocks step 1 without sources', () => {
    expect(canAdvanceWizardStep(1, baseState)).toBe(false)
  })

  it('allows step 1 with any source type', () => {
    expect(
      canAdvanceWizardStep(1, {
        ...baseState,
        selectedRecordingIds: new Set(['call-xyz']),
      }),
    ).toBe(true)
  })

  it('blocks step 2 without metrics', () => {
    expect(
      canAdvanceWizardStep(2, {
        ...baseState,
        selectedImportRowIds: new Set(['row-aaa-111']),
      }),
    ).toBe(false)
  })
})

describe('buildStudioSources', () => {
  it('maps import rows, recordings, and simulated results', () => {
    const sources = buildStudioSources({
      ...baseState,
      selectedImportRowIds: new Set(['row-aaa-111']),
      selectedRecordingIds: new Set(['call-xyz']),
      selectedSimulatedIds: new Set(['sim-uuid']),
    })
    expect(sources).toHaveLength(3)
    expect(sources[0]).toMatchObject({
      source_kind: 'call_import_row',
      source_ref: 'row-aaa-111',
    })
    expect(sources[1]).toMatchObject({
      source_kind: 'call_recording',
      source_ref: 'call-xyz',
      display_label: 'Playground test',
    })
    expect(sources[2]).toMatchObject({
      source_kind: 'evaluator_result',
      source_ref: 'sim-uuid',
      display_label: 'Scenario A',
    })
  })
})

describe('buildMetricStudioRunPayload', () => {
  it('cannot produce a valid run with empty metrics and sources', () => {
    const payload = buildMetricStudioRunPayload(baseState)
    expect(payload.metric_ids).toHaveLength(0)
    expect(payload.sources).toHaveLength(0)
  })

  it('omits LLM fields when provider or model unset', () => {
    const payload = buildMetricStudioRunPayload({
      ...baseState,
      metricIds: ['m1'],
      selectedImportRowIds: new Set(['row-aaa-111']),
      runName: '  test run  ',
    })
    expect(payload.name).toBe('test run')
    expect(payload.transcript_source).toBe('diarised')
    expect(payload).not.toHaveProperty('llm_provider')
    expect(payload).not.toHaveProperty('llm_credential_id')
  })

  it('includes LLM fields and credential id when set', () => {
    const payload = buildMetricStudioRunPayload({
      ...baseState,
      metricIds: ['m1'],
      selectedRecordingIds: new Set(['call-xyz']),
      llmProvider: 'openai',
      llmModel: 'gpt-4o',
      llmCredentialId: 'cred-99',
      llmConfig: { temperature: 0.2 },
    })
    expect(payload).toMatchObject({
      llm_provider: 'openai',
      llm_model: 'gpt-4o',
      llm_credential_id: 'cred-99',
      llm_config: { temperature: 0.2 },
    })
  })
})

describe('draftParentIdsToDelete', () => {
  it('maps selected parent or child to parent delete ids', () => {
    const drafts = [
      { id: 'p1', children: [{ id: 'c1' }] },
      { id: 'p2', children: [] },
    ]
    expect(draftParentIdsToDelete(drafts, ['c1'])).toEqual(['p1'])
    expect(draftParentIdsToDelete(drafts, ['p2', 'p1'])).toEqual(['p1', 'p2'])
  })
})

describe('singleDraftParentIdToPromote', () => {
  it('allows promote only when exactly one parent draft is selected', () => {
    const drafts = [{ id: 'p1' }, { id: 'p2' }]
    expect(singleDraftParentIdToPromote(drafts, ['p1'])).toBe('p1')
    expect(singleDraftParentIdToPromote(drafts, ['p1', 'p2'])).toBeNull()
    expect(singleDraftParentIdToPromote(drafts, [])).toBeNull()
  })
})

describe('search helpers', () => {
  it('filters import batches by name or id', () => {
    const items = [
      { id: 'imp-1', original_filename: 'sales_q1.csv', name: null },
      { id: 'imp-2', original_filename: null, name: 'Support calls' },
    ]
    expect(filterImportBatches(items, 'sales')).toHaveLength(1)
    expect(filterImportBatches(items, 'imp-2')).toHaveLength(1)
  })

  it('filters import batches by dataset or tag name', () => {
    const items = [
      {
        id: 'imp-1',
        original_filename: 'file.csv',
        dataset: 'prod_support',
        tags: [{ name: 'escalation' }],
      },
    ]
    expect(filterImportBatches(items, 'prod_support')).toHaveLength(1)
    expect(filterImportBatches(items, 'escalation')).toHaveLength(1)
  })

  it('matches recording search by call_short_id and label', () => {
    const row = baseState.recordings[0]!
    expect(matchesRecordingSearch(row, 'call-xyz')).toBe(true)
    expect(matchesRecordingSearch(row, 'playground')).toBe(true)
    expect(matchesRecordingSearch(row, 'nope')).toBe(false)
  })

  it('matches simulated search by id and name', () => {
    const item = baseState.simulatedItems[0]!
    expect(matchesSimulatedSearch(item, 'sim-uuid')).toBe(true)
    expect(matchesSimulatedSearch(item, 'scenario')).toBe(true)
    expect(matchesSimulatedSearch(item, 'res-42')).toBe(true)
  })
})
