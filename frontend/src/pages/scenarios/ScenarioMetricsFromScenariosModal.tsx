import { useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { BarChart3, Brain, ChevronDown, Lock, X } from 'lucide-react'
import Button from '../../components/Button'
import LLMAdvancedOptionsPanel from '../../components/providers/LLMAdvancedOptionsPanel'
import ScenarioMarkdownView from './ScenarioMarkdownView'
import { useToast } from '../../hooks/useToast'
import { apiClient } from '../../lib/api'
import { resolveActiveAIProvider } from '../../lib/gatewayRouting'
import { resolveLLMModelsForCredential } from '../../lib/llmModelOptions'
import { useLicenseStore } from '../../store/licenseStore'
import { AIProvider, ModelProvider } from '../../types/api'
import type { LLMGenerationConfig } from '../../config/llmGenerationParams'
import { getProviderLabel, getProviderLogo } from '../../config/providers'
import { isChatMedium } from '../../lib/agentMedium'
import type { AgentOption, Scenario } from './scenarioTypes'
import {
  MAX_SCENARIO_METRICS_BATCH,
  customDataTypeForMetricType,
  mergeRequiredMetricTags,
  scenarioToMetricWorkflowDraft,
  type GeneratedScenarioMetricDraft,
  type PlannedScenarioMetricType,
  type ScenarioMetricWorkflowDraft,
} from './scenarioMetricWorkflowTypes'

interface ScenarioMetricsFromScenariosModalProps {
  open: boolean
  onClose: () => void
  scenarios: Scenario[]
  agents: AgentOption[]
  aiProviders: AIProvider[]
  defaultAgentId: string | null
}

export default function ScenarioMetricsFromScenariosModal({
  open,
  onClose,
  scenarios,
  agents,
  aiProviders,
  defaultAgentId,
}: ScenarioMetricsFromScenariosModalProps) {
  const queryClient = useQueryClient()
  const { showToast } = useToast()
  const { isFeatureEnabled, isLoaded: licenseLoaded, getFeatureMeta } = useLicenseStore()
  const scenarioMetricsEnabled = licenseLoaded && isFeatureEnabled('scenario_metrics')

  const [drafts, setDrafts] = useState<ScenarioMetricWorkflowDraft[]>([])
  const [includedIds, setIncludedIds] = useState<Set<string>>(new Set())
  const [promptAgentId, setPromptAgentId] = useState('')
  const [isGenerating, setIsGenerating] = useState(false)
  const [pushingIds, setPushingIds] = useState<Set<string>>(new Set())

  const [metricSelectedAIProvider, setMetricSelectedAIProvider] = useState<ModelProvider | null>(
    null
  )
  const [metricSelectedModel, setMetricSelectedModel] = useState('')
  const [metricLlmConfig, setMetricLlmConfig] = useState<LLMGenerationConfig | null>(null)
  const [showMetricProviderDropdown, setShowMetricProviderDropdown] = useState(false)
  const metricProviderDropdownRef = useRef<HTMLDivElement>(null)

  const configuredProviders = useMemo(
    () =>
      aiProviders.filter((p) => p.is_active).map((p) => p.provider as ModelProvider),
    [aiProviders]
  )

  const { data: metricModelOptions } = useQuery({
    queryKey: ['model-options', metricSelectedAIProvider],
    queryFn: () => apiClient.getModelOptions(metricSelectedAIProvider!),
    enabled: open && !!metricSelectedAIProvider,
  })

  const metricLlmModels = useMemo(() => metricModelOptions?.llm || [], [metricModelOptions])

  const metricSelectedAiCredential = useMemo(() => {
    if (!metricSelectedAIProvider) return undefined
    return resolveActiveAIProvider(aiProviders, metricSelectedAIProvider)
  }, [aiProviders, metricSelectedAIProvider])

  const metricLlmModelResolution = useMemo(() => {
    if (!metricSelectedAiCredential) {
      return { mode: 'catalog' as const, models: metricLlmModels }
    }
    return resolveLLMModelsForCredential(metricSelectedAiCredential, metricLlmModels)
  }, [metricSelectedAiCredential, metricLlmModels])

  const selectableMetricLlmModels =
    metricLlmModelResolution.mode === 'catalog' ? metricLlmModelResolution.models : []

  const metricGatewayDirectModel =
    metricLlmModelResolution.mode === 'gateway_direct' ? metricLlmModelResolution.model : null

  const includedDrafts = useMemo(
    () => drafts.filter((d) => includedIds.has(d.id)),
    [drafts, includedIds]
  )

  const promptAgent = useMemo(
    () => agents.find((a) => a.id === promptAgentId),
    [agents, promptAgentId]
  )

  useEffect(() => {
    if (!open) return
    const nextDrafts = scenarios.map(scenarioToMetricWorkflowDraft)
    setDrafts(nextDrafts)
    const initialIncluded = new Set(nextDrafts.slice(0, MAX_SCENARIO_METRICS_BATCH).map((d) => d.id))
    setIncludedIds(initialIncluded)

    const linkedAgent =
      defaultAgentId ||
      scenarios.find((s) => s.agent_id)?.agent_id ||
      ''
    setPromptAgentId(linkedAgent)
    setMetricSelectedAIProvider(null)
    setMetricSelectedModel('')
    setMetricLlmConfig(null)
    setIsGenerating(false)
    setPushingIds(new Set())
  }, [open, scenarios, defaultAgentId])

  useEffect(() => {
    if (metricGatewayDirectModel) {
      setMetricSelectedModel(metricGatewayDirectModel)
    } else if (
      metricSelectedModel &&
      !selectableMetricLlmModels.includes(metricSelectedModel)
    ) {
      setMetricSelectedModel('')
    } else if (!metricSelectedAIProvider) {
      setMetricSelectedModel('')
    }
  }, [
    metricSelectedAIProvider,
    selectableMetricLlmModels,
    metricGatewayDirectModel,
    metricSelectedModel,
  ])

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (
        metricProviderDropdownRef.current &&
        !metricProviderDropdownRef.current.contains(event.target as Node)
      ) {
        setShowMetricProviderDropdown(false)
      }
    }
    if (showMetricProviderDropdown) {
      document.addEventListener('mousedown', handleClickOutside)
    }
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [showMetricProviderDropdown])

  const resolveAgentProductionPrompt = (agent: AgentOption) => {
    const chatAgent = isChatMedium(agent.call_medium)
    return (
      chatAgent
        ? (agent.provider_prompt || agent.description || '').trim()
        : (agent.description || '').trim()
    )
  }

  const toggleIncluded = (draftId: string) => {
    setIncludedIds((prev) => {
      const next = new Set(prev)
      if (next.has(draftId)) {
        if (next.size <= 1) {
          showToast('Select at least one scenario', 'error')
          return prev
        }
        next.delete(draftId)
        return next
      }
      if (next.size >= MAX_SCENARIO_METRICS_BATCH) {
        showToast(`You can generate metrics for at most ${MAX_SCENARIO_METRICS_BATCH} scenarios at a time`, 'error')
        return prev
      }
      next.add(draftId)
      return next
    })
  }

  const updateDraft = (draftId: string, updates: Partial<ScenarioMetricWorkflowDraft>) => {
    setDrafts((prev) => prev.map((d) => (d.id === draftId ? { ...d, ...updates } : d)))
  }

  const updateDraftMetric = (draftId: string, updates: Partial<GeneratedScenarioMetricDraft>) => {
    setDrafts((prev) =>
      prev.map((d) =>
        d.id === draftId && d.metric ? { ...d, metric: { ...d.metric, ...updates } } : d
      )
    )
  }

  const handleGenerate = async () => {
    if (!scenarioMetricsEnabled) {
      const title = getFeatureMeta('scenario_metrics')?.title ?? 'Scenario Metrics'
      showToast(`${title} requires an EfficientAI Enterprise license.`, 'error')
      return
    }
    if (!promptAgent) {
      showToast('Select an agent to use its production prompt', 'error')
      return
    }
    if (!metricSelectedAIProvider || !metricSelectedModel) {
      showToast('Please select an AI provider and model for metric generation', 'error')
      return
    }
    if (includedDrafts.length === 0) {
      showToast('Select at least one scenario', 'error')
      return
    }

    const agentPrompt = resolveAgentProductionPrompt(promptAgent)
    if (!agentPrompt) {
      showToast('Selected agent has no production prompt', 'error')
      return
    }

    setIsGenerating(true)
    try {
      const response = await apiClient.generateMetricsFromScenarios({
        agent_name: promptAgent.name,
        production_prompt: agentPrompt,
        call_medium: promptAgent.call_medium,
        scenarios: includedDrafts.map((draft) => ({
          name: draft.name.trim(),
          description: draft.description.trim() || draft.name.trim(),
          goal: draft.goal?.trim() || undefined,
          metric_type: draft.plannedMetricType,
        })),
        provider: metricSelectedAIProvider,
        model: metricSelectedModel,
        ...(metricLlmConfig ? { llm_config: metricLlmConfig } : {}),
      })

      const byId = new Map(includedDrafts.map((d, i) => [d.id, response.metrics[i]]))
      setDrafts((prev) =>
        prev.map((draft) => {
          const generated = byId.get(draft.id)
          if (!generated) return draft
          return {
            ...draft,
            metricPushed: false,
            metric: {
              name: generated.name,
              description: generated.description,
              metric_type: generated.metric_type,
              custom_data_type: generated.custom_data_type,
              custom_config: generated.custom_config ?? {},
              supported_surfaces: generated.supported_surfaces,
              enabled_surfaces: generated.enabled_surfaces,
              tags: generated.tags ?? [],
            },
          }
        })
      )
      showToast(`Generated ${response.metrics.length} metric drafts`, 'success')
    } catch (error: any) {
      showToast(
        `Failed to generate metrics: ${error.response?.data?.detail || error.message}`,
        'error'
      )
    } finally {
      setIsGenerating(false)
    }
  }

  const pushMetric = async (draft: ScenarioMetricWorkflowDraft) => {
    if (!draft.metric || draft.metricPushed) return
    const agentName = promptAgent?.name?.trim() || 'Agent'
    const metric = draft.metric
    const tags = mergeRequiredMetricTags(metric.tags, agentName)

    setPushingIds((prev) => new Set(prev).add(draft.id))
    try {
      await apiClient.createMetric({
        name: metric.name.trim(),
        description: metric.description.trim() || undefined,
        metric_type: metric.metric_type,
        metric_origin: 'custom',
        supported_surfaces: metric.supported_surfaces,
        enabled_surfaces: metric.enabled_surfaces,
        custom_data_type: metric.custom_data_type ?? undefined,
        custom_config:
          metric.custom_config && Object.keys(metric.custom_config).length > 0
            ? metric.custom_config
            : undefined,
        tags,
        scope: 'workspace',
      })
      await queryClient.invalidateQueries({ queryKey: ['metrics'] })
      setDrafts((prev) =>
        prev.map((item) =>
          item.id === draft.id ? { ...item, metricPushed: true, metric: { ...metric, tags } } : item
        )
      )
      showToast(`Added metric "${metric.name}" to Metrics`, 'success')
    } catch (error: any) {
      showToast(`Failed to add metric: ${error.response?.data?.detail || error.message}`, 'error')
    } finally {
      setPushingIds((prev) => {
        const next = new Set(prev)
        next.delete(draft.id)
        return next
      })
    }
  }

  if (!open || typeof document === 'undefined') return null

  return createPortal(
    <div
      className="fixed inset-0 bg-gray-500/75 flex items-center justify-center z-[9999] p-4 sm:p-6"
      onClick={onClose}
    >
      <div
        className="bg-white rounded-xl shadow-xl w-full max-w-6xl max-h-[92vh] overflow-hidden flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="px-6 py-4 border-b border-gray-200 flex justify-between items-start gap-4 shrink-0">
          <div>
            <h3 className="text-lg font-semibold text-gray-900">Generate metrics from scenarios</h3>
            <p className="text-sm text-gray-500 mt-1">
              Create evaluation metrics from saved scenarios using an agent production prompt.
            </p>
          </div>
          <button type="button" onClick={onClose} className="text-gray-400 hover:text-gray-600 shrink-0">
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto min-h-0 p-6 space-y-5">
          {!scenarioMetricsEnabled && licenseLoaded && (
            <p className="text-xs text-amber-800 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">
              {getFeatureMeta('scenario_metrics')?.title ?? 'Scenario Metrics'} is an Enterprise
              feature. Set{' '}
              <code className="font-mono text-[11px] bg-amber-100/80 px-1 rounded">
                EFFICIENTAI_LICENSE
              </code>{' '}
              on your server to generate and push metrics.
            </p>
          )}

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                Agent (production prompt) *
              </label>
              <select
                value={promptAgentId}
                onChange={(e) => setPromptAgentId(e.target.value)}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 bg-white text-sm"
              >
                <option value="">Select agent</option>
                {agents.map((agent) => (
                  <option key={agent.id} value={agent.id}>
                    {agent.name}
                  </option>
                ))}
              </select>
              <p className="text-xs text-gray-500 mt-1">
                Metrics are judged against this agent&apos;s production prompt.
              </p>
            </div>
            <div className="text-sm text-gray-600 flex items-end pb-1">
              {scenarios.length > MAX_SCENARIO_METRICS_BATCH ? (
                <p>
                  Select up to {MAX_SCENARIO_METRICS_BATCH} scenarios below ({includedIds.size}{' '}
                  selected).
                </p>
              ) : (
                <p>{scenarios.length} scenario(s) in this batch.</p>
              )}
            </div>
          </div>

          {scenarioMetricsEnabled && (
            <div className="rounded-lg border border-gray-200 bg-white p-4 space-y-4">
              <div>
                <h6 className="text-sm font-semibold text-gray-900">Metric generation model</h6>
                <p className="text-xs text-gray-500 mt-1">
                  Choose the AI provider and model used to draft metrics.
                </p>
              </div>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">AI Provider *</label>
                  <div className="relative" ref={metricProviderDropdownRef}>
                    <button
                      type="button"
                      onClick={() => setShowMetricProviderDropdown(!showMetricProviderDropdown)}
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg bg-white text-left flex items-center justify-between"
                    >
                      <div className="flex items-center gap-2">
                        {metricSelectedAIProvider && getProviderLogo(metricSelectedAIProvider) ? (
                          <img
                            src={getProviderLogo(metricSelectedAIProvider)!}
                            alt={getProviderLabel(metricSelectedAIProvider)}
                            className="w-5 h-5 object-contain"
                          />
                        ) : metricSelectedAIProvider ? (
                          <Brain className="h-5 w-5 text-primary-600" />
                        ) : null}
                        <span>
                          {metricSelectedAIProvider
                            ? getProviderLabel(metricSelectedAIProvider)
                            : 'Select an AI Provider'}
                        </span>
                      </div>
                      <ChevronDown
                        className={`h-4 w-4 text-gray-400 ${showMetricProviderDropdown ? 'rotate-180' : ''}`}
                      />
                    </button>
                    {showMetricProviderDropdown && (
                      <div className="absolute z-10 w-full mt-1 bg-white border border-gray-300 rounded-lg shadow-lg max-h-60 overflow-auto">
                        {configuredProviders.map((provider) => (
                          <button
                            key={`existing-metric-${provider}`}
                            type="button"
                            onClick={() => {
                              setMetricSelectedAIProvider(provider)
                              setShowMetricProviderDropdown(false)
                              setMetricSelectedModel('')
                            }}
                            className="w-full px-3 py-2 text-left hover:bg-gray-50 flex items-center gap-2"
                          >
                            {getProviderLogo(provider) ? (
                              <img
                                src={getProviderLogo(provider)!}
                                alt={getProviderLabel(provider)}
                                className="w-5 h-5 object-contain"
                              />
                            ) : (
                              <Brain className="h-5 w-5 text-primary-600" />
                            )}
                            {getProviderLabel(provider)}
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">Model *</label>
                  {metricGatewayDirectModel ? (
                    <div className="w-full px-3 py-2 border border-gray-300 rounded-lg bg-gray-50 text-gray-700 truncate">
                      {metricGatewayDirectModel}
                    </div>
                  ) : (
                    <select
                      value={metricSelectedModel}
                      onChange={(e) => setMetricSelectedModel(e.target.value)}
                      disabled={
                        !metricSelectedAIProvider || selectableMetricLlmModels.length === 0
                      }
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg disabled:bg-gray-100 text-sm"
                    >
                      <option value="">Select model</option>
                      {selectableMetricLlmModels.map((model) => (
                        <option key={model} value={model}>
                          {model}
                        </option>
                      ))}
                    </select>
                  )}
                </div>
                {metricSelectedAIProvider && !metricGatewayDirectModel && (
                  <div className="md:col-span-2">
                    <LLMAdvancedOptionsPanel
                      provider={metricSelectedAIProvider}
                      value={metricLlmConfig}
                      onChange={setMetricLlmConfig}
                    />
                  </div>
                )}
              </div>
              <div className="flex justify-end">
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => void handleGenerate()}
                  isLoading={isGenerating}
                  disabled={!promptAgentId || !metricSelectedAIProvider || !metricSelectedModel}
                >
                  {!scenarioMetricsEnabled && (
                    <Lock className="h-4 w-4 text-amber-600 mr-1.5" aria-hidden />
                  )}
                  <BarChart3 className="h-4 w-4 mr-1.5" aria-hidden />
                  Generate metrics
                </Button>
              </div>
            </div>
          )}

          {drafts.map((draft) => {
            const included = includedIds.has(draft.id)
            return (
              <div
                key={draft.id}
                className={`border rounded-lg p-4 ${included ? 'border-gray-200 bg-gray-50' : 'border-gray-100 bg-gray-50/50 opacity-70'}`}
              >
                {scenarios.length > 1 && (
                  <label className="flex items-center gap-2 mb-3 text-sm text-gray-700 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={included}
                      onChange={() => toggleIncluded(draft.id)}
                      className="rounded border-gray-300 text-primary-600 focus:ring-primary-500"
                    />
                    Include in generation batch
                  </label>
                )}
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 lg:gap-6 items-start">
                  <div className="space-y-3 min-w-0">
                    <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide">
                      Scenario
                    </p>
                    <p className="text-sm font-semibold text-gray-900">{draft.name}</p>
                    <div className="rounded-lg border border-gray-200 bg-white p-3 max-h-64 overflow-y-auto">
                      <ScenarioMarkdownView
                        content={draft.description}
                        emptyMessage="No description"
                        size="sm"
                      />
                    </div>
                  </div>

                  <div className="space-y-3 min-w-0 lg:border-l lg:border-gray-200 lg:pl-6">
                    <div className="flex items-center justify-between gap-2">
                      <p className="text-xs font-semibold text-primary-700 uppercase tracking-wide">
                        Metric
                      </p>
                      {draft.metricPushed && (
                        <span className="text-xs font-medium text-green-700 bg-green-50 border border-green-200 rounded-full px-2 py-0.5">
                          In Metrics
                        </span>
                      )}
                    </div>

                    {!draft.metric ? (
                      <div className="rounded-lg border border-dashed border-primary-200 bg-white p-4 space-y-3 min-h-[180px]">
                        <div>
                          <label className="block text-xs font-medium text-gray-700 mb-1">
                            Metric type to generate
                          </label>
                          <select
                            value={draft.plannedMetricType}
                            disabled={!included || !scenarioMetricsEnabled}
                            onChange={(e) =>
                              updateDraft(draft.id, {
                                plannedMetricType: e.target.value as PlannedScenarioMetricType,
                              })
                            }
                            className="w-full px-3 py-2 border border-gray-300 rounded-lg bg-white text-sm"
                          >
                            <option value="auto">Auto (LLM chooses)</option>
                            <option value="boolean">Boolean</option>
                            <option value="rating">Rating</option>
                            <option value="number">Number</option>
                            <option value="text">Text</option>
                          </select>
                        </div>
                        {!included && (
                          <p className="text-xs text-gray-500">Not included in the next generation run.</p>
                        )}
                      </div>
                    ) : (
                      <div className="rounded-lg border border-primary-200 bg-white p-3 space-y-3">
                        <input
                          type="text"
                          value={draft.metric.name}
                          disabled={draft.metricPushed}
                          onChange={(e) => updateDraftMetric(draft.id, { name: e.target.value })}
                          className="w-full px-3 py-2 border border-gray-300 rounded-lg bg-white text-sm disabled:bg-gray-100"
                          placeholder="Metric name"
                        />
                        <textarea
                          value={draft.metric.description}
                          disabled={draft.metricPushed}
                          onChange={(e) =>
                            updateDraftMetric(draft.id, { description: e.target.value })
                          }
                          rows={4}
                          className="w-full px-3 py-2 border border-gray-300 rounded-lg bg-white text-sm disabled:bg-gray-100"
                          placeholder="Rubric"
                        />
                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                          <select
                            value={draft.metric.metric_type}
                            disabled={draft.metricPushed}
                            onChange={(e) => {
                              const metric_type = e.target
                                .value as GeneratedScenarioMetricDraft['metric_type']
                              updateDraftMetric(draft.id, {
                                metric_type,
                                custom_data_type: customDataTypeForMetricType(metric_type),
                              })
                            }}
                            className="w-full px-3 py-2 border border-gray-300 rounded-lg bg-white text-sm"
                          >
                            <option value="boolean">Boolean</option>
                            <option value="rating">Rating</option>
                            <option value="number">Number</option>
                            <option value="text">Text</option>
                          </select>
                          <input
                            type="text"
                            value={draft.metric.tags.join(', ')}
                            disabled={draft.metricPushed}
                            onChange={(e) =>
                              updateDraftMetric(draft.id, {
                                tags: e.target.value
                                  .split(',')
                                  .map((t) => t.trim())
                                  .filter(Boolean),
                              })
                            }
                            className="w-full px-3 py-2 border border-gray-300 rounded-lg bg-white text-sm"
                            placeholder="Tags"
                          />
                        </div>
                        {!draft.metricPushed && scenarioMetricsEnabled && (
                          <div className="flex justify-end">
                            <Button
                              type="button"
                              variant="primary"
                              isLoading={pushingIds.has(draft.id)}
                              disabled={!draft.metric.name.trim()}
                              onClick={() => void pushMetric(draft)}
                            >
                              Add to Metrics
                            </Button>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              </div>
            )
          })}
        </div>

        <div className="px-6 py-4 border-t border-gray-200 bg-gray-50/80 flex justify-end shrink-0">
          <Button type="button" variant="outline" onClick={onClose}>
            Close
          </Button>
        </div>
      </div>
    </div>,
    document.body
  )
}
