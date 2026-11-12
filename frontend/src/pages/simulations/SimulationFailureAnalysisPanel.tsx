import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, Copy, Loader2, Sparkles, Square } from 'lucide-react'

import AIProviderModelPicker from '../../components/AIProviderModelPicker'
import Button from '../../components/Button'
import ClusterHierarchyExplorer from '../../components/metricClusters/ClusterHierarchyExplorer'
import ClusterReportVisualizationTab from '../../components/metricClusters/ClusterReportVisualizationTab'
import type { LLMGenerationConfig } from '../../config/llmGenerationParams'
import { apiClient } from '../../lib/api'
import { getApiErrorDetail } from '../../lib/authSession'
import PromptLineDiff, { type PromptDiffView } from '../callImports/components/PromptLineDiff'
import PromptSuggestionList from '../callImports/components/PromptSuggestionList'
import type { MetricClusterEvidence, SimulationFailureAnalysis } from '../../types/api'

type ClusterView = 'overview' | 'clusters'

function isAnalysisRunning(data?: SimulationFailureAnalysis) {
  return (
    data?.metric_clusters?.status === 'running' || data?.prompt_improvements?.status === 'running'
  )
}

/** Clusters trials that missed a success rule and suggests production-prompt fixes. */
export default function SimulationFailureAnalysisPanel({
  runId,
  runActive,
  onToast,
}: {
  runId: string
  runActive: boolean
  onToast: (message: string, kind?: 'success' | 'error') => void
}) {
  const queryClient = useQueryClient()
  const [view, setView] = useState<ClusterView>('overview')
  const [diffView, setDiffView] = useState<PromptDiffView>('split')
  const [showComposed, setShowComposed] = useState(false)
  const [provider, setProvider] = useState('')
  const [model, setModel] = useState('')
  const [credentialId, setCredentialId] = useState('')
  const [llmConfig, setLlmConfig] = useState<LLMGenerationConfig | null>(null)

  const queryKey = ['simulation-failure-analysis', runId]
  const { data, isLoading } = useQuery({
    queryKey,
    queryFn: () => apiClient.getSimulationFailureAnalysis(runId),
    enabled: !runActive,
    refetchInterval: (query) => (isAnalysisRunning(query.state.data) ? 4000 : false),
  })
  const refresh = () => {
    queryClient.invalidateQueries({ queryKey })
    queryClient.invalidateQueries({ queryKey: ['simulation-composed-prompt', runId] })
  }

  const generateMutation = useMutation({
    mutationFn: () =>
      apiClient.generateSimulationFailureAnalysis(runId, {
        provider: provider || undefined,
        model: model || undefined,
        credential_id: credentialId || undefined,
      }),
    onSuccess: (next) => {
      queryClient.setQueryData(queryKey, next)
      setShowComposed(false)
    },
    onError: (err) => onToast(getApiErrorDetail(err) || 'Failed to start failure analysis', 'error'),
  })
  const cancelMutation = useMutation({
    mutationFn: () => apiClient.cancelSimulationFailureAnalysis(runId),
    onSuccess: (next) => queryClient.setQueryData(queryKey, next),
    onError: (err) => onToast(getApiErrorDetail(err) || 'Failed to cancel', 'error'),
  })
  const reviewMutation = useMutation({
    mutationFn: (body: Parameters<typeof apiClient.reviewSimulationPromptImprovement>[1]) =>
      apiClient.reviewSimulationPromptImprovement(runId, body),
    onSuccess: refresh,
    onError: (err) => onToast(getApiErrorDetail(err) || 'Failed to save the review', 'error'),
  })

  const clusters = data?.metric_clusters ?? null
  const improvements = data?.prompt_improvements ?? null
  const suggestions = improvements?.suggestions ?? []
  const acceptedCount = suggestions.filter((s) => s.review_status === 'accepted').length

  const { data: composed, error: composedError } = useQuery({
    queryKey: ['simulation-composed-prompt', runId],
    queryFn: () => apiClient.getSimulationComposedPrompt(runId),
    enabled: showComposed && improvements?.status === 'completed',
    retry: false,
  })

  const evidenceClient = {
    buildEvidenceHref: (evidence: MetricClusterEvidence) =>
      evidence.evaluation_row_id
        ? `/simulations/${runId}?tab=analysis&trial=${encodeURIComponent(evidence.evaluation_row_id)}`
        : null,
  }

  const running = isAnalysisRunning(data)
  const canGenerate = !runActive && !running && (data?.failed_trials ?? 0) > 0
  const progress = clusters?.progress

  return (
    <section className="space-y-4 rounded-lg border border-gray-200 bg-white p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="inline-flex items-center gap-2 text-sm font-semibold text-gray-900">
            <Sparkles className="h-4 w-4 text-primary-600" />
            Failure analysis
          </h2>
          <p className="mt-1 text-xs text-gray-500">
            Trials that missed a success rule are clustered into failure patterns, then mapped to
            suggested edits of the production agent prompt.
          </p>
        </div>
        {running && clusters?.status === 'running' ? (
          <Button
            variant="outline"
            size="sm"
            leftIcon={<Square className="h-4 w-4" />}
            onClick={() => cancelMutation.mutate()}
            isLoading={cancelMutation.isPending}
          >
            Cancel
          </Button>
        ) : (
          <Button
            size="sm"
            leftIcon={<Sparkles className="h-4 w-4" />}
            onClick={() => generateMutation.mutate()}
            isLoading={generateMutation.isPending}
            disabled={!canGenerate}
          >
            {clusters ? 'Regenerate' : 'Generate'}
          </Button>
        )}
      </div>

      {runActive ? (
        <p className="text-sm text-gray-500">Available once the run finishes.</p>
      ) : isLoading ? (
        <p className="text-sm text-gray-500">Loading…</p>
      ) : (
        <>
          {!running ? (
            <div className="rounded-md border border-gray-200 bg-gray-50 p-2.5">
              <p className="mb-2 text-[11px] text-gray-500">
                LLM used for clustering and prompt suggestions. Leave unset to use your default.
              </p>
              <AIProviderModelPicker
                provider={provider}
                model={model}
                credentialId={credentialId}
                onProviderChange={setProvider}
                onModelChange={setModel}
                onCredentialIdChange={setCredentialId}
                llm_config={llmConfig}
                onLLMConfigChange={setLlmConfig}
                disabled={generateMutation.isPending}
                size="sm"
              />
            </div>
          ) : null}

          {!clusters && (data?.failed_trials ?? 0) === 0 ? (
            <p className="text-sm text-gray-500">
              Every completed trial met its success rules, so there is nothing to analyse.
            </p>
          ) : !clusters ? (
            <p className="text-sm text-gray-500">
              {data?.failed_trials} trial(s) missed a success rule. Generate an analysis to see why.
            </p>
          ) : null}

          {clusters?.status === 'running' ? (
            <p className="inline-flex items-center gap-2 text-sm text-gray-700">
              <Loader2 className="h-4 w-4 animate-spin text-primary-600" />
              Clustering failed trials
              {progress?.total_llm_calls
                ? ` · ${progress.completed_llm_calls}/${progress.total_llm_calls} LLM calls`
                : ''}
              {progress?.current_metric_name ? ` · ${progress.current_metric_name}` : ''}
            </p>
          ) : null}

          {clusters?.status === 'failed' || clusters?.status === 'cancelled' ? (
            <div className="inline-flex items-start gap-2 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
              <span>{clusters.error_message || 'Failure clustering did not finish.'}</span>
            </div>
          ) : null}

          {clusters?.status === 'completed' ? (
            <div className="space-y-3">
              <div className="inline-flex rounded-md border border-gray-200 p-0.5 text-xs font-medium">
                {(['overview', 'clusters'] as const).map((option) => (
                  <button
                    key={option}
                    type="button"
                    onClick={() => setView(option)}
                    className={`rounded px-3 py-1 capitalize ${
                      view === option ? 'bg-primary-600 text-white' : 'text-gray-600 hover:bg-gray-50'
                    }`}
                  >
                    {option}
                  </button>
                ))}
              </div>
              {view === 'overview' ? (
                <ClusterReportVisualizationTab state={clusters} />
              ) : (
                <ClusterHierarchyExplorer state={clusters} client={evidenceClient} />
              )}
            </div>
          ) : null}

          {clusters?.status === 'completed' ? (
            <div className="space-y-3 border-t border-gray-100 pt-4">
              <h3 className="text-sm font-semibold text-gray-900">Prompt optimization</h3>
              {improvements?.status === 'running' ? (
                <p className="inline-flex items-center gap-2 text-sm text-gray-700">
                  <Loader2 className="h-4 w-4 animate-spin text-primary-600" />
                  Mapping failure clusters to the production agent prompt…
                </p>
              ) : improvements?.status === 'failed' ? (
                <div className="inline-flex items-start gap-2 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
                  <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                  <span>{improvements.error_message || 'Prompt suggestions failed.'}</span>
                </div>
              ) : null}

              {improvements?.overview ? (
                <div className="rounded-md border border-gray-100 bg-gray-50 px-3 py-2 text-sm text-gray-700">
                  {improvements.overview}
                </div>
              ) : null}

              {suggestions.length ? (
                <PromptSuggestionList
                  suggestions={suggestions}
                  onReview={(body) => reviewMutation.mutateAsync(body)}
                  isReviewing={reviewMutation.isPending}
                  diffView={diffView}
                  onDiffViewChange={setDiffView}
                  acceptedNote="Accepted — included in the optimized prompt"
                  appliedNote="Applied"
                />
              ) : improvements?.status === 'completed' ? (
                <p className="text-sm text-gray-500">No suggestions were produced for this run.</p>
              ) : null}

              {suggestions.length ? (
                <div className="space-y-3 rounded-lg border border-gray-200 p-3">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <p className="text-sm text-gray-700">
                      {acceptedCount
                        ? `${acceptedCount} accepted change(s) applied to the production prompt.`
                        : 'Accept suggestions to build the optimized prompt.'}
                    </p>
                    <div className="flex gap-2">
                      <Button
                        variant="outline"
                        size="sm"
                        disabled={!acceptedCount}
                        onClick={() => setShowComposed((open) => !open)}
                      >
                        {showComposed ? 'Hide optimized prompt' : 'View optimized prompt'}
                      </Button>
                      {showComposed && composed ? (
                        <Button
                          size="sm"
                          leftIcon={<Copy className="h-4 w-4" />}
                          onClick={() =>
                            navigator.clipboard
                              .writeText(composed.composed_prompt)
                              .then(() => onToast('Optimized prompt copied', 'success'))
                              .catch(() => onToast('Could not copy to clipboard', 'error'))
                          }
                        >
                          Copy
                        </Button>
                      ) : null}
                    </div>
                  </div>
                  {showComposed && composedError ? (
                    <p className="text-xs text-red-600">
                      {getApiErrorDetail(composedError) || 'Could not compose the prompt.'}
                    </p>
                  ) : null}
                  {showComposed && composed ? (
                    <PromptLineDiff
                      view={diffView}
                      leftLabel="Current prompt"
                      rightLabel="Optimized prompt"
                      before={composed.base_prompt}
                      after={composed.composed_prompt}
                      maxHeightClass="max-h-[28rem]"
                    />
                  ) : null}
                </div>
              ) : null}
            </div>
          ) : null}
        </>
      )}
    </section>
  )
}
