import type { LLMGenerationConfig } from '../../../../config/llmGenerationParams'
import {
  getCallImportRowLabel,
  getObservabilityCallLabel,
  getPlaygroundRecordingLabel,
  getSimulatedResultLabel,
  getCallImportBatchLabel,
} from '../../utils/sourceLabels'

export type StudioSourceKind = 'call_import_row' | 'call_recording' | 'evaluator_result'

export type StudioSource = {
  source_kind: StudioSourceKind
  source_ref: string
  display_label: string
}

export type StudioRecordingRow = {
  id: string
  label: string
  subtitle: string
  kind: 'playground' | 'webhook'
}

export type StudioSimulatedRow = {
  id: string
  result_id?: string | null
  name?: string | null
}

export type StudioRunFormState = {
  metricIds: string[]
  selectedImportRowIds: Set<string>
  selectedRecordingIds: Set<string>
  selectedSimulatedIds: Set<string>
  importRows: Array<{ id: string; conversation_id?: string | null; row_index?: number | null }>
  recordings: StudioRecordingRow[]
  simulatedItems: StudioSimulatedRow[]
  runName: string
  transcriptSource: 'production' | 'diarised'
  llmProvider: string
  llmModel: string
  llmCredentialId: string
  llmConfig: LLMGenerationConfig
}

export function canAdvanceWizardStep(
  step: 1 | 2 | 3,
  state: Pick<StudioRunFormState, 'metricIds' | 'selectedImportRowIds' | 'selectedRecordingIds' | 'selectedSimulatedIds'>,
): boolean {
  const sourceCount =
    state.selectedImportRowIds.size +
    state.selectedRecordingIds.size +
    state.selectedSimulatedIds.size
  if (step === 1) return sourceCount > 0
  if (step === 2) return state.metricIds.length > 0
  return sourceCount > 0 && state.metricIds.length > 0
}

export function buildStudioSources(state: Pick<
  StudioRunFormState,
  | 'selectedImportRowIds'
  | 'selectedRecordingIds'
  | 'selectedSimulatedIds'
  | 'importRows'
  | 'recordings'
  | 'simulatedItems'
>): StudioSource[] {
  const next: StudioSource[] = []

  for (const rowId of state.selectedImportRowIds) {
    const row = state.importRows.find((r) => r.id === rowId)
    next.push({
      source_kind: 'call_import_row',
      source_ref: rowId,
      display_label: row
        ? getCallImportRowLabel(row as Parameters<typeof getCallImportRowLabel>[0])
        : `Import row ${rowId.slice(0, 8)}`,
    })
  }
  for (const callShortId of state.selectedRecordingIds) {
    const rec = state.recordings.find((r) => r.id === callShortId)
    next.push({
      source_kind: 'call_recording',
      source_ref: callShortId,
      display_label: rec?.label ?? callShortId,
    })
  }
  for (const resultId of state.selectedSimulatedIds) {
    const item = state.simulatedItems.find(
      (r) => r.id === resultId || r.result_id === resultId,
    )
    next.push({
      source_kind: 'evaluator_result',
      source_ref: item?.id ?? resultId,
      display_label: item ? getSimulatedResultLabel(item) : resultId.slice(0, 8),
    })
  }
  return next
}

export function buildMetricStudioRunPayload(state: StudioRunFormState): {
  name?: string
  metric_ids: string[]
  sources: Array<{
    source_kind: StudioSourceKind
    source_ref: string
    display_label: string
  }>
  transcript_source: 'production' | 'diarised'
  llm_provider?: string
  llm_model?: string
  llm_credential_id?: string
  llm_config?: LLMGenerationConfig
} {
  const sources = buildStudioSources(state)
  const name = state.runName.trim()
  const base = {
    metric_ids: state.metricIds,
    sources: sources.map(({ source_kind, source_ref, display_label }) => ({
      source_kind,
      source_ref,
      display_label,
    })),
    transcript_source: state.transcriptSource,
    ...(name ? { name } : {}),
  }
  if (state.llmProvider && state.llmModel) {
    return {
      ...base,
      llm_provider: state.llmProvider,
      llm_model: state.llmModel,
      ...(state.llmCredentialId ? { llm_credential_id: state.llmCredentialId } : {}),
      llm_config: state.llmConfig,
    }
  }
  return base
}

/** Client-side filter for import batches already loaded from list API. */
export function filterImportBatches<
  T extends {
    id: string
    original_filename?: string | null
    name?: string | null
    dataset?: string | null
    tags?: Array<{ name?: string | null }>
  },
>(items: T[], query: string): T[] {
  const q = query.trim().toLowerCase()
  if (!q) return items
  return items.filter((imp) => {
    const label = getCallImportBatchLabel(imp).toLowerCase()
    const dataset = (imp.dataset ?? '').toLowerCase()
    const tagText = (imp.tags ?? [])
      .map((t) => (t.name ?? '').toLowerCase())
      .join(' ')
    return (
      label.includes(q) ||
      imp.id.toLowerCase().includes(q) ||
      dataset.includes(q) ||
      tagText.includes(q)
    )
  })
}

export function matchesRecordingSearch(row: StudioRecordingRow, query: string): boolean {
  const q = query.trim().toLowerCase()
  if (!q) return true
  return (
    row.id.toLowerCase().includes(q) ||
    row.label.toLowerCase().includes(q) ||
    row.subtitle.toLowerCase().includes(q) ||
    row.kind.toLowerCase().includes(q)
  )
}

export function matchesSimulatedSearch(item: StudioSimulatedRow, query: string): boolean {
  const q = query.trim().toLowerCase()
  if (!q) return true
  const label = getSimulatedResultLabel(item).toLowerCase()
  const resultId = (item.result_id ?? '').toLowerCase()
  return (
    item.id.toLowerCase().includes(q) ||
    label.includes(q) ||
    (resultId.length > 0 && resultId.includes(q))
  )
}

export function mapPlaygroundRecordings(playgroundRecordings: Array<{ call_short_id: string; display_name?: string | null }>): StudioRecordingRow[] {
  return playgroundRecordings.map((r) => ({
    id: r.call_short_id,
    label: getPlaygroundRecordingLabel(r),
    subtitle: r.call_short_id,
    kind: 'playground' as const,
  }))
}

export function draftParentIdsToDelete(
  draftMetrics: Array<{ id: string; children?: Array<{ id: string }> }>,
  selectedMetricIds: string[],
): string[] {
  const selected = new Set(selectedMetricIds)
  return draftMetrics
    .filter(
      (m) =>
        selected.has(m.id) || (m.children ?? []).some((c) => selected.has(c.id)),
    )
    .map((m) => m.id)
}

export function singleDraftParentIdToPromote(
  draftMetrics: Array<{ id: string }>,
  selectedMetricIds: string[],
): string | null {
  const parents = draftMetrics.filter((m) => selectedMetricIds.includes(m.id))
  if (parents.length !== 1) return null
  return parents[0]!.id
}

export function mapObservabilityCalls(
  observabilityCalls: Array<{
    call_short_id: string
    display_name?: string | null
    agent?: { name?: string | null } | null
    provider_platform?: string | null
  }>,
): StudioRecordingRow[] {
  return observabilityCalls.map((r) => ({
    id: r.call_short_id,
    label: getObservabilityCallLabel(r),
    subtitle: r.call_short_id,
    kind: 'webhook' as const,
  }))
}
