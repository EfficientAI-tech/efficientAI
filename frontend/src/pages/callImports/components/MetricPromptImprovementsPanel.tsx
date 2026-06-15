import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { AlertTriangle, ExternalLink, GitBranch, Loader2, Sparkles } from 'lucide-react'
import ReactMarkdown from 'react-markdown'

import AIProviderModelPicker from '../../../components/AIProviderModelPicker'
import type { LLMGenerationConfig } from '../../../config/llmGenerationParams'
import { apiClient } from '../../../lib/api'
import AgentFlowChart from '../../promptPartials/components/AgentFlowChart'
import type {
  AgentFlowGraph,
  EvaluationMetricClustersState,
  EvaluationPromptImprovementsState,
  ImportedAgent,
  PromptImprovementSuggestion,
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
  const [pickerLlmConfig, setPickerLlmConfig] = useState<LLMGenerationConfig | null>(null)
  const [llmPickerTouched, setLlmPickerTouched] = useState(false)
  const [agentPickerTouched, setAgentPickerTouched] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [activeSuggestionId, setActiveSuggestionId] = useState<string | null>(null)

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
              auto-detect your organization&apos;s first active provider.
            </p>
            <AIProviderModelPicker
              provider={pickerProvider}
              model={pickerModel}
              onProviderChange={(next) => {
                setLlmPickerTouched(true)
                setPickerProvider(next)
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

                {changeType === 'edit' && suggestion.anchor_excerpt ? (
                  <div className="grid gap-2 md:grid-cols-2 min-w-0">
                    <div className="rounded border border-rose-200 bg-rose-50/40 p-3 text-xs text-gray-800 max-w-full overflow-hidden">
                      <p className="text-[10px] font-semibold uppercase tracking-wide text-rose-600 mb-1.5">
                        Current prompt (being changed)
                      </p>
                      <div className="prose prose-sm max-w-none break-words prose-headings:text-gray-900 prose-headings:text-sm prose-headings:font-semibold prose-headings:mt-2 prose-headings:mb-1 prose-p:text-gray-800 prose-p:my-1 prose-li:text-gray-800 prose-li:my-0.5 prose-ul:my-1 prose-ol:my-1">
                        <ReactMarkdown>{suggestion.anchor_excerpt}</ReactMarkdown>
                      </div>
                    </div>
                    <div className="rounded border border-emerald-200 bg-emerald-50/40 p-3 text-xs text-gray-800 max-w-full overflow-hidden">
                      <p className="text-[10px] font-semibold uppercase tracking-wide text-emerald-700 mb-1.5">
                        Suggested replacement
                      </p>
                      <div className="prose prose-sm max-w-none break-words prose-headings:text-gray-900 prose-headings:text-sm prose-headings:font-semibold prose-headings:mt-2 prose-headings:mb-1 prose-p:text-gray-800 prose-p:my-1 prose-li:text-gray-800 prose-li:my-0.5 prose-ul:my-1 prose-ol:my-1">
                        <ReactMarkdown>{suggestion.suggested_text}</ReactMarkdown>
                      </div>
                    </div>
                  </div>
                ) : suggestion.suggested_text ? (
                  <div className="rounded border border-gray-200 bg-white p-3 text-xs text-gray-800 max-w-full overflow-hidden">
                    <p className="text-[10px] font-semibold uppercase tracking-wide text-gray-500 mb-1.5">
                      Suggested prompt addition
                    </p>
                    <div className="prose prose-sm max-w-none break-words prose-headings:text-gray-900 prose-headings:text-sm prose-headings:font-semibold prose-headings:mt-2 prose-headings:mb-1 prose-p:text-gray-800 prose-p:my-1 prose-li:text-gray-800 prose-li:my-0.5 prose-ul:my-1 prose-ol:my-1">
                      <ReactMarkdown>{suggestion.suggested_text}</ReactMarkdown>
                    </div>
                  </div>
                ) : null}

                {suggestion.rationale ? (
                  <p className="text-xs text-gray-500 break-words">{suggestion.rationale}</p>
                ) : null}
              </article>
            )
          })}
        </div>
      ) : improvementsState?.status === 'completed' ? (
        <p className="text-sm text-gray-500">No suggestions were produced for this run.</p>
      ) : null}
    </section>
  )
}
