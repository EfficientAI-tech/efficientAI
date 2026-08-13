import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate } from 'react-router-dom'
import { format } from 'date-fns'
import { Play, Plus, RefreshCw, Sparkles, Trash2 } from 'lucide-react'
import { apiClient } from '../../lib/api'
import { getApiErrorMessage } from '../../lib/apiErrors'
import Button from '../../components/Button'
import AIProviderModelPicker from '../../components/AIProviderModelPicker'
import MetricPickerPanel from './components/MetricPickerPanel'
import MetricsManagement from './MetricsManagement'
import type { LLMGenerationConfig } from '../../config/llmGenerationParams'
import {
  getCallImportBatchLabel,
  getCallImportRowLabel,
  getCallImportRowSubtitle,
  getObservabilityCallLabel,
  getPlaygroundRecordingLabel,
  getSimulatedResultLabel,
  getSimulatedResultSubtitle,
} from './utils/sourceLabels'

type SourceKind = 'call_import_row' | 'call_recording' | 'evaluator_result'

type StudioSource = {
  source_kind: SourceKind
  source_ref: string
  display_label: string
}

type SourceTab = 'imports' | 'recordings' | 'simulated'

export default function MetricsStudio() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [metricTab, setMetricTab] = useState<'active' | 'drafts'>('active')
  const [sourceTab, setSourceTab] = useState<SourceTab>('imports')
  const [selectedMetricIds, setSelectedMetricIds] = useState<string[]>([])
  const [runName, setRunName] = useState('')
  const [transcriptSource, setTranscriptSource] = useState<'production' | 'diarised'>('diarised')
  const [llmProvider, setLlmProvider] = useState('')
  const [llmModel, setLlmModel] = useState('')
  const [llmConfig, setLlmConfig] = useState<LLMGenerationConfig>({})
  const [showDraftModal, setShowDraftModal] = useState(false)

  const [selectedImportId, setSelectedImportId] = useState<string>('')
  const [selectedImportRowIds, setSelectedImportRowIds] = useState<Set<string>>(new Set())
  const [selectedRecordingIds, setSelectedRecordingIds] = useState<Set<string>>(new Set())
  const [selectedSimulatedIds, setSelectedSimulatedIds] = useState<Set<string>>(new Set())

  const { data: activeMetrics = [] } = useQuery({
    queryKey: ['metrics', 'studio', 'active'],
    queryFn: () => apiClient.listMetrics(undefined, true, { includeDrafts: false }),
  })

  const { data: draftMetrics = [] } = useQuery({
    queryKey: ['metrics', 'studio', 'drafts'],
    queryFn: () => apiClient.listMetrics(undefined, true, { draftsOnly: true }),
  })

  const metricsForPicker = metricTab === 'drafts' ? draftMetrics : activeMetrics

  const { data: importsData } = useQuery({
    queryKey: ['call-imports', 'studio'],
    queryFn: () => apiClient.listCallImports({ page: 1, page_size: 100 }),
  })

  const { data: importDetail } = useQuery({
    queryKey: ['call-import', selectedImportId, 'studio-rows'],
    queryFn: () => apiClient.getCallImport(selectedImportId, { row_limit: 100 }),
    enabled: !!selectedImportId,
  })

  const { data: playgroundRecordings = [] } = useQuery({
    queryKey: ['call-recordings', 'studio'],
    queryFn: () => apiClient.listCallRecordings(0, 100),
  })

  const { data: observabilityCalls = [] } = useQuery({
    queryKey: ['observability-calls', 'studio'],
    queryFn: () => apiClient.listObservabilityCalls(0, 100),
  })

  const { data: simulatedResults } = useQuery({
    queryKey: ['evaluator-results', 'studio-simulated'],
    queryFn: () => apiClient.listEvaluatorResults({ testAgentsOnly: true, limit: 100 }),
  })

  const { data: runsData, isLoading: runsLoading } = useQuery({
    queryKey: ['metric-studio-runs'],
    queryFn: () => apiClient.listMetricStudioRuns(),
    refetchInterval: (query) => {
      const items = query.state.data?.items ?? []
      return items.some((r: any) => r.status === 'running' || r.status === 'pending')
        ? 3000
        : false
    },
  })

  const promoteMutation = useMutation({
    mutationFn: (metricId: string) => apiClient.promoteMetric(metricId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['metrics'] })
    },
  })

  const runMutation = useMutation({
    mutationFn: () =>
      apiClient.createMetricStudioRun({
        name: runName.trim() || undefined,
        metric_ids: selectedMetricIds,
        sources: selectedSources.map(({ source_kind, source_ref, display_label }) => ({
          source_kind,
          source_ref,
          display_label,
        })),
        transcript_source: transcriptSource,
        ...(llmProvider && llmModel
          ? {
              llm_provider: llmProvider,
              llm_model: llmModel,
              llm_config: llmConfig,
            }
          : {}),
      }),
    onSuccess: (run) => {
      queryClient.invalidateQueries({ queryKey: ['metric-studio-runs'] })
      navigate(`/metrics-management/studio/runs/${run.id}`)
    },
  })

  const deleteRunMutation = useMutation({
    mutationFn: (runId: string) => apiClient.deleteMetricStudioRun(runId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['metric-studio-runs'] }),
  })

  const importRows = importDetail?.rows ?? []
  const recordings = useMemo(
    () => [
      ...playgroundRecordings.map((r: any) => ({
        id: r.call_short_id,
        label: getPlaygroundRecordingLabel(r),
        subtitle: r.call_short_id,
        kind: 'playground' as const,
      })),
      ...observabilityCalls.map((r: any) => ({
        id: r.call_short_id,
        label: getObservabilityCallLabel(r),
        subtitle: r.call_short_id,
        kind: 'webhook' as const,
      })),
    ],
    [playgroundRecordings, observabilityCalls],
  )

  const simulatedItems = simulatedResults?.items ?? []

  const selectedSources = useMemo(() => {
    const next: StudioSource[] = []

    for (const rowId of selectedImportRowIds) {
      const row = importRows.find((r: any) => r.id === rowId)
      next.push({
        source_kind: 'call_import_row',
        source_ref: rowId,
        display_label: row ? getCallImportRowLabel(row) : `Import row ${rowId.slice(0, 8)}`,
      })
    }
    for (const callShortId of selectedRecordingIds) {
      const rec = recordings.find((r) => r.id === callShortId)
      next.push({
        source_kind: 'call_recording',
        source_ref: callShortId,
        display_label: rec?.label ?? callShortId,
      })
    }
    for (const resultId of selectedSimulatedIds) {
      const item = simulatedItems.find(
        (r: any) => r.id === resultId || r.result_id === resultId,
      )
      next.push({
        source_kind: 'evaluator_result',
        source_ref: item?.id ?? resultId,
        display_label: item ? getSimulatedResultLabel(item) : resultId.slice(0, 8),
      })
    }
    return next
  }, [
    selectedImportRowIds,
    selectedRecordingIds,
    selectedSimulatedIds,
    importRows,
    recordings,
    simulatedItems,
  ])

  const runError = runMutation.isError
    ? getApiErrorMessage(runMutation.error, 'Failed to start Studio run.')
    : null

  const canRun = selectedMetricIds.length > 0 && selectedSources.length > 0

  return (
    <div className="space-y-8">
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
        <section className="rounded-lg border border-gray-200 bg-white p-4 space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold text-gray-900">Metrics</h2>
            <Button
              variant="ghost"
              size="sm"
              leftIcon={<Plus className="h-4 w-4" />}
              onClick={() => setShowDraftModal(true)}
            >
              Draft
            </Button>
          </div>
          <div className="inline-flex rounded-md border border-gray-200 bg-gray-50 p-0.5 text-xs font-medium">
            {(['active', 'drafts'] as const).map((tab) => (
              <button
                key={tab}
                type="button"
                onClick={() => setMetricTab(tab)}
                className={`px-3 py-1.5 rounded ${
                  metricTab === tab
                    ? 'bg-white text-gray-900 shadow-sm'
                    : 'text-gray-600 hover:text-gray-900'
                }`}
              >
                {tab === 'active' ? 'Active' : 'Drafts'}
              </button>
            ))}
          </div>
          <MetricPickerPanel
            metrics={metricsForPicker}
            selectedMetricIds={selectedMetricIds}
            onChange={setSelectedMetricIds}
            emptyMessage={
              metricTab === 'drafts'
                ? 'No draft metrics yet. Create one to experiment.'
                : 'No active metrics found.'
            }
          />
          {metricTab === 'drafts' && draftMetrics.length > 0 && (
            <div className="space-y-2 pt-2 border-t border-gray-100">
              {draftMetrics.map((m: any) => (
                <div key={m.id} className="flex items-center justify-between text-xs">
                  <span className="text-gray-700 truncate">{m.name}</span>
                  <button
                    type="button"
                    className="text-primary-700 hover:text-primary-900 font-medium"
                    onClick={() => promoteMutation.mutate(m.id)}
                    disabled={promoteMutation.isPending}
                  >
                    Promote
                  </button>
                </div>
              ))}
            </div>
          )}
        </section>

        <section className="rounded-lg border border-gray-200 bg-white p-4 space-y-4 xl:col-span-1">
          <h2 className="text-sm font-semibold text-gray-900">Call sources</h2>
          <div className="inline-flex rounded-md border border-gray-200 bg-gray-50 p-0.5 text-xs font-medium w-full">
            {(
              [
                { id: 'imports', label: 'Call Imports' },
                { id: 'recordings', label: 'Recordings' },
                { id: 'simulated', label: 'Simulated' },
              ] as const
            ).map((tab) => (
              <button
                key={tab.id}
                type="button"
                onClick={() => setSourceTab(tab.id)}
                className={`flex-1 px-2 py-1.5 rounded ${
                  sourceTab === tab.id
                    ? 'bg-white text-gray-900 shadow-sm'
                    : 'text-gray-600 hover:text-gray-900'
                }`}
              >
                {tab.label}
              </button>
            ))}
          </div>

          {sourceTab === 'imports' && (
            <div className="space-y-3">
              <select
                value={selectedImportId}
                onChange={(e) => {
                  setSelectedImportId(e.target.value)
                  setSelectedImportRowIds(new Set())
                }}
                className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
              >
                <option value="">Select import batch…</option>
                {(importsData?.items ?? []).map((imp: any) => (
                  <option key={imp.id} value={imp.id}>
                    {getCallImportBatchLabel(imp)}
                  </option>
                ))}
              </select>
              <div className="max-h-48 overflow-y-auto space-y-1 border border-gray-100 rounded p-2">
                {importRows.map((row: any) => (
                  <label key={row.id} className="flex items-start gap-2 text-sm py-1">
                    <input
                      type="checkbox"
                      className="mt-1"
                      checked={selectedImportRowIds.has(row.id)}
                      onChange={() => {
                        const next = new Set(selectedImportRowIds)
                        if (next.has(row.id)) next.delete(row.id)
                        else next.add(row.id)
                        setSelectedImportRowIds(next)
                      }}
                    />
                    <span className="min-w-0">
                      <span className="block truncate font-medium text-gray-900">
                        {getCallImportRowLabel(row)}
                      </span>
                      <span className="block text-xs text-gray-500 truncate">
                        {getCallImportRowSubtitle(row)}
                      </span>
                    </span>
                  </label>
                ))}
              </div>
            </div>
          )}

          {sourceTab === 'recordings' && (
            <div className="space-y-3">
              <div className="max-h-48 overflow-y-auto space-y-1 border border-gray-100 rounded p-2">
                {recordings.map((rec) => (
                  <label key={rec.id} className="flex items-start gap-2 text-sm py-1">
                    <input
                      type="checkbox"
                      className="mt-1"
                      checked={selectedRecordingIds.has(rec.id)}
                      onChange={() => {
                        const next = new Set(selectedRecordingIds)
                        if (next.has(rec.id)) next.delete(rec.id)
                        else next.add(rec.id)
                        setSelectedRecordingIds(next)
                      }}
                    />
                    <span className="min-w-0">
                      <span className="block truncate font-medium text-gray-900">{rec.label}</span>
                      <span className="block text-xs text-gray-500 truncate">
                        {rec.subtitle} · {rec.kind}
                      </span>
                    </span>
                  </label>
                ))}
              </div>
            </div>
          )}

          {sourceTab === 'simulated' && (
            <div className="space-y-3">
              <div className="max-h-48 overflow-y-auto space-y-1 border border-gray-100 rounded p-2">
                {simulatedItems.map((item: any) => (
                  <label key={item.id} className="flex items-start gap-2 text-sm py-1">
                    <input
                      type="checkbox"
                      className="mt-1"
                      checked={selectedSimulatedIds.has(item.id)}
                      onChange={() => {
                        const next = new Set(selectedSimulatedIds)
                        if (next.has(item.id)) next.delete(item.id)
                        else next.add(item.id)
                        setSelectedSimulatedIds(next)
                      }}
                    />
                    <span className="min-w-0">
                      <span className="block truncate font-medium text-gray-900">
                        {getSimulatedResultLabel(item)}
                      </span>
                      {getSimulatedResultSubtitle(item) && (
                        <span className="block text-xs text-gray-500 truncate">
                          {getSimulatedResultSubtitle(item)}
                        </span>
                      )}
                    </span>
                  </label>
                ))}
              </div>
            </div>
          )}

          {selectedSources.length > 0 && (
            <div className="flex flex-wrap gap-2 pt-2">
              {selectedSources.map((src) => (
                <span
                  key={`${src.source_kind}:${src.source_ref}`}
                  className="inline-flex items-center gap-1 px-2 py-1 rounded-full bg-gray-100 text-xs text-gray-700"
                >
                  {src.display_label}
                  <button
                    type="button"
                    className="text-gray-500 hover:text-gray-800"
                    onClick={() => {
                      if (src.source_kind === 'call_import_row') {
                        setSelectedImportRowIds((prev) => {
                          const next = new Set(prev)
                          next.delete(src.source_ref)
                          return next
                        })
                      } else if (src.source_kind === 'call_recording') {
                        setSelectedRecordingIds((prev) => {
                          const next = new Set(prev)
                          next.delete(src.source_ref)
                          return next
                        })
                      } else {
                        setSelectedSimulatedIds((prev) => {
                          const next = new Set(prev)
                          next.delete(src.source_ref)
                          return next
                        })
                      }
                    }}
                  >
                    ×
                  </button>
                </span>
              ))}
            </div>
          )}
        </section>

        <section className="rounded-lg border border-gray-200 bg-white p-4 space-y-4">
          <h2 className="text-sm font-semibold text-gray-900">Run configuration</h2>
          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1">Run name</label>
            <input
              value={runName}
              onChange={(e) => setRunName(e.target.value)}
              className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
              placeholder="Optional label"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1">Transcript source</label>
            <select
              value={transcriptSource}
              onChange={(e) =>
                setTranscriptSource(e.target.value as 'production' | 'diarised')
              }
              className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
            >
              <option value="diarised">Diarised</option>
              <option value="production">Production (CSV)</option>
            </select>
          </div>
          <AIProviderModelPicker
            provider={llmProvider}
            model={llmModel}
            llm_config={llmConfig}
            onProviderChange={setLlmProvider}
            onModelChange={setLlmModel}
            onLLMConfigChange={(next) => setLlmConfig(next ?? {})}
          />
          {runError && <p className="text-sm text-red-600">{runError}</p>}
          {!canRun && (
            <p className="text-xs text-gray-500">
              Select at least one metric and one call source to run.
            </p>
          )}
          <Button
            variant="primary"
            className="w-full"
            leftIcon={<Play className="h-4 w-4" />}
            disabled={!canRun || runMutation.isPending}
            onClick={() => runMutation.mutate()}
          >
            {runMutation.isPending ? 'Starting…' : 'Run evaluation'}
          </Button>
        </section>
      </div>

      <section className="rounded-lg border border-gray-200 bg-white">
        <div className="px-4 py-3 border-b border-gray-200 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-gray-900 flex items-center gap-2">
            <Sparkles className="h-4 w-4 text-amber-500" />
            Recent Studio runs
          </h2>
          <button
            type="button"
            onClick={() => queryClient.invalidateQueries({ queryKey: ['metric-studio-runs'] })}
            className="text-gray-500 hover:text-gray-800"
          >
            <RefreshCw className="h-4 w-4" />
          </button>
        </div>
        {runsLoading ? (
          <div className="p-8 text-center text-sm text-gray-500">Loading runs…</div>
        ) : (runsData?.items ?? []).length === 0 ? (
          <div className="p-8 text-center text-sm text-gray-500">
            No Studio runs yet. Configure metrics and sources above, then run an evaluation.
          </div>
        ) : (
          <div className="divide-y divide-gray-100">
            {(runsData?.items ?? []).map((run: any) => (
              <div
                key={run.id}
                className="px-4 py-3 flex items-center justify-between gap-4 hover:bg-gray-50"
              >
                <div>
                  <Link
                    to={`/metrics-management/studio/runs/${run.id}`}
                    className="text-sm font-medium text-gray-900 hover:text-primary-800"
                  >
                    {run.name || `Run ${run.id.slice(0, 8)}`}
                  </Link>
                  <p className="text-xs text-gray-500 mt-0.5">
                    {format(new Date(run.created_at), 'MMM d, yyyy HH:mm')} ·{' '}
                    {run.completed_items}/{run.total_items} completed · {run.status}
                  </p>
                </div>
                <button
                  type="button"
                  className="text-gray-400 hover:text-red-600"
                  onClick={() => deleteRunMutation.mutate(run.id)}
                  aria-label="Delete run"
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              </div>
            ))}
          </div>
        )}
      </section>

      <MetricsManagement
        createModalOnly
        draftMode
        createModalOpen={showDraftModal}
        onCreateModalClose={() => setShowDraftModal(false)}
        onMetricCreated={(metric: any) => {
          const childIds = (metric.children ?? []).map((c: any) => c.id)
          const ids = [metric.id, ...childIds]
          setSelectedMetricIds((prev) => Array.from(new Set([...prev, ...ids])))
          setMetricTab('drafts')
          setShowDraftModal(false)
        }}
      />
    </div>
  )
}
