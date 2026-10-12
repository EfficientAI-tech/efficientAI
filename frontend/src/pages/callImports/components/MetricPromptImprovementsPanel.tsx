import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { AlertTriangle, Check, ExternalLink, GitBranch, Loader2, Pencil, Sparkles, X } from 'lucide-react'

import AIProviderModelPicker from '../../../components/AIProviderModelPicker'
import type { LLMGenerationConfig } from '../../../config/llmGenerationParams'
import { apiClient } from '../../../lib/api'
import { getApiErrorMessage } from '../../../lib/apiErrors'
import AgentFlowChart from '../../promptPartials/components/AgentFlowChart'
import PromptLineDiff from './PromptLineDiff'
import type {
  AgentFlowGraph,
  EvaluationMetricClustersState,
  EvaluationPromptImprovementsState,
  ImportedAgent,
  PromptImprovementSuggestion,
  PromptPushPreview,
} from '../../../types/api'

const GAP_LABEL_STYLES: Record<string, string> = {
  LOGIC_GAP: 'bg-rose-50 text-rose-700 border-rose-200',
  UNDERSPEC: 'bg-amber-50 text-amber-700 border-amber-200',
  EXISTS_NO_TRIGGER: 'bg-sky-50 text-sky-700 border-sky-200',
  MISSING: 'bg-violet-50 text-violet-700 border-violet-200',
}

const PRIORITY_STYLES: Record<string, string> = {
  high: 'text-rose-700',
  medium: 'text-amber-700',
  low: 'text-gray-600',
}

const CHANGE_TYPE_STYLES: Record<string, string> = {
  edit: 'bg-blue-50 text-blue-700 border-blue-200',
  add: 'bg-emerald-50 text-emerald-700 border-emerald-200',
}

function formatModelLabel(provider?: string | null, model?: string | null): string | null {
  if (!provider && !model) return null
  if (provider && model) return `${provider} / ${model}`
  return provider || model || null
}

export default function MetricPromptImprovementsPanel({
  callImportId,
  evaluationId,
  clustersState,
  improvementsState,
  isLoading,
  onGenerated,
}: {
  callImportId: string
  evaluationId: string
  clustersState: EvaluationMetricClustersState | null
  improvementsState: EvaluationPromptImprovementsState | null
  isLoading: boolean
  onGenerated: () => void
}) {
  const queryClient = useQueryClient()
  const [selectedAgentId, setSelectedAgentId] = useState('')
  const [pickerProvider, setPickerProvider] = useState('')
  const [pickerModel, setPickerModel] = useState('')
  const [pickerCredentialId, setPickerCredentialId] = useState('')
  const [pickerLlmConfig, setPickerLlmConfig] = useState<LLMGenerationConfig | null>(null)
  const [llmPickerTouched, setLlmPickerTouched] = useState(false)
  const [agentPickerTouched, setAgentPickerTouched] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [activeSuggestionId, setActiveSuggestionId] = useState<string | null>(null)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [draftText, setDraftText] = useState('')
  const [pushPreview, setPushPreview] = useState<PromptPushPreview | null>(null)
  const [confirmText, setConfirmText] = useState('')
  const [pushError, setPushError] = useState<string | null>(null)

  const { data: importedAgents = [] } = useQuery<ImportedAgent[]>({
    queryKey: ['imported-agents-picker'],
    queryFn: () => apiClient.listImportedAgents(0, 100),
  })

  const { data: selectedAgentDetail } = useQuery({
    queryKey: ['prompt-partial', selectedAgentId],
    queryFn: () => apiClient.getPromptPartial(selectedAgentId),
    enabled: !!selectedAgentId,
    refetchOnWindowFocus: false,
    refetchInterval: (query) => {
      const status = query.state.data?.agent_flowchart_status
      return status === 'generating' || status === 'mapping' ? 3000 : false
    },
  })

  useEffect(() => {
    setAgentPickerTouched(false)
    setActiveSuggestionId(null)
  }, [evaluationId])

  useEffect(() => {
    if (agentPickerTouched) return
    if (improvementsState?.imported_agent_id) {
      setSelectedAgentId(improvementsState.imported_agent_id)
    } else if (!selectedAgentId && importedAgents.length === 1) {
      setSelectedAgentId(importedAgents[0].id)
    }
  }, [
    improvementsState?.imported_agent_id,
    importedAgents,
    selectedAgentId,
    agentPickerTouched,
  ])

  useEffect(() => {
    if (llmPickerTouched) return
    if (improvementsState?.provider) {
      setPickerProvider(improvementsState.provider)
    }
    if (improvementsState?.model) {
      setPickerModel(improvementsState.model)
    }
  }, [
    improvementsState?.provider,
    improvementsState?.model,
    llmPickerTouched,
  ])

  const generateMutation = useMutation({
    mutationFn: () =>
      apiClient.generateCallImportEvaluationPromptImprovements(
        callImportId,
        evaluationId,
        {
          imported_agent_id: selectedAgentId,
          regenerate: improvementsState?.status === 'completed',
          force: improvementsState?.status === 'completed',
          provider: pickerProvider || undefined,
          model: pickerModel || undefined,
          credential_id: pickerCredentialId || undefined,
        },
      ),
    onSuccess: () => {
      setError(null)
      onGenerated()
    },
    onError: (e: any) => {
      setError(e?.response?.data?.detail || 'Failed to generate prompt improvements.')
    },
  })

  const generateFlowchartMutation = useMutation({
    mutationFn: () =>
      apiClient.generateAgentFlowchart(selectedAgentId, {
        provider: pickerProvider || undefined,
        model: pickerModel || undefined,
        credential_id: pickerCredentialId || undefined,
        regenerate: false,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['prompt-partial', selectedAgentId] })
    },
    onError: (e: any) => {
      setError(
        e?.response?.data?.detail || 'Failed to generate agent logic diagram.',
      )
    },
  })

  const reviewMutation = useMutation({
    mutationFn: (data: {
      suggestion_id: string
      review_status: 'pending' | 'accepted' | 'rejected'
      edited_text?: string | null
    }) => apiClient.reviewCallImportEvaluationPromptImprovement(callImportId, evaluationId, data),
    onSuccess: () => {
      setEditingId(null)
      setPushPreview(null)
      setConfirmText('')
      onGenerated()
    },
    onError: (e: unknown) => setError(getApiErrorMessage(e, 'Failed to save the review.')),
  })

  const settingsMutation = useMutation({
    mutationFn: (requireReview: boolean) =>
      apiClient.updateCallImportEvaluationPromptImprovementSettings(callImportId, evaluationId, {
        require_review: requireReview,
      }),
    onSuccess: () => onGenerated(),
    onError: (e: unknown) => setError(getApiErrorMessage(e, 'Failed to update review settings.')),
  })

  const previewMutation = useMutation({
    mutationFn: () => apiClient.previewCallImportEvaluationPromptPush(callImportId, evaluationId),
    onSuccess: (preview) => {
      setPushError(null)
      setConfirmText('')
      setPushPreview(preview)
    },
    onError: (e: unknown) => setPushError(getApiErrorMessage(e, 'Failed to prepare the prompt diff.')),
  })

  const pushMutation = useMutation({
    mutationFn: () => apiClient.pushCallImportEvaluationPrompt(callImportId, evaluationId, 'confirm'),
    onSuccess: () => {
      setPushPreview(null)
      setConfirmText('')
      setPushError(null)
      onGenerated()
      if (selectedAgentId) {
        queryClient.invalidateQueries({ queryKey: ['prompt-partial', selectedAgentId] })
      }
    },
    onError: (e: unknown) => setPushError(getApiErrorMessage(e, 'The live prompt was not updated.')),
  })

  const clustersReady = clustersState?.status === 'completed'
  const agentFlowchart = selectedAgentDetail?.agent_flowchart as AgentFlowGraph | null | undefined
  const hasFlowchart = !!agentFlowchart?.nodes?.length
  const flowchartStatus = selectedAgentDetail?.agent_flowchart_status as string | null | undefined

  const activeSuggestion = improvementsState?.suggestions?.find(
    (suggestion) => suggestion.id === activeSuggestionId,
  )
  const highlightNodeId = activeSuggestion?.flow_node_id || null

  const handleSuggestionFocus = (suggestion: PromptImprovementSuggestion) => {
    setActiveSuggestionId(suggestion.id)
  }

  if (isLoading && !improvementsState) {
    return (
      <section className="rounded-lg border border-dashed border-gray-200 bg-gray-50/60 p-4">
        <h3 className="text-sm font-semibold text-gray-900 mb-1">
          Prompt / Agent Improvements
        </h3>
        <p className="text-xs text-gray-500">Loading…</p>
      </section>
    )
  }

  if (!clustersReady) {
    return (
      <section className="rounded-lg border border-amber-200 bg-amber-50/60 px-4 py-3">
        <p className="text-sm font-semibold text-gray-900 mb-1">
          Prompt / Agent Improvements
        </p>
        <p className="text-sm text-amber-800">
          Generate failure diagnostics (Clusters sub-tab) first. Prompt improvements
          are derived from the top failure clusters in that run.
        </p>
      </section>
    )
  }

  if (improvementsState?.status === 'running') {
    return (
      <section className="rounded-lg border border-amber-200 bg-amber-50/60 px-4 py-3">
        <p className="text-sm font-semibold text-gray-900 inline-flex items-center gap-2">
          <Loader2 className="h-4 w-4 animate-spin text-amber-600" />
          Generating prompt improvement suggestions…
        </p>
        <p className="text-xs text-amber-800 mt-2">
          Mapping clusters from this evaluation against the selected imported agent prompt.
        </p>
      </section>
    )
  }

  const usedModelLabel = formatModelLabel(
    improvementsState?.provider,
    improvementsState?.model,
  )

  return (
    <section className="rounded-lg border border-gray-200 bg-white p-4 space-y-4 min-w-0 overflow-hidden">
      <div>
        <h3 className="text-sm font-semibold text-gray-900 inline-flex items-center gap-2">
          <Sparkles className="h-4 w-4 text-primary-600" />
          Prompt / Agent Improvements
        </h3>
        <p className="text-xs text-gray-500 mt-1">
          Map this evaluation against a production agent prompt and get suggested edits
          to reduce high-share failure clusters.
        </p>
        {usedModelLabel ? (
          <p className="text-[11px] text-gray-400 mt-1">
            Generated with {usedModelLabel}
          </p>
        ) : null}
      </div>

      {importedAgents.length === 0 ? (
        <div className="rounded-md border border-dashed border-gray-200 bg-gray-50 px-3 py-3 text-sm text-gray-600">
          No imported agents yet.{' '}
          <Link
            to="/prompt-partials?kind=imported_agent"
            className="text-primary-700 hover:text-primary-800"
          >
            Import a production prompt
          </Link>{' '}
          under Prompts → Partials.
        </div>
      ) : (
        <div className="space-y-3">
          <div className="flex flex-wrap items-end gap-3">
            <div className="min-w-[240px]">
              <label className="block text-xs font-medium text-gray-700 mb-1">
                Imported agent
              </label>
              <select
                value={selectedAgentId}
                onChange={(e) => {
                  setAgentPickerTouched(true)
                  setSelectedAgentId(e.target.value)
                  setActiveSuggestionId(null)
                }}
                className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
              >
                <option value="">Select an imported agent…</option>
                {importedAgents.map((agent) => (
                  <option key={agent.id} value={agent.id}>
                    {agent.name}
                  </option>
                ))}
              </select>
            </div>
            <button
              type="button"
              disabled={!selectedAgentId || generateMutation.isPending}
              onClick={() => generateMutation.mutate()}
              className="inline-flex items-center gap-2 rounded-md bg-primary-600 px-4 py-2 text-sm font-medium text-white hover:bg-primary-700 disabled:opacity-50"
            >
              {generateMutation.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Sparkles className="h-4 w-4" />
              )}
              Generate suggestions
            </button>
          </div>

          <div className="rounded-md border border-gray-200 bg-gray-50 p-2.5">
            <p className="text-[11px] text-gray-500 mb-2">
              Choose the LLM used to generate improvement suggestions. Leave unset to
              select a provider and model explicitly.
            </p>
            <AIProviderModelPicker
              provider={pickerProvider}
              model={pickerModel}
              credentialId={pickerCredentialId}
              onProviderChange={(next) => {
                setLlmPickerTouched(true)
                setPickerProvider(next)
              }}
              onCredentialIdChange={(next) => {
                setLlmPickerTouched(true)
                setPickerCredentialId(next)
              }}
              onModelChange={(next) => {
                setLlmPickerTouched(true)
                setPickerModel(next)
              }}
              llm_config={pickerLlmConfig}
              onLLMConfigChange={setPickerLlmConfig}
              disabled={generateMutation.isPending}
              size="sm"
            />
          </div>
        </div>
      )}

      {selectedAgentId && !hasFlowchart ? (
        <div className="rounded-md border border-dashed border-gray-200 bg-gray-50 px-3 py-3 text-sm text-gray-600 space-y-2">
          <p className="inline-flex items-center gap-2">
            <GitBranch className="h-4 w-4 text-gray-500" />
            Generate an agent logic diagram to map suggestions to specific nodes in
            the flow.
          </p>
          <button
            type="button"
            disabled={
              generateFlowchartMutation.isPending ||
              flowchartStatus === 'generating' ||
              flowchartStatus === 'mapping'
            }
            onClick={() => generateFlowchartMutation.mutate()}
            className="inline-flex items-center gap-2 rounded-md border border-gray-300 bg-white px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
          >
            {generateFlowchartMutation.isPending ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <GitBranch className="h-3.5 w-3.5" />
            )}
            {flowchartStatus === 'generating' || flowchartStatus === 'mapping'
              ? 'Generating diagram…'
              : 'Generate agent diagram'}
          </button>
        </div>
      ) : null}

      {error ? <p className="text-xs text-red-600">{error}</p> : null}

      {improvementsState?.status === 'failed' ? (
        <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700 inline-flex items-start gap-2">
          <AlertTriangle className="h-4 w-4 mt-0.5 shrink-0" />
          <span>{improvementsState.error_message || 'Generation failed.'}</span>
        </div>
      ) : null}

      {improvementsState?.overview ? (
        <div className="rounded-md border border-gray-100 bg-gray-50 px-3 py-2 text-sm text-gray-700">
          {improvementsState.overview}
        </div>
      ) : null}

      {hasFlowchart && improvementsState?.suggestions?.length ? (
        <div className="rounded-md border border-gray-200 bg-white overflow-hidden">
          <div className="flex items-center justify-between px-3 py-2 border-b border-gray-100 bg-gray-50">
            <p className="text-xs font-medium text-gray-700 inline-flex items-center gap-1.5">
              <GitBranch className="h-3.5 w-3.5" />
              Agent logic diagram
              {activeSuggestion?.flow_node_label ? (
                <span className="text-gray-500 font-normal">
                  · highlighting {activeSuggestion.flow_node_label}
                </span>
              ) : null}
            </p>
            <Link
              to={`/prompt-partials/${selectedAgentId}?kind=imported_agent`}
              className="text-[11px] text-primary-700 hover:text-primary-800 inline-flex items-center gap-1"
            >
              Open full diagram
              <ExternalLink className="h-3 w-3" />
            </Link>
          </div>
          <div className="h-[280px]">
            <AgentFlowChart
              data={agentFlowchart!}
              height={280}
              title={selectedAgentDetail?.name || 'Agent logic'}
              highlightNodeId={highlightNodeId}
            />
          </div>
        </div>
      ) : null}

      {improvementsState?.suggestions?.length ? (
        <div className="space-y-3 min-w-0">
          {improvementsState.suggestions.map((suggestion, index) => {
            const isActive = activeSuggestionId === suggestion.id
            const changeType = suggestion.change_type || 'add'
            const changeLabel = changeType === 'edit' ? 'Edit existing' : 'New addition'

            return (
              <article
                key={suggestion.id}
                className={`rounded-md border p-3 space-y-2 min-w-0 overflow-hidden transition-colors ${
                  isActive
                    ? 'border-primary-300 bg-primary-50/30'
                    : 'border-gray-200 bg-gray-50/60'
                }`}
              >
                <div className="flex flex-wrap items-center gap-2 min-w-0">
                  <button
                    type="button"
                    onClick={() => handleSuggestionFocus(suggestion)}
                    className="text-sm font-semibold text-gray-900 break-words min-w-0 flex-1 text-left hover:text-primary-700"
                  >
                    {index + 1}. {suggestion.metric_name} · {suggestion.cluster_label}
                  </button>
                  <span
                    className={`text-[10px] uppercase tracking-wide font-semibold rounded border px-1.5 py-0.5 ${
                      CHANGE_TYPE_STYLES[changeType] || 'bg-gray-100 text-gray-700 border-gray-200'
                    }`}
                  >
                    {changeLabel}
                  </span>
                  <span
                    className={`text-[10px] uppercase tracking-wide font-semibold rounded border px-1.5 py-0.5 ${
                      GAP_LABEL_STYLES[suggestion.gap_label] || 'bg-gray-100 text-gray-700 border-gray-200'
                    }`}
                  >
                    {suggestion.gap_label}
                  </span>
                  <span
                    className={`text-xs font-medium ${
                      PRIORITY_STYLES[suggestion.priority] || 'text-gray-600'
                    }`}
                  >
                    {suggestion.priority} priority
                  </span>
                  <span className="text-xs text-gray-500 tabular-nums">
                    {suggestion.share_pct.toFixed(1)}% cluster share
                  </span>
                </div>

                {suggestion.target_section ? (
                  <p className="text-xs text-gray-600 break-words">
                    <span className="font-medium">Target section:</span>{' '}
                    {suggestion.target_section}
                  </p>
                ) : null}

                {suggestion.flow_node_label ? (
                  <p className="text-xs text-gray-600 break-words">
                    <span className="font-medium">Agent logic node:</span>{' '}
                    <button
                      type="button"
                      onClick={() => handleSuggestionFocus(suggestion)}
                      className="text-primary-700 hover:text-primary-800 underline-offset-2 hover:underline"
                    >
                      {suggestion.flow_node_label}
                    </button>
                  </p>
                ) : null}

                {suggestion.current_gap ? (
                  <p className="text-xs text-gray-600 break-words">
                    <span className="font-medium">Current gap:</span> {suggestion.current_gap}
                  </p>
                ) : null}

                {suggestion.rationale ? (
                  <p className="text-xs text-gray-500 break-words">{suggestion.rationale}</p>
                ) : null}

                <PromptLineDiff
                  before={changeType === 'edit' ? suggestion.anchor_excerpt || '' : ''}
                  after={
                    suggestion.edited_text?.trim()
                      ? suggestion.edited_text
                      : suggestion.suggested_text
                  }
                />

                {editingId === suggestion.id ? (
                  <div className="space-y-2">
                    <textarea
                      value={draftText}
                      onChange={(event) => setDraftText(event.target.value)}
                      rows={6}
                      className="w-full rounded border border-gray-300 px-2 py-1.5 text-xs font-mono text-gray-800"
                    />
                    <div className="flex gap-2">
                      <button
                        type="button"
                        disabled={reviewMutation.isPending || !draftText.trim()}
                        onClick={() =>
                          reviewMutation.mutate({
                            suggestion_id: suggestion.id,
                            review_status: 'accepted',
                            edited_text: draftText,
                          })
                        }
                        className="rounded border border-emerald-300 bg-emerald-50 px-2 py-1 text-xs font-medium text-emerald-800 disabled:opacity-50"
                      >
                        Accept edited text
                      </button>
                      <button
                        type="button"
                        onClick={() => setEditingId(null)}
                        className="rounded border border-gray-300 px-2 py-1 text-xs text-gray-600"
                      >
                        Cancel
                      </button>
                    </div>
                  </div>
                ) : (
                  <div className="flex flex-wrap items-center gap-2">
                    <span
                      className={`text-[10px] uppercase tracking-wide font-semibold rounded border px-1.5 py-0.5 ${
                        suggestion.review_status === 'accepted'
                          ? 'bg-emerald-50 text-emerald-700 border-emerald-200'
                          : suggestion.review_status === 'rejected'
                            ? 'bg-rose-50 text-rose-700 border-rose-200'
                            : 'bg-gray-100 text-gray-600 border-gray-200'
                      }`}
                    >
                      {suggestion.review_status || 'pending'}
                    </span>
                    <button
                      type="button"
                      disabled={reviewMutation.isPending}
                      onClick={() =>
                        reviewMutation.mutate({
                          suggestion_id: suggestion.id,
                          review_status: 'accepted',
                        })
                      }
                      className="inline-flex items-center gap-1 rounded border border-emerald-300 bg-white px-2 py-1 text-xs font-medium text-emerald-800"
                    >
                      <Check className="h-3 w-3" />
                      Accept this change
                    </button>
                    <button
                      type="button"
                      disabled={reviewMutation.isPending}
                      onClick={() =>
                        reviewMutation.mutate({
                          suggestion_id: suggestion.id,
                          review_status: 'rejected',
                        })
                      }
                      className="inline-flex items-center gap-1 rounded border border-rose-300 bg-white px-2 py-1 text-xs font-medium text-rose-800"
                    >
                      <X className="h-3 w-3" />
                      Reject this change
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        setEditingId(suggestion.id)
                        setDraftText(
                          suggestion.edited_text?.trim()
                            ? suggestion.edited_text
                            : suggestion.suggested_text,
                        )
                      }}
                      className="inline-flex items-center gap-1 rounded border border-gray-300 bg-white px-2 py-1 text-xs font-medium text-gray-700"
                    >
                      <Pencil className="h-3 w-3" />
                      Edit manually
                    </button>
                  </div>
                )}
              </article>
            )
          })}
        </div>
      ) : improvementsState?.status === 'completed' ? (
        <p className="text-sm text-gray-500">No suggestions were produced for this run.</p>
      ) : null}

      {improvementsState?.suggestions?.length ? (
        <div className="rounded-md border border-gray-200 bg-white p-3 space-y-3">
          <label className="flex items-center justify-between gap-3 text-sm text-gray-800">
            <span>Require review before push</span>
            <input
              type="checkbox"
              checked={improvementsState.require_review !== false}
              disabled={settingsMutation.isPending}
              onChange={(event) => settingsMutation.mutate(event.target.checked)}
            />
          </label>
          <p className="text-xs text-gray-500">
            Accepted changes are applied to the imported agent prompt. Rejected changes stay out.
            The live agent is updated only after the full diff and a typed confirm.
          </p>
          <button
            type="button"
            disabled={previewMutation.isPending}
            onClick={() => previewMutation.mutate()}
            className="rounded-md bg-gray-900 px-3 py-1.5 text-xs font-medium text-white disabled:opacity-50"
          >
            {previewMutation.isPending ? 'Preparing diff…' : 'Review full prompt'}
          </button>
          {pushError ? <p className="text-xs text-red-600">{pushError}</p> : null}
          {pushPreview ? (
            <div className="space-y-2">
              <p className="text-xs text-gray-700">
                {pushPreview.external_agent_name
                  ? `Target: ${pushPreview.provider || 'provider'} · ${pushPreview.external_agent_name}`
                  : 'Target agent'}
                {pushPreview.block_reason ? ` · ${pushPreview.block_reason}` : ''}
              </p>
              <PromptLineDiff before={pushPreview.base_prompt} after={pushPreview.composed_prompt} />
              <label className="block text-xs text-gray-700">
                Type confirm to push this prompt live
                <input
                  value={confirmText}
                  onChange={(event) => setConfirmText(event.target.value)}
                  autoComplete="off"
                  className="mt-1 w-full max-w-xs rounded border border-gray-300 px-2 py-1.5 text-sm"
                />
              </label>
              <button
                type="button"
                disabled={
                  pushMutation.isPending ||
                  !pushPreview.can_push ||
                  confirmText !== 'confirm'
                }
                onClick={() => pushMutation.mutate()}
                className="rounded-md bg-emerald-700 px-3 py-1.5 text-xs font-medium text-white disabled:opacity-50"
              >
                {pushMutation.isPending ? 'Pushing…' : 'Push live prompt'}
              </button>
            </div>
          ) : null}
        </div>
      ) : null}
    </section>
  )
}
