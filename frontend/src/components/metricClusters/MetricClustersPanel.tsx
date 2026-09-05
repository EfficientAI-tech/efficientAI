import { useEffect, useMemo, useState } from 'react'
import { createPortal } from 'react-dom'
import { useQuery } from '@tanstack/react-query'
import { Loader2, X } from 'lucide-react'
import AIProviderModelPicker from '../AIProviderModelPicker'
import Button from '../Button'
import ResultsDateRangePicker from '../../pages/evaluators/results/ResultsDateRangePicker'
import {
  dateRangeToSinceUntil,
} from '../../pages/evaluators/results/resultsDateRange'
import ClusterReportDetailsTab from './ClusterReportDetailsTab'
import ClusterReportVisualizationTab from './ClusterReportVisualizationTab'
import type { MetricClustersClient, EvaluatorResultClusterScope } from './clients'
import {
  createEvaluatorResultsMetricClustersClient,
} from './clients'
import { useWorkspaceStore } from '../../store/workspaceStore'
import type {
  EvaluationMetricClustersState,
  MetricFailurePolicy,
  MetricFailurePolicyMetricPreview,
  EvaluatorResultsAgentSummary,
  MetricClustersPanelProps,
  ClusterReportView,
} from './types'

const METRIC_CLUSTER_ROW_PRESETS = [25, 50, 500] as const
type MetricClusterRowPreset =
  (typeof METRIC_CLUSTER_ROW_PRESETS)[number] | 'all'

function scenariosForAgent(agent: EvaluatorResultsAgentSummary) {
  const seen = new Map<string, string>()
  for (const suite of agent.suites ?? []) {
    for (const scenario of suite.scenarios ?? []) {
      seen.set(scenario.scenario_id, scenario.scenario_name)
    }
  }
  return [...seen.entries()]
    .map(([id, name]) => ({ id, name }))
    .sort((a, b) => a.name.localeCompare(b.name))
}

function clusterScopeToApi(scope: {
  agentId: string
  scenarioIds: string[]
  startDate: string | null
  endDate: string | null
}): EvaluatorResultClusterScope {
  const out: EvaluatorResultClusterScope = { agentId: scope.agentId }
  if (scope.scenarioIds.length) out.scenarioIds = scope.scenarioIds
  if (scope.startDate && scope.endDate) {
    const bounds = dateRangeToSinceUntil(scope.startDate, scope.endDate)
    out.since = bounds.since
    out.until = bounds.until
  }
  return out
}

const PROVIDER_DISPLAY: Record<string, string> = {
  openai: 'OpenAI',
  anthropic: 'Anthropic',
  google: 'Google',
  deepseek: 'DeepSeek',
  groq: 'Groq',
}

function metricClusterSelectedCount(
  totalEligible: number,
  preset: MetricClusterRowPreset,
): number {
  if (totalEligible <= 0) return 0
  if (preset === 'all') return totalEligible
  return Math.min(preset, totalEligible)
}

function MetricClusterRowPicker({
  totalEligible,
  preset,
  onChangePreset,
  disabled,
}: {
  totalEligible: number
  preset: MetricClusterRowPreset
  onChangePreset: (next: MetricClusterRowPreset) => void
  disabled?: boolean
}) {
  const selectedCount = metricClusterSelectedCount(totalEligible, preset)

  const presetActive = (n: number) =>
    preset !== 'all' && preset === n && selectedCount === n

  const allActive = preset === 'all' && totalEligible > 0

  const presetButtonClass = (active: boolean) =>
    'rounded-full px-2 py-0.5 border text-[10px] font-medium transition-colors disabled:opacity-40 ' +
    (active
      ? 'border-primary-300 bg-primary-50 text-primary-800'
      : 'border-gray-200 bg-white text-gray-600 hover:border-gray-300 hover:bg-gray-50')

  return (
    <div className="rounded-md border border-gray-200 bg-white">
      <div className="px-3 py-3 border-b border-gray-100 bg-gray-50/80 space-y-2">
        <div className="flex items-center justify-between gap-2">
          <p className="text-xs font-medium text-gray-700">
            Calls to include ({selectedCount} / {totalEligible} eligible)
          </p>
        </div>
        {totalEligible > 0 ? (
          <div className="flex flex-wrap items-center gap-1.5">
            {METRIC_CLUSTER_ROW_PRESETS.map((n) => (
              <button
                key={n}
                type="button"
                disabled={disabled}
                className={presetButtonClass(presetActive(n))}
                onClick={() => onChangePreset(n)}
              >
                First {n}
              </button>
            ))}
            <button
              type="button"
              disabled={disabled}
              className={presetButtonClass(allActive)}
              onClick={() => onChangePreset('all')}
            >
              All {totalEligible}
            </button>
          </div>
        ) : (
          <p className="text-xs text-gray-500">
            No completed calls with a flagged quality metric yet.
          </p>
        )}
      </div>
    </div>
  )
}

function normalizeFailureLabel(label: string): string {
  return label.trim().toLowerCase()
}

function failureRowCountForPreview(
  preview: MetricFailurePolicyMetricPreview,
  policy: MetricFailurePolicy,
): number {
  if (preview.is_multi_label_parent) {
    let total = 0
    for (const name of policy.failure_child_names || []) {
      total += preview.row_count_by_value[name] ?? 0
    }
    return total
  }
  let total = 0
  const targets = new Set(
    (policy.failure_values || []).map((v) => normalizeFailureLabel(v)),
  )
  for (const [label, count] of Object.entries(preview.row_count_by_value)) {
    if (targets.has(normalizeFailureLabel(label))) {
      total += count
    }
  }
  return total
}

function policyHasFailureCriteria(
  preview: MetricFailurePolicyMetricPreview,
  policy: MetricFailurePolicy,
): boolean {
  if (preview.is_multi_label_parent) {
    return (policy.failure_child_names?.length ?? 0) > 0
  }
  if (policy.numeric_rule) return true
  return (policy.failure_values?.length ?? 0) > 0
}

function MetricFailurePolicyEditor({
  previews,
  policies,
  policiesSource,
  onChangePolicies,
  disabled,
}: {
  previews: MetricFailurePolicyMetricPreview[]
  policies: Record<string, MetricFailurePolicy>
  policiesSource: 'inferred' | 'user'
  onChangePolicies: (next: Record<string, MetricFailurePolicy>) => void
  disabled?: boolean
}) {
  if (!previews.length) {
    return (
      <p className="text-xs text-gray-500">
        No quality metrics available for failure policy configuration.
      </p>
    )
  }

  return (
    <div className="space-y-3">
      <div>
        <p className="text-xs font-medium text-gray-800">
          Failure values per metric
        </p>
        <p className="text-[10px] text-gray-500 mt-0.5">
          Select which answers count as failures for metrics you want to cluster.
          Metrics with none selected, or with no matching calls, are skipped.{' '}
          {policiesSource === 'inferred' ? (
            <span className="text-amber-700">
              Suggested defaults only where matching rows exist.
            </span>
          ) : (
            <span className="text-green-700">Saved for this evaluation.</span>
          )}
        </p>
      </div>
      {previews.map((preview) => {
        const policy =
          policies[preview.metric_id] ?? preview.effective_policy
        const failureCount = failureRowCountForPreview(preview, policy)
        const hasCriteria = policyHasFailureCriteria(preview, policy)
        const isSkipped = !hasCriteria || failureCount === 0

        const toggleValue = (label: string, checked: boolean) => {
          const norm = normalizeFailureLabel(label)
          const current = new Set(
            (policy.failure_values || []).map(normalizeFailureLabel),
          )
          if (checked) current.add(norm)
          else current.delete(norm)
          const nextValues = preview.value_counts
            .map((vc) => vc.label)
            .filter((l) => current.has(normalizeFailureLabel(l)))
          onChangePolicies({
            ...policies,
            [preview.metric_id]: {
              ...policy,
              metric_id: preview.metric_id,
              failure_values: nextValues.map(normalizeFailureLabel),
            },
          })
        }

        const toggleChild = (name: string, checked: boolean) => {
          const current = new Set(policy.failure_child_names || [])
          if (checked) current.add(name)
          else current.delete(name)
          onChangePolicies({
            ...policies,
            [preview.metric_id]: {
              ...policy,
              metric_id: preview.metric_id,
              failure_child_names: Array.from(current),
            },
          })
        }

        return (
          <div
            key={preview.metric_id}
            className="rounded-md border border-gray-200 bg-gray-50/50 p-3"
          >
            <div className="flex items-start justify-between gap-2 mb-2">
              <p className="text-sm font-semibold text-gray-900">
                {preview.metric_name}
              </p>
              <span
                className={`text-[10px] font-medium px-2 py-0.5 rounded-full ${
                  isSkipped
                    ? 'bg-gray-100 text-gray-600'
                    : 'bg-primary-50 text-primary-800'
                }`}
              >
                {isSkipped
                  ? 'Skipped — no matching calls'
                  : `${failureCount} call${failureCount === 1 ? '' : 's'} to cluster`}
              </span>
            </div>
            {preview.is_multi_label_parent ? (
              <div className="flex flex-wrap gap-2">
                {preview.child_names.map((name) => {
                  const checked = (policy.failure_child_names || []).includes(
                    name,
                  )
                  const count = preview.row_count_by_value[name] ?? 0
                  return (
                    <label
                      key={name}
                      className="inline-flex items-center gap-1.5 text-xs text-gray-700"
                    >
                      <input
                        type="checkbox"
                        checked={checked}
                        disabled={disabled}
                        onChange={(e) =>
                          toggleChild(name, e.target.checked)
                        }
                      />
                      {name}
                      <span className="text-gray-400">({count})</span>
                    </label>
                  )
                })}
              </div>
            ) : preview.value_counts.length ? (
              <div className="flex flex-wrap gap-2">
                {preview.value_counts.map((vc) => {
                  const checked = (policy.failure_values || []).some(
                    (v) =>
                      normalizeFailureLabel(v) ===
                      normalizeFailureLabel(vc.label),
                  )
                  return (
                    <label
                      key={vc.label}
                      className="inline-flex items-center gap-1.5 text-xs text-gray-700"
                    >
                      <input
                        type="checkbox"
                        checked={checked}
                        disabled={disabled}
                        onChange={(e) => toggleValue(vc.label, e.target.checked)}
                      />
                      {vc.label}
                      <span className="text-gray-400">({vc.count})</span>
                    </label>
                  )
                })}
              </div>
            ) : policy.numeric_rule ? (
              <p className="text-xs text-gray-600">
                Numeric failures: score {policy.numeric_rule.op}{' '}
                {policy.numeric_rule.threshold}
                {preview.metric_type ? ` (${preview.metric_type})` : ''}
              </p>
            ) : (
              <p className="text-xs text-gray-500">No observed values yet.</p>
            )}
          </div>
        )
      })}
    </div>
  )
}

function MetricClusterGenerationModal({
  open,
  onClose,
  client: initialClient,
  defaultProvider = '',
  defaultModel = '',
  state,
  onGenerated,
  onError,
  overlayZIndexClass = 'z-50',
  evaluatorScope,
}: {
  open: boolean
  onClose: () => void
  client: MetricClustersClient
  defaultProvider?: string
  defaultModel?: string
  state: EvaluationMetricClustersState | null
  onGenerated: (nextState?: EvaluationMetricClustersState, scope?: EvaluatorResultClusterScope) => void
  onError?: (message: string | null) => void
  overlayZIndexClass?: string
  evaluatorScope?: MetricClustersPanelProps['evaluatorScope']
}) {
  const activeWorkspaceId = useWorkspaceStore((s) => s.activeWorkspaceId)
  const [generating, setGenerating] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [pickerProvider, setPickerProvider] = useState('')
  const [pickerModel, setPickerModel] = useState('')
  const [rowPreset, setRowPreset] = useState<MetricClusterRowPreset>(25)
  const [llmPickerTouched, setLlmPickerTouched] = useState(false)
  const [policies, setPolicies] = useState<Record<string, MetricFailurePolicy>>(
    {},
  )
  const [policiesSource, setPoliciesSource] = useState<'inferred' | 'user'>(
    'inferred',
  )
  const [policiesTouched, setPoliciesTouched] = useState(false)
  const [draftAgentId, setDraftAgentId] = useState('')
  const [draftScenarioIds, setDraftScenarioIds] = useState<string[]>([])
  const [draftStartDate, setDraftStartDate] = useState<string | null>(null)
  const [draftEndDate, setDraftEndDate] = useState<string | null>(null)

  useEffect(() => {
    if (!open || !evaluatorScope) return
    const existing = evaluatorScope.scope
    setDraftAgentId(existing?.agentId ?? '')
    setDraftScenarioIds(existing?.scenarioIds ?? [])
    if (existing?.since && existing?.until) {
      setDraftStartDate(existing.since.slice(0, 10))
      setDraftEndDate(existing.until.slice(0, 10))
    } else {
      setDraftStartDate(null)
      setDraftEndDate(null)
    }
  }, [open, evaluatorScope])

  const draftApiScope = useMemo(() => {
    if (!evaluatorScope || !draftAgentId) return null
    return clusterScopeToApi({
      agentId: draftAgentId,
      scenarioIds: draftScenarioIds,
      startDate: draftStartDate,
      endDate: draftEndDate,
    })
  }, [
    draftAgentId,
    draftEndDate,
    draftScenarioIds,
    draftStartDate,
    evaluatorScope,
  ])

  const client = useMemo(() => {
    if (draftApiScope) {
      return createEvaluatorResultsMetricClustersClient(
        draftApiScope,
        activeWorkspaceId,
      )
    }
    return initialClient
  }, [activeWorkspaceId, draftApiScope, initialClient])

  const selectedAgent = evaluatorScope?.agents.find(
    (agent) => agent.agent_id === draftAgentId,
  )
  const scenarioOptions = selectedAgent ? scenariosForAgent(selectedAgent) : []

  const failurePoliciesQuery = useQuery({
    queryKey: [...client.queryKeyPrefix, 'failure-policies'],
    queryFn: () => client.getFailurePolicies(),
    enabled: open && (!evaluatorScope || Boolean(draftAgentId)),
    staleTime: 30_000,
  })

  const eligibleRowsQuery = useQuery({
    queryKey: [...client.queryKeyPrefix, 'eligible-rows'],
    queryFn: () => client.listEligibleRows({ count_only: true }),
    enabled: open && (!evaluatorScope || Boolean(draftAgentId)),
    staleTime: 30_000,
  })

  const totalEligible = eligibleRowsQuery.data?.total ?? 0
  const selectedRowCount = metricClusterSelectedCount(totalEligible, rowPreset)

  const hasExistingClusters = !!state?.groups?.length

  useEffect(() => {
    if (!open) return
    setError(null)
    onError?.(null)
    setRowPreset(25)
  }, [open, onError])

  useEffect(() => {
    const data = failurePoliciesQuery.data
    if (!open || !data || policiesTouched) return
    setPolicies(data.policies)
    setPoliciesSource(data.source)
  }, [open, failurePoliciesQuery.data, policiesTouched])

  useEffect(() => {
    if (!open || !policiesTouched || generating) return
    const timer = window.setTimeout(() => {
      client
        .saveFailurePolicies(policies)
        .then((saved) => {
          setPoliciesSource(saved.source)
          eligibleRowsQuery.refetch()
        })
        .catch(() => {
          /* keep local edits; generate will persist */
        })
    }, 600)
    return () => window.clearTimeout(timer)
  }, [open, policies, policiesTouched, generating, client, eligibleRowsQuery])

  useEffect(() => {
    if (state?.provider) {
      setPickerProvider(state.provider)
      if (state.model) setPickerModel(state.model)
      return
    }
    if (llmPickerTouched) return
    if (defaultProvider) setPickerProvider(defaultProvider)
    if (defaultModel) setPickerModel(defaultModel)
  }, [
    state?.provider,
    state?.model,
    defaultProvider,
    defaultModel,
    llmPickerTouched,
  ])

  const reportError = (message: string | null) => {
    setError(message)
    onError?.(message)
  }

  const handleGenerate = async () => {
    if (evaluatorScope && !draftAgentId) {
      reportError('Select an agent to cluster.')
      return
    }
    if (selectedRowCount === 0) {
      reportError('Select at least one call to cluster.')
      return
    }
    const previews = failurePoliciesQuery.data?.previews ?? []
    const hasClusterableMetric = previews.some((p) => {
      const policy = policies[p.metric_id] ?? p.effective_policy
      return (
        policyHasFailureCriteria(p, policy) &&
        failureRowCountForPreview(p, policy) > 0
      )
    })
    if (!hasClusterableMetric) {
      reportError(
        'No calls match any failure policy. Select failure values on at least one metric that has matching rows.',
      )
      return
    }
    setGenerating(true)
    reportError(null)
    try {
      const force = hasExistingClusters
      const nextState = await client.generateClusters({
        force,
        regenerate: force,
        provider: pickerProvider || undefined,
        model: pickerModel || undefined,
        row_limit: rowPreset === 'all' ? undefined : rowPreset,
        failure_policies: policies,
      })
      if (evaluatorScope && draftApiScope) {
        evaluatorScope.onScopeCommit(draftApiScope)
      }
      onGenerated(nextState, draftApiScope ?? undefined)
      onClose()
    } catch (e: any) {
      reportError(
        e?.response?.data?.detail ||
          'Failed to start metric cluster generation.',
      )
    } finally {
      setGenerating(false)
    }
  }

  const handleClose = () => {
    if (generating) return
    reportError(null)
    onClose()
  }

  if (!open || typeof document === 'undefined') return null

  return createPortal(
    <div
      className={`fixed inset-0 ${overlayZIndexClass} flex items-center justify-center p-4 bg-black/40`}
    >
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-4xl max-h-[92vh] overflow-hidden flex flex-col">
        <div className="px-6 py-4 border-b border-gray-200 flex items-center justify-between">
          <div>
            <h2 className="text-lg font-semibold text-gray-900">
              Generate clusters
            </h2>
            <p className="text-sm text-gray-600 mt-0.5">
              Configure failure values per metric, choose calls, then generate
              clusters from LLM rationales.
            </p>
          </div>
          <button
            type="button"
            onClick={handleClose}
            disabled={generating}
            className="text-gray-400 hover:text-gray-600 disabled:opacity-50"
            aria-label="Close cluster generation modal"
          >
            <X className="h-5 w-5" />
          </button>
        </div>
        <div className="px-6 py-5 overflow-y-auto flex-1">
          {evaluatorScope ? (
            <div className="mb-5 space-y-4 rounded-lg border border-gray-200 bg-gray-50/70 p-4">
              <div>
                <p className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-1">
                  Cluster scope
                </p>
                <p className="text-xs text-gray-600">
                  Choose which agent, scenarios, and simulation dates to include.
                </p>
              </div>
              <label className="block text-sm">
                <span className="text-xs font-medium text-gray-500 uppercase tracking-wide">
                  Agent
                </span>
                <select
                  className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm bg-white"
                  value={draftAgentId}
                  disabled={generating}
                  onChange={(e) => {
                    setDraftAgentId(e.target.value)
                    setDraftScenarioIds([])
                    setPoliciesTouched(false)
                  }}
                >
                  <option value="">Select an agent…</option>
                  {evaluatorScope.agents.map((agent) => (
                    <option key={agent.agent_id} value={agent.agent_id}>
                      {agent.agent_name} ({agent.counts.total})
                    </option>
                  ))}
                </select>
              </label>
              {draftAgentId ? (
                <div>
                  <p className="text-xs font-medium text-gray-700 mb-2">
                    Scenarios (optional — leave all unchecked for every scenario)
                  </p>
                  {scenarioOptions.length ? (
                    <div className="flex flex-wrap gap-2 max-h-32 overflow-y-auto">
                      {scenarioOptions.map((scenario) => {
                        const checked = draftScenarioIds.includes(scenario.id)
                        return (
                          <label
                            key={scenario.id}
                            className="inline-flex items-center gap-1.5 rounded-full border border-gray-200 bg-white px-2.5 py-1 text-xs text-gray-700"
                          >
                            <input
                              type="checkbox"
                              checked={checked}
                              disabled={generating}
                              onChange={(e) => {
                                setDraftScenarioIds((prev) =>
                                  e.target.checked
                                    ? [...prev, scenario.id]
                                    : prev.filter((id) => id !== scenario.id),
                                )
                                setPoliciesTouched(false)
                              }}
                            />
                            {scenario.name}
                          </label>
                        )
                      })}
                    </div>
                  ) : (
                    <p className="text-xs text-gray-500">
                      No scenarios found for this agent yet.
                    </p>
                  )}
                </div>
              ) : null}
              <ResultsDateRangePicker
                start={draftStartDate}
                end={draftEndDate}
                onApply={(start, end) => {
                  setDraftStartDate(start)
                  setDraftEndDate(end)
                  setPoliciesTouched(false)
                }}
              />
            </div>
          ) : null}
          <div className="mb-4">
            {failurePoliciesQuery.isLoading ? (
              <p className="text-xs text-gray-500">Loading failure policies…</p>
            ) : failurePoliciesQuery.data ? (
              <MetricFailurePolicyEditor
                previews={failurePoliciesQuery.data.previews}
                policies={policies}
                policiesSource={policiesSource}
                onChangePolicies={(next) => {
                  setPoliciesTouched(true)
                  setPolicies(next)
                }}
                disabled={generating}
              />
            ) : null}
          </div>
          <div className="mb-3">
            {eligibleRowsQuery.isLoading ? (
              <p className="text-xs text-gray-500">Loading eligible calls…</p>
            ) : (
              <MetricClusterRowPicker
                totalEligible={totalEligible}
                preset={rowPreset}
                onChangePreset={setRowPreset}
                disabled={generating}
              />
            )}
          </div>
          <div className="mb-3 rounded-md border border-gray-100 bg-white/80 p-3">
            <p className="text-xs font-medium text-gray-800 mb-0.5">
              LLM for clustering
            </p>
            <p className="text-[10px] text-gray-500 mb-2">
              Provider and model used for failure signatures and cluster
              synthesis. Defaults to this evaluation&apos;s scoring LLM when
              unset.
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
              disabled={generating}
              size="sm"
            />
          </div>
          {error ? <p className="text-sm text-red-600">{error}</p> : null}
        </div>
        <div className="px-6 py-4 border-t border-gray-200 flex items-center justify-end gap-2">
          <Button variant="outline" onClick={handleClose} disabled={generating}>
            Cancel
          </Button>
          <Button
            variant="primary"
            onClick={handleGenerate}
            isLoading={generating}
            disabled={
              generating ||
              selectedRowCount === 0 ||
              (Boolean(evaluatorScope) && !draftAgentId)
            }
          >
            Generate clusters
          </Button>
        </div>
      </div>
    </div>,
    document.body,
  )
}

export function MetricClustersPanel({
  client,
  defaultProvider = '',
  defaultModel = '',
  state,
  isLoading,
  onGenerated,
  evaluatorScope,
  registerOpenGenerateModal,
  onGenerateModalOpenChange,
  activeView = 'details',
  onViewChange,
}: MetricClustersPanelProps) {
  const [cancelling, setCancelling] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [pickerProvider, setPickerProvider] = useState('')
  const [pickerModel, setPickerModel] = useState('')
  const [llmPickerTouched, setLlmPickerTouched] = useState(false)
  const [clusterActionModalOpen, setClusterActionModalOpen] = useState(false)

  const setModalOpen = (open: boolean) => {
    setClusterActionModalOpen(open)
    onGenerateModalOpenChange?.(open)
  }

  useEffect(() => {
    registerOpenGenerateModal?.(() => setModalOpen(true))
  }, [registerOpenGenerateModal])

  useEffect(() => {
    if (state?.provider) {
      setPickerProvider(state.provider)
      if (state.model) setPickerModel(state.model)
      return
    }
    if (llmPickerTouched) return
    if (defaultProvider) setPickerProvider(defaultProvider)
    if (defaultModel) setPickerModel(defaultModel)
  }, [
    state?.provider,
    state?.model,
    defaultProvider,
    defaultModel,
    llmPickerTouched,
  ])

  const llmPickerDisabled = cancelling || state?.status === 'running'

  const llmPickerBlock = (
    <div className="mb-3 rounded-md border border-gray-100 bg-white/80 p-3">
      <p className="text-xs font-medium text-gray-800 mb-0.5">
        LLM for clustering
      </p>
      <p className="text-[10px] text-gray-500 mb-2">
        Provider and model used for failure signatures and cluster synthesis.
        Defaults to this evaluation&apos;s scoring LLM when unset.
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
        disabled={llmPickerDisabled}
        size="sm"
      />
    </div>
  )

  const clusterGenerationModal = (
    <MetricClusterGenerationModal
      open={clusterActionModalOpen}
      onClose={() => {
        setModalOpen(false)
        setError(null)
      }}
      client={client}
      defaultProvider={defaultProvider}
      defaultModel={defaultModel}
      state={state}
      onGenerated={onGenerated}
      onError={setError}
      evaluatorScope={evaluatorScope}
    />
  )

  const handleCancel = async () => {
    setCancelling(true)
    setError(null)
    try {
      await client.cancelClusters()
      onGenerated()
    } catch (e: any) {
      setError(
        e?.response?.data?.detail || 'Failed to stop cluster generation.',
      )
    } finally {
      setCancelling(false)
    }
  }

  if (isLoading && !state) {
    return (
      <>
        <section className="rounded-lg border border-dashed border-gray-200 bg-gray-50/60 p-4">
          <h3 className="text-sm font-semibold text-gray-900 mb-1">
            Failure diagnostics (internal)
          </h3>
          <p className="text-xs text-gray-500 mb-3">Loading…</p>
          {llmPickerBlock}
        </section>
        {clusterGenerationModal}
      </>
    )
  }

  if (state?.status === 'running') {
    const progress = state.progress
    const selectedCountLabel = state.selected_evaluation_row_ids?.length
    const completedLlm = progress?.completed_llm_calls ?? 0
    const totalLlm = progress?.total_llm_calls ?? 0
    const completedCalls = progress?.completed_selected_calls ?? 0
    const totalCalls =
      progress?.total_selected_calls ??
      selectedCountLabel ??
      0
    const callPct =
      totalCalls > 0
        ? Math.min(100, Math.round((completedCalls / totalCalls) * 100))
        : totalLlm > 0
          ? Math.min(100, Math.round((completedLlm / totalLlm) * 100))
          : 0
    const providerLabel = state.provider
      ? PROVIDER_DISPLAY[state.provider] || state.provider
      : null
    const callsLabel = totalCalls
      ? `${totalCalls} selected call${totalCalls === 1 ? '' : 's'}`
      : 'flagged calls'
    const metricStage =
      progress?.current_metric_name &&
      progress?.total_metrics &&
      progress.total_metrics > 0
        ? `Metric ${progress.current_metric_index ?? 0} of ${progress.total_metrics}: ${progress.current_metric_name}`
        : null
    return (
      <div className="space-y-3">
        <section className="rounded-lg border border-amber-200 bg-amber-50/60 px-4 py-3">
          <div className="flex items-center justify-between gap-3 flex-wrap mb-2">
            <p className="text-xs font-semibold text-gray-900 inline-flex items-center gap-1.5">
              <Loader2 className="h-3.5 w-3.5 animate-spin text-amber-600" />
              Failure diagnostics — generating clusters
            </p>
            {totalCalls > 0 ? (
              <p className="text-[10px] text-gray-600 tabular-nums">
                {completedCalls} / {totalCalls} calls ({callPct}%)
              </p>
            ) : totalLlm > 0 ? (
              <p className="text-[10px] text-gray-600 tabular-nums">
                {completedLlm} / {totalLlm} LLM calls ({callPct}%)
              </p>
            ) : null}
          </div>
          {metricStage ? (
            <p className="text-xs text-amber-900 mb-1">{metricStage}</p>
          ) : null}
          <p className="text-xs text-amber-800 mb-2">
            Clustering {callsLabel} for each enabled quality metric.
          </p>
          {totalCalls > 0 || totalLlm > 0 ? (
            <div className="mb-2">
              <div className="h-2.5 rounded-full bg-amber-100 overflow-hidden">
                <div
                  className="h-full bg-amber-600 transition-all duration-300"
                  style={{ width: `${callPct}%` }}
                  role="progressbar"
                  aria-valuenow={completedCalls || completedLlm}
                  aria-valuemin={0}
                  aria-valuemax={totalCalls || totalLlm}
                  aria-label="Cluster generation progress"
                />
              </div>
            </div>
          ) : (
            <div className="mb-2 h-2.5 rounded-full bg-amber-100 overflow-hidden">
              <div className="h-full w-1/3 bg-amber-400 animate-pulse rounded-full" />
            </div>
          )}
          {totalLlm > 0 ? (
            <p className="text-[10px] text-gray-500 tabular-nums">
              {completedLlm} / {totalLlm} LLM calls
            </p>
          ) : null}
          {providerLabel || state.model ? (
            <p className="text-[10px] text-gray-500">
              Using {providerLabel || 'LLM'}
              {state.model ? ` · ${state.model}` : ''}
            </p>
          ) : null}
          <div className="mt-3 flex items-center gap-2">
            <Button
              variant="outline"
              onClick={handleCancel}
              isLoading={cancelling}
              disabled={cancelling}
            >
              Stop
            </Button>
          </div>
          {error ? <p className="text-xs text-red-600 mt-2">{error}</p> : null}
        </section>
        {clusterGenerationModal}
      </div>
    )
  }

  if (state?.status === 'cancelled') {
    return (
      <div className="space-y-3">
        <section className="rounded-lg border border-gray-200 bg-gray-50/80 px-4 py-3">
        <p className="text-sm font-semibold text-gray-900 mb-1">
          Failure diagnostics stopped
        </p>
        <p className="text-sm text-gray-600">
          {state.error_message ||
            'Cluster generation was cancelled. Partial results were not saved.'}
        </p>
        {state.progress ? (
          <p className="text-xs text-gray-500 mt-1">
            Stopped at {state.progress.completed_llm_calls} /{' '}
            {state.progress.total_llm_calls} LLM calls
          </p>
        ) : null}
        <p className="text-xs text-gray-600 mt-2">
          Use New report above to start again.
        </p>
        </section>
        {clusterGenerationModal}
      </div>
    )
  }

  if (state?.status === 'failed') {
    return (
      <div className="space-y-3">
        <section className="rounded-lg border border-red-200 bg-red-50/50 px-4 py-3">
        <p className="text-sm font-semibold text-gray-900 mb-1">
          Failure diagnostics failed
        </p>
        <p className="text-sm text-red-700">
          {state.error_message || 'Cluster generation failed.'}
        </p>
        <p className="text-xs text-gray-600 mt-2">
          Use New report above to try again with a different scope or configuration.
        </p>
        </section>
        {clusterGenerationModal}
      </div>
    )
  }

  if (!state || state.status === 'idle') {
    return (
      <section className="space-y-3">
        <section className="rounded-lg border border-dashed border-gray-200 bg-gray-50/60 p-4">
        <div>
          <h3 className="text-base font-semibold text-gray-900 mb-1">
            No cluster results yet
          </h3>
          <p className="text-sm text-gray-600">
            Select a cluster report above or use New report to generate clusters
            for an agent, scenario set, and date range.
          </p>
        </div>
        </section>
        {clusterGenerationModal}
      </section>
    )
  }

  if (state.status === 'completed' && !state.groups.length) {
    return (
      <section className="space-y-3">
        <section className="rounded-lg border border-amber-200 bg-amber-50/60 p-4">
          <h3 className="text-base font-semibold text-gray-900 mb-1">
            Report ready but no clusters found
          </h3>
          <p className="text-sm text-gray-600">
            Generation completed, but no failure clusters were produced for this
            scope. Try New report with different calls or failure policies.
          </p>
        </section>
        {clusterGenerationModal}
      </section>
    )
  }

  const subtabClass = (view: ClusterReportView) =>
    `px-3 py-1.5 text-xs font-medium rounded transition ${
      activeView === view
        ? 'bg-white text-primary-700 shadow-sm'
        : 'text-gray-600 hover:text-gray-900'
    }`

  return (
    <section className="space-y-4">
      {clusterGenerationModal}

      <div className="inline-flex border border-gray-200 rounded-lg p-1 bg-gray-50 w-fit">
        <button
          type="button"
          onClick={() => onViewChange?.('details')}
          className={subtabClass('details')}
        >
          Details
        </button>
        <button
          type="button"
          onClick={() => onViewChange?.('visualization')}
          className={subtabClass('visualization')}
        >
          Visualization
        </button>
      </div>

      {activeView === 'details' ? (
        <ClusterReportDetailsTab
          state={state}
          client={client}
          agents={evaluatorScope?.agents ?? []}
          urlScope={evaluatorScope?.scope ?? null}
        />
      ) : (
        <ClusterReportVisualizationTab state={state} />
      )}

      {error ? <p className="text-sm text-red-600">{error}</p> : null}
    </section>
  )
}

export default MetricClustersPanel

export type { MetricClustersPanelProps }
