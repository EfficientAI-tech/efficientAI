import { useEffect, useMemo, useState } from 'react'
import { createPortal } from 'react-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, Play, X } from 'lucide-react'
import { apiClient } from '../../../../lib/api'
import { getApiErrorMessage } from '../../../../lib/apiErrors'
import { itemsOf } from '../../../../lib/safeData'
import { useWorkspaceStore } from '../../../../store/workspaceStore'
import type { LLMGenerationConfig } from '../../../../config/llmGenerationParams'
import Button from '../../../../components/Button'
import {
  buildMetricStudioRunPayload,
  callImportSourceFormatForKind,
  canAdvanceWizardStep,
  draftParentIdsToDelete,
  mapObservabilityCalls,
  mapPlaygroundRecordings,
  singleDraftParentIdToPromote,
  type StudioImportKindTab,
} from './studioRunSelection'
import StudioWizardCallsStep from './StudioWizardCallsStep'
import StudioWizardLlmStep from './StudioWizardLlmStep'
import StudioWizardMetricsStep from './StudioWizardMetricsStep'
import MetricsManagement from '../../MetricsManagement'
import ConfirmModal from '../../../../components/ConfirmModal'

const WIZARD_STEPS = [
  { id: 1 as const, label: 'Calls' },
  { id: 2 as const, label: 'Metrics' },
  { id: 3 as const, label: 'LLM & run' },
]

type StudioRunWizardProps = {
  open: boolean
  onClose: () => void
  onRunCreated: (runId: string) => void
}

type SourceTab = 'imports' | 'recordings' | 'simulated'

function resetWizardState() {
  return {
    step: 1 as 1 | 2 | 3,
    sourceTab: 'imports' as SourceTab,
    metricTab: 'active' as 'active' | 'drafts',
    selectedMetricIds: [] as string[],
    runName: '',
    transcriptSource: 'diarised' as 'production' | 'diarised',
    llmProvider: '',
    llmModel: '',
    llmCredentialId: '',
    llmConfig: {} as LLMGenerationConfig,
    selectedImportId: '',
    selectedImportRowIds: new Set<string>(),
    selectedRecordingIds: new Set<string>(),
    selectedSimulatedIds: new Set<string>(),
    importKindTab: 'datasets' as StudioImportKindTab,
    importDatasetFilter: '',
    importTagFilter: [] as string[],
    importBatchSearch: '',
    importRowSearch: '',
    recordingSearch: '',
    simulatedSearch: '',
  }
}

export default function StudioRunWizard({
  open,
  onClose,
  onRunCreated,
}: StudioRunWizardProps) {
  const queryClient = useQueryClient()
  const activeWorkspaceId = useWorkspaceStore((s) => s.activeWorkspaceId)

  const [state, setState] = useState(resetWizardState)
  const [showDraftModal, setShowDraftModal] = useState(false)
  const [draftDeleteTarget, setDraftDeleteTarget] = useState<{
    parentIds: string[]
    label: string
  } | null>(null)

  useEffect(() => {
    if (!open) setState(resetWizardState())
  }, [open])

  const { data: activeMetrics = [] } = useQuery({
    queryKey: ['metrics', 'studio', 'active', activeWorkspaceId],
    queryFn: () =>
      apiClient.listMetrics(undefined, true, {
        includeDrafts: false,
        enabledOnly: true,
      }),
    enabled: open,
  })

  const { data: draftMetrics = [] } = useQuery({
    queryKey: ['metrics', 'studio', 'drafts', activeWorkspaceId],
    queryFn: () => apiClient.listMetrics(undefined, true, { draftsOnly: true }),
    enabled: open,
  })

  const metricsForPicker = state.metricTab === 'drafts' ? draftMetrics : activeMetrics

  const { data: importDatasets = [] } = useQuery({
    queryKey: ['call-import-datasets', activeWorkspaceId],
    queryFn: () => apiClient.listCallImportDatasets(),
    enabled: open,
  })

  const { data: importTags = [] } = useQuery({
    queryKey: ['call-import-tags', activeWorkspaceId],
    queryFn: () => apiClient.listCallImportTags(),
    enabled: open,
  })

  const { data: importsData } = useQuery({
    queryKey: [
      'call-imports',
      'studio',
      activeWorkspaceId,
      state.importKindTab,
      state.importDatasetFilter,
      state.importTagFilter,
    ],
    queryFn: () =>
      apiClient.listCallImports({
        page: 1,
        page_size: 100,
        source_format: callImportSourceFormatForKind(state.importKindTab),
        ...(state.importDatasetFilter ? { dataset: state.importDatasetFilter } : {}),
        ...(state.importTagFilter.length > 0 ? { tag_id: state.importTagFilter } : {}),
      }),
    enabled: open,
  })

  const rowSearchQ = state.importRowSearch.trim() || undefined

  const { data: importDetail, isLoading: importRowsLoading } = useQuery({
    queryKey: ['call-import', state.selectedImportId, 'studio-wizard-rows', rowSearchQ],
    queryFn: () =>
      apiClient.getCallImport(state.selectedImportId, {
        row_limit: 500,
        q: rowSearchQ,
      }),
    enabled: open && !!state.selectedImportId,
  })

  const { data: playgroundRecordings = [] } = useQuery({
    queryKey: ['call-recordings', 'studio'],
    queryFn: () => apiClient.listCallRecordings(0, 100),
    enabled: open,
  })

  const { data: observabilityCalls = [] } = useQuery({
    queryKey: ['observability-calls', 'studio'],
    queryFn: () => apiClient.listObservabilityCalls(0, 100),
    enabled: open,
  })

  const { data: simulatedResults } = useQuery({
    queryKey: ['evaluator-results', 'studio-simulated'],
    queryFn: () => apiClient.listEvaluatorResults({ testAgentsOnly: true, limit: 100 }),
    enabled: open,
  })

  const importRows = importDetail?.rows ?? []
  const recordings = useMemo(
    () => [
      ...mapPlaygroundRecordings(playgroundRecordings),
      ...mapObservabilityCalls(observabilityCalls),
    ],
    [playgroundRecordings, observabilityCalls],
  )

  const simulatedItems = itemsOf<{
    id: string
    result_id?: string | null
    name?: string | null
  }>(simulatedResults)

  const formState = useMemo(
    () => ({
      metricIds: state.selectedMetricIds,
      selectedImportRowIds: state.selectedImportRowIds,
      selectedRecordingIds: state.selectedRecordingIds,
      selectedSimulatedIds: state.selectedSimulatedIds,
      importRows,
      recordings,
      simulatedItems,
      runName: state.runName,
      transcriptSource: state.transcriptSource,
      llmProvider: state.llmProvider,
      llmModel: state.llmModel,
      llmCredentialId: state.llmCredentialId,
      llmConfig: state.llmConfig,
    }),
    [
      state.selectedMetricIds,
      state.selectedImportRowIds,
      state.selectedRecordingIds,
      state.selectedSimulatedIds,
      state.runName,
      state.transcriptSource,
      state.llmProvider,
      state.llmModel,
      state.llmCredentialId,
      state.llmConfig,
      importRows,
      recordings,
      simulatedItems,
    ],
  )

  const promoteMutation = useMutation({
    mutationFn: (metricId: string) => apiClient.promoteMetric(metricId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['metrics'] }),
  })

  const deleteDraftMutation = useMutation({
    mutationFn: async (parentIds: string[]) => {
      for (const id of parentIds) {
        await apiClient.deleteMetric(id)
      }
    },
    onSuccess: (_data, parentIds) => {
      queryClient.invalidateQueries({ queryKey: ['metrics'] })
      const remove = new Set<string>()
      for (const parentId of parentIds) {
        remove.add(parentId)
        const draft = draftMetrics.find((m: { id: string }) => m.id === parentId)
        for (const child of draft?.children ?? []) {
          remove.add(child.id)
        }
      }
      setState((s) => ({
        ...s,
        selectedMetricIds: s.selectedMetricIds.filter((id) => !remove.has(id)),
      }))
      setDraftDeleteTarget(null)
    },
  })

  const selectedDraftParentIds = draftParentIdsToDelete(
    draftMetrics,
    state.selectedMetricIds,
  )
  const promoteDraftId = singleDraftParentIdToPromote(draftMetrics, state.selectedMetricIds)

  const runMutation = useMutation({
    mutationFn: () => apiClient.createMetricStudioRun(buildMetricStudioRunPayload(formState)),
    onSuccess: (run) => {
      queryClient.invalidateQueries({ queryKey: ['metric-studio-runs'] })
      onRunCreated(run.id)
      onClose()
    },
  })

  const runError = runMutation.isError
    ? getApiErrorMessage(runMutation.error, 'Failed to start Studio run.')
  : null

  const canNext = canAdvanceWizardStep(state.step, formState)
  const isLastStep = state.step === 3

  const goStep = (step: 1 | 2 | 3) => setState((s) => ({ ...s, step }))

  const wizardModal = open
    ? createPortal(
    <div
      className="fixed inset-0 z-[9999] flex items-center justify-center p-4 bg-black/40"
      role="dialog"
      aria-modal="true"
      aria-labelledby="studio-run-wizard-title"
    >
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-6xl h-[90vh] overflow-hidden flex flex-col">
        <div className="px-6 py-4 border-b border-gray-200 flex-shrink-0">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <h2 id="studio-run-wizard-title" className="text-lg font-semibold text-gray-900">
                New Studio evaluation
              </h2>
              <p className="text-xs text-gray-500 mt-0.5">
                Step {state.step} of {WIZARD_STEPS.length}:{' '}
                {WIZARD_STEPS[state.step - 1]?.label}
              </p>
            </div>
            <button
              type="button"
              onClick={onClose}
              disabled={runMutation.isPending}
              className="text-gray-400 hover:text-gray-600 disabled:opacity-50 shrink-0"
              aria-label="Close"
            >
              <X className="h-5 w-5" />
            </button>
          </div>
          <ol className="mt-4 flex items-stretch gap-1.5">
            {WIZARD_STEPS.map((step) => {
              const reachable = step.id <= state.step
              const active = state.step === step.id
              const done = state.step > step.id
              return (
                <li key={step.id} className="flex-1 min-w-0">
                  <button
                    type="button"
                    onClick={() => {
                      if (reachable && step.id < state.step) goStep(step.id)
                    }}
                    disabled={!reachable || step.id > state.step}
                    className={`w-full rounded-md px-2 py-2 text-left transition-colors disabled:cursor-default ${
                      active
                        ? 'bg-primary-50 text-primary-800 ring-1 ring-primary-200'
                        : done
                          ? 'text-green-800 hover:bg-green-50'
                          : 'text-gray-400'
                    }`}
                  >
                    <span className="flex items-center gap-1.5">
                      <span
                        className={`inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[10px] font-semibold ${
                          done
                            ? 'bg-green-100 text-green-700'
                            : active
                              ? 'bg-primary-100 text-primary-700'
                              : 'bg-gray-100 text-gray-500'
                        }`}
                      >
                        {done ? <Check className="h-3 w-3" aria-hidden /> : step.id}
                      </span>
                      <span className="truncate text-[11px] font-medium leading-tight">{step.label}</span>
                    </span>
                  </button>
                </li>
              )
            })}
          </ol>
        </div>

        <div className="flex-1 min-h-0 px-6 py-4 overflow-hidden flex flex-col">
          {state.step === 1 && (
            <StudioWizardCallsStep
              sourceTab={state.sourceTab}
              onSourceTabChange={(sourceTab) => setState((s) => ({ ...s, sourceTab }))}
              importsData={importsData}
              importKindTab={state.importKindTab}
              onImportKindTabChange={(importKindTab) =>
                setState((s) => ({
                  ...s,
                  importKindTab,
                  selectedImportId: '',
                  selectedImportRowIds: new Set(),
                }))
              }
              importDatasets={importDatasets}
              importTags={importTags}
              importDatasetFilter={state.importDatasetFilter}
              onImportDatasetFilterChange={(importDatasetFilter) =>
                setState((s) => ({
                  ...s,
                  importDatasetFilter,
                  selectedImportId: '',
                  selectedImportRowIds: new Set(),
                }))
              }
              importTagFilter={state.importTagFilter}
              onImportTagFilterChange={(importTagFilter) =>
                setState((s) => ({
                  ...s,
                  importTagFilter,
                  selectedImportId: '',
                  selectedImportRowIds: new Set(),
                }))
              }
              importBatchSearch={state.importBatchSearch}
              onImportBatchSearchChange={(importBatchSearch) =>
                setState((s) => ({ ...s, importBatchSearch }))
              }
              selectedImportId={state.selectedImportId}
              onSelectedImportIdChange={(selectedImportId) =>
                setState((s) => ({ ...s, selectedImportId, selectedImportRowIds: new Set() }))
              }
              importRowSearch={state.importRowSearch}
              onImportRowSearchChange={(importRowSearch) =>
                setState((s) => ({ ...s, importRowSearch }))
              }
              importRows={importRows}
              importRowsLoading={importRowsLoading}
              filteredTotalRows={importDetail?.filtered_total_rows ?? undefined}
              selectedImportRowIds={state.selectedImportRowIds}
              onSelectedImportRowIdsChange={(selectedImportRowIds) =>
                setState((s) => ({ ...s, selectedImportRowIds }))
              }
              recordings={recordings}
              recordingSearch={state.recordingSearch}
              onRecordingSearchChange={(recordingSearch) =>
                setState((s) => ({ ...s, recordingSearch }))
              }
              selectedRecordingIds={state.selectedRecordingIds}
              onSelectedRecordingIdsChange={(selectedRecordingIds) =>
                setState((s) => ({ ...s, selectedRecordingIds }))
              }
              simulatedItems={simulatedItems}
              simulatedSearch={state.simulatedSearch}
              onSimulatedSearchChange={(simulatedSearch) =>
                setState((s) => ({ ...s, simulatedSearch }))
              }
              selectedSimulatedIds={state.selectedSimulatedIds}
              onSelectedSimulatedIdsChange={(selectedSimulatedIds) =>
                setState((s) => ({ ...s, selectedSimulatedIds }))
              }
            />
          )}
          {state.step === 2 && (
            <StudioWizardMetricsStep
              metricTab={state.metricTab}
              onMetricTabChange={(metricTab) => setState((s) => ({ ...s, metricTab }))}
              metricsForPicker={metricsForPicker}
              selectedMetricIds={state.selectedMetricIds}
              onSelectedMetricIdsChange={(selectedMetricIds) =>
                setState((s) => ({ ...s, selectedMetricIds }))
              }
              canPromoteSelectedDraft={!!promoteDraftId}
              onPromoteSelectedDraft={() => {
                if (promoteDraftId) promoteMutation.mutate(promoteDraftId)
              }}
              promotePending={promoteMutation.isPending}
              canDeleteSelectedDrafts={selectedDraftParentIds.length > 0}
              onDeleteSelectedDrafts={() => {
                const names = draftMetrics
                  .filter((m: { id: string }) => selectedDraftParentIds.includes(m.id))
                  .map((m: { name: string }) => m.name)
                const label =
                  names.length === 1
                    ? `“${names[0]}”`
                    : `${names.length} draft metrics`
                setDraftDeleteTarget({ parentIds: selectedDraftParentIds, label })
              }}
              deletePending={deleteDraftMutation.isPending}
              onCreateDraft={() => setShowDraftModal(true)}
            />
          )}
          {state.step === 3 && (
            <StudioWizardLlmStep
              runName={state.runName}
              onRunNameChange={(runName) => setState((s) => ({ ...s, runName }))}
              transcriptSource={state.transcriptSource}
              onTranscriptSourceChange={(transcriptSource) =>
                setState((s) => ({ ...s, transcriptSource }))
              }
              llmProvider={state.llmProvider}
              llmModel={state.llmModel}
              llmCredentialId={state.llmCredentialId}
              llmConfig={state.llmConfig}
              onProviderChange={(llmProvider) => setState((s) => ({ ...s, llmProvider }))}
              onModelChange={(llmModel) => setState((s) => ({ ...s, llmModel }))}
              onCredentialIdChange={(llmCredentialId) =>
                setState((s) => ({ ...s, llmCredentialId }))
              }
              onLLMConfigChange={(llmConfig) =>
                setState((s) => ({ ...s, llmConfig: llmConfig ?? {} }))
              }
            />
          )}
        </div>

        <div className="px-6 py-4 border-t border-gray-200 flex items-center justify-between gap-4 flex-shrink-0">
          <p className="text-sm text-red-600 min-h-[1.25rem]">{runError ?? ''}</p>
          <div className="flex items-center gap-2">
            <Button
              variant="ghost"
              disabled={state.step === 1 || runMutation.isPending}
              onClick={() => goStep((state.step - 1) as 1 | 2 | 3)}
            >
              Back
            </Button>
            {!isLastStep ? (
              <Button variant="primary" disabled={!canNext} onClick={() => goStep((state.step + 1) as 2 | 3)}>
                Next
              </Button>
            ) : (
              <Button
                variant="primary"
                leftIcon={<Play className="h-4 w-4" />}
                disabled={!canNext || runMutation.isPending}
                onClick={() => runMutation.mutate()}
              >
                {runMutation.isPending ? 'Starting…' : 'Run evaluation'}
              </Button>
            )}
          </div>
        </div>
      </div>
    </div>,
    document.body,
  )
    : null

  return (
    <>
      {wizardModal}
      <ConfirmModal
        title="Delete draft metric?"
        description={
          draftDeleteTarget
            ? `${draftDeleteTarget.label} will be removed permanently. This cannot be undone.`
            : undefined
        }
        confirmLabel="Delete"
        isOpen={!!draftDeleteTarget}
        isLoading={deleteDraftMutation.isPending}
        overlayZIndexClass="z-[10060]"
        onCancel={() => setDraftDeleteTarget(null)}
        onConfirm={() => {
          if (draftDeleteTarget) deleteDraftMutation.mutate(draftDeleteTarget.parentIds)
        }}
      />
      <MetricsManagement
        createModalOnly
        draftMode
        createModalOpen={showDraftModal}
        createModalZIndexClass="z-[10050]"
        onCreateModalClose={() => setShowDraftModal(false)}
        onMetricCreated={(metric: any) => {
          const childIds = (metric.children ?? []).map((c: any) => c.id)
          const ids = [metric.id, ...childIds]
          setState((s) => ({
            ...s,
            selectedMetricIds: Array.from(new Set([...s.selectedMetricIds, ...ids])),
            metricTab: 'drafts',
          }))
          setShowDraftModal(false)
        }}
      />
    </>
  )
}
