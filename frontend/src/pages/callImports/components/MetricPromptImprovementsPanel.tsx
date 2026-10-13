import { useEffect, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import {
  AlertTriangle,
  ArrowRight,
  Check,
  CheckCircle2,
  ExternalLink,
  GitBranch,
  Info,
  Loader2,
  Pencil,
  Sparkles,
  X,
} from 'lucide-react'

import Button from '../../../components/Button'
import AIProviderModelPicker from '../../../components/AIProviderModelPicker'
import { getIntegrationPlatformLogo } from '../../../config/providers'
import type { LLMGenerationConfig } from '../../../config/llmGenerationParams'
import { apiClient } from '../../../lib/api'
import { getApiErrorMessage } from '../../../lib/apiErrors'
import AgentFlowChart from '../../promptPartials/components/AgentFlowChart'
import PromptLineDiff, { PromptDiffViewToggle, type PromptDiffView } from './PromptLineDiff'
import type {
  AgentFlowGraph,
  EvaluationMetricClustersState,
  EvaluationPromptImprovementsState,
  ImportedAgent,
  IntegrationPlatform,
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

function PromptPushMetaPill({ label, children }: { label: string; children: ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-gray-200 bg-white px-2.5 py-1 text-xs">
      <span className="font-medium text-gray-500">{label}</span>
      <span className="text-gray-900 truncate max-w-[12rem]">{children}</span>
    </span>
  )
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
  linkedImportedAgentPartialId = null,
  platformAgentLabel = null,
}: {
  callImportId: string
  evaluationId: string
  clustersState: EvaluationMetricClustersState | null
  improvementsState: EvaluationPromptImprovementsState | null
  isLoading: boolean
  onGenerated: () => void
  linkedImportedAgentPartialId?: string | null
  platformAgentLabel?: string | null
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
  const [pushConfirmOpen, setPushConfirmOpen] = useState(false)
  const [pushModalStep, setPushModalStep] = useState<'review' | 'confirm'>('review')
  const [confirmText, setConfirmText] = useState('')
  const [pushError, setPushError] = useState<string | null>(null)
  const [diffView, setDiffView] = useState<PromptDiffView>('split')

  useEffect(() => {
    if (!pushConfirmOpen) return
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.body.style.overflow = previousOverflow
    }
  }, [pushConfirmOpen])

  const closePushModal = () => {
    setPushConfirmOpen(false)
    setPushModalStep('review')
    setConfirmText('')
  }

  const effectiveAgentId =
    selectedAgentId ||
    linkedImportedAgentPartialId ||
    improvementsState?.imported_agent_id ||
    ''

  const { data: importedAgents = [] } = useQuery<ImportedAgent[]>({
    queryKey: ['imported-agents-picker'],
    queryFn: () => apiClient.listImportedAgents(0, 100),
  })

  const { data: selectedAgentDetail } = useQuery({
    queryKey: ['prompt-partial', effectiveAgentId],
    queryFn: () => apiClient.getPromptPartial(effectiveAgentId),
    enabled: !!effectiveAgentId,
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
    } else if (linkedImportedAgentPartialId) {
      setSelectedAgentId(linkedImportedAgentPartialId)
    } else if (!selectedAgentId && importedAgents.length === 1) {
      setSelectedAgentId(importedAgents[0].id)
    }
  }, [
    improvementsState?.imported_agent_id,
    linkedImportedAgentPartialId,
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
    mutationFn: () => {
      const payload: {
        imported_agent_id?: string
        regenerate?: boolean
        force?: boolean
        provider?: string
        model?: string
        credential_id?: string
      } = {
        regenerate: improvementsState?.status === 'completed',
        force: improvementsState?.status === 'completed',
        provider: pickerProvider || undefined,
        model: pickerModel || undefined,
        credential_id: pickerCredentialId || undefined,
      }
      if (!linkedImportedAgentPartialId && effectiveAgentId) {
        payload.imported_agent_id = effectiveAgentId
      }
      return apiClient.generateCallImportEvaluationPromptImprovements(
        callImportId,
        evaluationId,
        payload,
      )
    },
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
      apiClient.generateAgentFlowchart(effectiveAgentId, {
        provider: pickerProvider || undefined,
        model: pickerModel || undefined,
        credential_id: pickerCredentialId || undefined,
        regenerate: false,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['prompt-partial', effectiveAgentId] })
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

  const previewMutation = useMutation({
    mutationFn: () => apiClient.previewCallImportEvaluationPromptPush(callImportId, evaluationId),
    onSuccess: (preview) => {
      setPushError(null)
      setConfirmText('')
      setPushPreview(preview)
      setPushModalStep('review')
      setPushConfirmOpen(true)
      if (preview.relinked_imported_agent) {
        if (preview.imported_agent_id) {
          setSelectedAgentId(preview.imported_agent_id)
        }
        onGenerated()
        queryClient.invalidateQueries({ queryKey: ['prompt-partials'] })
        if (preview.imported_agent_id) {
          queryClient.invalidateQueries({ queryKey: ['prompt-partial', preview.imported_agent_id] })
        }
      }
    },
    onError: (e: unknown) => setPushError(getApiErrorMessage(e, 'Failed to prepare the prompt diff.')),
  })

  const pushMutation = useMutation({
    mutationFn: (pushToLive: boolean) =>
      apiClient.pushCallImportEvaluationPrompt(callImportId, evaluationId, 'confirm', {
        pushToLive,
      }),
    onSuccess: (_data, pushToLive) => {
      setPushPreview(null)
      setPushConfirmOpen(false)
      setPushModalStep('review')
      setConfirmText('')
      setPushError(null)
      onGenerated()
      if (effectiveAgentId) {
        queryClient.invalidateQueries({ queryKey: ['prompt-partial', effectiveAgentId] })
      }
      if (!pushToLive) {
        setError(null)
      }
    },
    onError: (e: unknown, pushToLive) =>
      setPushError(
        getApiErrorMessage(
          e,
          pushToLive ? 'The live prompt was not updated.' : 'Could not save the prompt version.',
        ),
      ),
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

      {!linkedImportedAgentPartialId && importedAgents.length === 0 ? (
        <div className="rounded-md border border-dashed border-gray-200 bg-gray-50 px-3 py-3 text-sm text-gray-600">
          No imported agents yet.{' '}
          <Link
            to="/prompt-partials?kind=imported_agent"
            className="text-primary-700 hover:text-primary-800"
          >
            Import a production prompt
          </Link>{' '}
          under Prompts → Partials, or use a single-agent platform import.
        </div>
      ) : (
        <div className="space-y-3">
          {linkedImportedAgentPartialId ? (
            <div className="rounded-md border border-amber-200 bg-amber-50/70 px-3 py-2.5 text-sm text-gray-800">
              <p>
                <span className="font-medium text-gray-900">Target agent:</span>{' '}
                {platformAgentLabel || improvementsState?.imported_agent_name || 'Platform import agent'}
              </p>
              <p className="text-xs text-gray-600 mt-1">
                Live prompt was imported as{' '}
                <Link
                  to={`/prompt-partials/${linkedImportedAgentPartialId}?kind=imported_agent`}
                  className="text-primary-700 hover:text-primary-800 font-medium"
                >
                  Prompt Partial v1
                </Link>{' '}
                when this platform import started. Version history is append-only.
              </p>
            </div>
          ) : (
            <div className="min-w-[240px] max-w-md">
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
          )}
          <div className="flex flex-wrap items-end gap-3">
            <button
              type="button"
              disabled={!effectiveAgentId || generateMutation.isPending}
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

      {effectiveAgentId && !hasFlowchart ? (
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
              to={`/prompt-partials/${effectiveAgentId}?kind=imported_agent`}
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
          <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-gray-200 bg-gray-50 px-3 py-2">
            <span className="text-xs font-medium text-gray-600">Suggestion diffs</span>
            <PromptDiffViewToggle view={diffView} onChange={setDiffView} />
          </div>
          {improvementsState.suggestions.map((suggestion, index) => {
            const isActive = activeSuggestionId === suggestion.id
            const changeType = suggestion.change_type || 'add'
            const changeLabel = changeType === 'edit' ? 'Edit existing' : 'New addition'
            const reviewStatus = suggestion.review_status || 'pending'
            const isAccepted = reviewStatus === 'accepted'
            const isRejected = reviewStatus === 'rejected'
            const isPending = !isAccepted && !isRejected

            const cardSurfaceClass = isAccepted
              ? 'border-emerald-300 bg-emerald-50/50 ring-1 ring-emerald-200/80'
              : isRejected
                ? 'border-rose-200 bg-rose-50/35 ring-1 ring-rose-100'
                : isActive
                  ? 'border-primary-300 bg-primary-50/30'
                  : 'border-gray-200 bg-gray-50/60'

            return (
              <article
                key={suggestion.id}
                className={`rounded-md border p-3 space-y-2 min-w-0 overflow-hidden transition-all duration-200 ${cardSurfaceClass}`}
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
                  view={diffView}
                  leftLabel={changeType === 'edit' ? 'Current excerpt' : '—'}
                  rightLabel={changeType === 'edit' ? 'Suggested text' : 'New section'}
                  before={changeType === 'edit' ? suggestion.anchor_excerpt || '' : ''}
                  after={
                    suggestion.edited_text?.trim()
                      ? suggestion.edited_text
                      : suggestion.suggested_text
                  }
                  maxHeightClass="max-h-64"
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
                  <div className="space-y-2">
                    {isAccepted ? (
                      <p className="inline-flex items-center gap-1.5 rounded-md border border-emerald-300 bg-emerald-100 px-2.5 py-1.5 text-xs font-medium text-emerald-900">
                        <Check className="h-3.5 w-3.5 shrink-0" />
                        Accepted — included when you push the live prompt
                      </p>
                    ) : null}
                    {isRejected ? (
                      <p className="inline-flex items-center gap-1.5 rounded-md border border-rose-200 bg-rose-100/80 px-2.5 py-1.5 text-xs font-medium text-rose-900">
                        <X className="h-3.5 w-3.5 shrink-0" />
                        Rejected — excluded from the composed prompt
                      </p>
                    ) : null}
                    <div className="flex flex-wrap items-center gap-2">
                      {isPending ? (
                        <span
                          className="text-[10px] uppercase tracking-wide font-semibold rounded border px-1.5 py-0.5 bg-gray-100 text-gray-600 border-gray-200"
                        >
                          pending
                        </span>
                      ) : null}
                      <button
                        type="button"
                        disabled={reviewMutation.isPending || isAccepted}
                        onClick={() =>
                          reviewMutation.mutate({
                            suggestion_id: suggestion.id,
                            review_status: 'accepted',
                          })
                        }
                        className={`inline-flex items-center gap-1 rounded px-2 py-1 text-xs font-medium transition ${
                          isAccepted
                            ? 'border border-emerald-500 bg-emerald-600 text-white cursor-default shadow-sm'
                            : 'border border-emerald-300 bg-white text-emerald-800 hover:bg-emerald-50'
                        }`}
                      >
                        <Check className="h-3 w-3" />
                        {isAccepted ? 'Accepted' : 'Accept this change'}
                      </button>
                      <button
                        type="button"
                        disabled={reviewMutation.isPending || isRejected}
                        onClick={() =>
                          reviewMutation.mutate({
                            suggestion_id: suggestion.id,
                            review_status: 'rejected',
                          })
                        }
                        className={`inline-flex items-center gap-1 rounded px-2 py-1 text-xs font-medium transition ${
                          isRejected
                            ? 'border border-rose-400 bg-rose-600 text-white cursor-default shadow-sm'
                            : 'border border-rose-300 bg-white text-rose-800 hover:bg-rose-50'
                        }`}
                      >
                        <X className="h-3 w-3" />
                        {isRejected ? 'Rejected' : 'Reject this change'}
                      </button>
                      {!isRejected ? (
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
                          className="inline-flex items-center gap-1 rounded border border-gray-300 bg-white px-2 py-1 text-xs font-medium text-gray-700 hover:bg-gray-50"
                        >
                          <Pencil className="h-3 w-3" />
                          Edit manually
                        </button>
                      ) : null}
                    </div>
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
        <div className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm space-y-3">
          <p className="text-sm text-gray-700">
            Review the full diff, then save to your import-linked partial or update the live agent.
          </p>
          <Button
            type="button"
            size="sm"
            disabled={previewMutation.isPending}
            isLoading={previewMutation.isPending}
            onClick={() => previewMutation.mutate()}
          >
            {previewMutation.isPending ? 'Loading preview…' : 'Review changes'}
          </Button>
          {pushError && !pushConfirmOpen ? <p className="text-xs text-red-600">{pushError}</p> : null}
        </div>
      ) : null}

      {pushConfirmOpen && pushPreview && typeof document !== 'undefined'
        ? (() => {
            const providerKey = (pushPreview.provider || '').toLowerCase() as IntegrationPlatform
            const providerLogo = pushPreview.provider
              ? getIntegrationPlatformLogo(providerKey)
              : null
            return createPortal(
            <div className="fixed inset-0 z-[9999] overflow-y-auto">
              <div className="flex min-h-full items-center justify-center p-4 sm:p-6">
                <div
                  className="fixed inset-0 bg-gray-500 bg-opacity-75 transition-opacity"
                  onClick={closePushModal}
                  aria-hidden
                />
                <div
                  className="push-modal-panel relative flex w-full max-w-5xl max-h-[min(90vh,880px)] flex-col overflow-hidden rounded-2xl border border-gray-200 bg-white shadow-xl"
                  role="dialog"
                  aria-modal="true"
                  aria-labelledby="push-live-prompt-title"
                >
                  <div className="flex items-start justify-between gap-3 px-6 py-4 border-b border-gray-100">
                    <div className="flex min-w-0 items-start gap-3">
                      {providerLogo ? (
                        <img
                          src={providerLogo}
                          alt=""
                          className="h-9 w-9 shrink-0 object-contain mt-0.5"
                        />
                      ) : null}
                      <div className="min-w-0">
                        <h3 id="push-live-prompt-title" className="text-lg font-semibold text-gray-900">
                          Review prompt changes
                        </h3>
                        <p className="text-sm text-gray-500 truncate mt-0.5">
                          {pushPreview.external_agent_name || 'Agent'}
                        </p>
                      </div>
                    </div>
                    <button
                      type="button"
                      onClick={closePushModal}
                      className="p-1.5 rounded-md text-gray-400 hover:text-gray-600 hover:bg-gray-100"
                      aria-label="Close"
                    >
                      <X className="h-5 w-5" />
                    </button>
                  </div>

                  <div className="px-6 py-3 bg-gray-50 border-b border-gray-100 flex gap-2 text-xs font-medium">
                    {(
                      [
                        { id: 'review' as const, label: 'Review diff' },
                        { id: 'confirm' as const, label: 'Confirm' },
                      ] as const
                    ).map((s, i) => {
                      const active = pushModalStep === s.id
                      const done = s.id === 'review' && pushModalStep === 'confirm'
                      return (
                        <div key={s.id} className="flex items-center gap-2 flex-1 min-w-0">
                          <span
                            className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full ${
                              done
                                ? 'bg-primary-600 text-white'
                                : active
                                  ? 'bg-primary-100 text-primary-700 ring-2 ring-primary-500'
                                  : 'bg-white text-gray-400 border border-gray-200'
                            }`}
                          >
                            {done ? <CheckCircle2 className="h-3.5 w-3.5" /> : i + 1}
                          </span>
                          <span className={active || done ? 'text-gray-900' : 'text-gray-400'}>
                            {s.label}
                          </span>
                          {i < 1 ? (
                            <ArrowRight className="h-3 w-3 text-gray-300 ml-auto hidden sm:block" />
                          ) : null}
                        </div>
                      )
                    })}
                  </div>

                  <div className="flex flex-wrap gap-2 px-6 py-3 border-b border-gray-100 bg-white">
                    <PromptPushMetaPill label="Partial">
                      {pushPreview.imported_agent_name ||
                        improvementsState?.imported_agent_name ||
                        '—'}
                    </PromptPushMetaPill>
                    <PromptPushMetaPill label="Version">
                      v{pushPreview.partial_current_version ?? 1}
                      {(pushPreview.partial_next_version ?? 1) >
                      (pushPreview.partial_current_version ?? 1)
                        ? ` → v${pushPreview.partial_next_version}`
                        : ''}
                    </PromptPushMetaPill>
                    <PromptPushMetaPill label="Accepted">
                      {pushPreview.accepted_count}
                    </PromptPushMetaPill>
                    {pushPreview.external_agent_id ? (
                      <span
                        className="inline-flex items-center rounded-full border border-gray-200 bg-gray-50 px-2.5 py-1 font-mono text-[11px] text-gray-500 truncate max-w-full"
                        title={pushPreview.external_agent_id}
                      >
                        {pushPreview.external_agent_id}
                      </span>
                    ) : null}
                  </div>

                  <div className="flex min-h-0 flex-1 flex-col overflow-hidden px-6 py-4 gap-3 custom-scrollbar">
                    {pushPreview.relinked_imported_agent ? (
                      <div className="flex gap-2.5 rounded-lg border border-sky-200 bg-sky-50 px-3 py-2.5 text-sm text-gray-800 shrink-0">
                        <Info className="h-5 w-5 shrink-0 text-sky-600" />
                        <div className="min-w-0 space-y-1">
                          <p className="font-medium text-gray-900">
                            Import-linked partial was missing — we re-linked it
                          </p>
                          <p className="text-gray-700 leading-snug">
                            The agent partial for this import was deleted or could not be found in
                            Prompt Partials. We fetched the current live provider prompt, created a
                            new import-linked partial
                            {pushPreview.imported_agent_name
                              ? ` (${pushPreview.imported_agent_name})`
                              : ''}
                            , and attached it to this evaluation. The diff below uses that live
                            prompt as the base.
                          </p>
                          {pushPreview.imported_agent_id ? (
                            <Link
                              to={`/prompt-partials/${pushPreview.imported_agent_id}?kind=imported_agent`}
                              className="inline-flex items-center gap-1 text-xs font-medium text-sky-800 hover:text-sky-950"
                              onClick={closePushModal}
                            >
                              Open new partial in Prompt Partials
                              <ExternalLink className="h-3 w-3" />
                            </Link>
                          ) : null}
                        </div>
                      </div>
                    ) : null}
                    {pushPreview.saved_prompt_matches_live === false ? (
                      <div className="flex gap-2.5 rounded-lg border border-amber-200 bg-[#fef7e0] px-3 py-2.5 text-sm text-gray-800 shrink-0">
                        <AlertTriangle className="h-5 w-5 shrink-0 text-[#f29900]" />
                        <p>
                          Saved partial differs from the provider. You can still save locally; push
                          live from here or Prompt Partials → Agents.
                        </p>
                      </div>
                    ) : null}
                    {pushPreview.block_reason && !pushPreview.can_push && pushModalStep === 'confirm' ? (
                      <p className="text-sm text-red-700 bg-red-50 border border-red-100 rounded-lg px-3 py-2 shrink-0">
                        {pushPreview.block_reason}
                      </p>
                    ) : null}

                    <div
                      key={pushModalStep}
                      className="push-modal-step-enter flex min-h-0 flex-1 flex-col gap-3 overflow-hidden"
                    >
                      {pushModalStep === 'confirm' ? (
                        <div className="shrink-0 rounded-xl border border-gray-200 bg-gray-50 px-4 py-3 space-y-3">
                          <p className="text-sm text-gray-700 leading-relaxed">
                            Choose <span className="font-medium">Save to Partials</span> to version
                            locally, or <span className="font-medium">Update live agent</span> to write
                            to {pushPreview.provider || 'the provider'} (v
                            {pushPreview.partial_next_version ??
                              (pushPreview.partial_current_version ?? 1) + 1}
                            ).
                          </p>
                          <label className="block text-sm font-medium text-gray-900">
                            Type{' '}
                            <span className="rounded-md bg-white border border-gray-200 px-1.5 py-0.5 font-mono text-xs">
                              confirm
                            </span>
                            <input
                              value={confirmText}
                              onChange={(event) => setConfirmText(event.target.value)}
                              autoComplete="off"
                              autoFocus
                              placeholder="confirm"
                              className="mt-2 w-full rounded-lg border border-gray-300 bg-white px-3 py-2.5 text-sm text-gray-900 placeholder:text-gray-400 focus:border-primary-500 focus:outline-none focus:ring-2 focus:ring-primary-500/20"
                            />
                          </label>
                          {pushError ? <p className="text-sm text-red-600">{pushError}</p> : null}
                        </div>
                      ) : null}

                      <div className="flex min-h-0 flex-1 flex-col gap-2 rounded-xl border border-gray-200 overflow-hidden">
                        <div className="flex shrink-0 flex-wrap items-center justify-between gap-2 border-b border-gray-100 bg-gray-50 px-3 py-2">
                          <span className="text-sm font-medium text-gray-800">
                            {pushModalStep === 'review'
                              ? 'Provider vs with accepted changes'
                              : 'Diff preview'}
                          </span>
                          <PromptDiffViewToggle view={diffView} onChange={setDiffView} />
                        </div>
                        <div className="min-h-0 flex-1 p-2 bg-white">
                          <PromptLineDiff
                            view={diffView}
                            leftLabel="Live (provider)"
                            rightLabel="After changes"
                            before={pushPreview.live_prompt || pushPreview.base_prompt}
                            after={pushPreview.composed_prompt}
                            maxHeightClass={
                              pushModalStep === 'confirm'
                                ? 'max-h-[min(32vh,340px)]'
                                : 'max-h-[min(50vh,500px)]'
                            }
                          />
                        </div>
                      </div>
                    </div>
                  </div>

                  <div className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-t border-gray-100 bg-gray-50/90 px-6 py-4">
                    {pushModalStep === 'confirm' ? (
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        onClick={() => {
                          setPushModalStep('review')
                          setConfirmText('')
                          setPushError(null)
                        }}
                      >
                        Back
                      </Button>
                    ) : (
                      <Button type="button" variant="ghost" size="sm" onClick={closePushModal}>
                        Cancel
                      </Button>
                    )}
                    {pushModalStep === 'review' ? (
                      <Button
                        type="button"
                        size="sm"
                        disabled={!pushPreview.can_save_version && !pushPreview.can_push}
                        onClick={() => {
                          setPushModalStep('confirm')
                          setPushError(null)
                        }}
                      >
                        Continue
                      </Button>
                    ) : (
                      <div className="flex flex-wrap justify-end gap-2">
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          disabled={
                            pushMutation.isPending ||
                            !pushPreview.can_save_version ||
                            confirmText !== 'confirm'
                          }
                          isLoading={pushMutation.isPending}
                          onClick={() => pushMutation.mutate(false)}
                        >
                          Save to Partials
                        </Button>
                        <Button
                          type="button"
                          size="sm"
                          disabled={
                            pushMutation.isPending ||
                            !pushPreview.can_push ||
                            confirmText !== 'confirm'
                          }
                          isLoading={pushMutation.isPending}
                          onClick={() => pushMutation.mutate(true)}
                        >
                          Update live agent
                        </Button>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            </div>,
            document.body,
          )
          })()
        : null}
    </section>
  )
}
