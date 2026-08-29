import { type ReactNode, useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ExternalLink, Loader2, X } from 'lucide-react'
import AIProviderModelPicker from '../AIProviderModelPicker'
import Button from '../Button'
import type { MetricClustersClient } from './clients'
import type {
  EvaluationMetricClustersState,
  MetricClustersRcaSummary,
  MetricFailurePolicy,
  MetricFailurePolicyMetricPreview,
  MetricClustersPanelProps,
} from './types'

const METRIC_CLUSTER_ROW_PRESETS = [25, 50, 500] as const
type MetricClusterRowPreset =
  (typeof METRIC_CLUSTER_ROW_PRESETS)[number] | 'all'

const PROVIDER_DISPLAY: Record<string, string> = {
  openai: 'OpenAI',
  anthropic: 'Anthropic',
  google: 'Google',
  deepseek: 'DeepSeek',
  groq: 'Groq',
}

function clampProseToSentences(
  text: string,
  maxSentences = 3,
  maxChars = 300,
): string {
  const trimmed = text.trim().replace(/\s*\n+\s*/g, ' ')
  if (!trimmed) return trimmed
  const sentences = trimmed.split(/(?<=[.!?])\s+/).filter(Boolean)
  let result = (sentences.length ? sentences.slice(0, maxSentences) : [trimmed])
    .join(' ')
    .trim()
  if (result.length > maxChars) {
    const cut = result.slice(0, maxChars - 3).replace(/\s+\S*$/, '')
    result = `${cut || result.slice(0, maxChars)}...`
  }
  return result
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
  client,
  defaultProvider = '',
  defaultModel = '',
  state,
  onGenerated,
  onError,
  overlayZIndexClass = 'z-50',
}: {
  open: boolean
  onClose: () => void
  client: MetricClustersClient
  defaultProvider?: string
  defaultModel?: string
  state: EvaluationMetricClustersState | null
  onGenerated: () => void
  onError?: (message: string | null) => void
  overlayZIndexClass?: string
}) {
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

  const failurePoliciesQuery = useQuery({
    queryKey: [...client.queryKeyPrefix, 'failure-policies'],
    queryFn: () => client.getFailurePolicies(),
    enabled: open,
    staleTime: 30_000,
  })

  const eligibleRowsQuery = useQuery({
    queryKey: [...client.queryKeyPrefix, 'eligible-rows'],
    queryFn: () => client.listEligibleRows({ count_only: true }),
    enabled: open,
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
      await client.generateClusters({
        force,
        regenerate: force,
        provider: pickerProvider || undefined,
        model: pickerModel || undefined,
        row_limit: rowPreset === 'all' ? undefined : rowPreset,
        failure_policies: policies,
      })
      onGenerated()
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
            disabled={generating || selectedRowCount === 0}
          >
            Generate clusters
          </Button>
        </div>
      </div>
    </div>,
    document.body,
  )
}

function RcaExecutiveBar({ pct, scaleMax }: { pct: number; scaleMax: number }) {
  const width =
    scaleMax > 0 ? Math.min(100, Math.round((pct / scaleMax) * 100)) : 0
  return (
    <div className="h-2.5 rounded-sm bg-[#e7ddd1] border border-[#d7cfc2] overflow-hidden w-full max-w-full">
      <div
        className="h-full bg-[#c7725e] rounded-sm transition-all"
        style={{ width: `${width}%` }}
      />
    </div>
  )
}

function RcaExecutiveInterpretation({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-md border border-rose-100 bg-rose-50/70 px-3 py-2.5 mt-3">
      <p className="text-[10px] font-bold uppercase tracking-wide text-rose-800 mb-1">
        Executive interpretation
      </p>
      <p className="text-xs text-gray-800 leading-relaxed">{children}</p>
    </div>
  )
}

function MetricClustersRcaSummaryPanel({
  summary,
}: {
  summary: MetricClustersRcaSummary
}) {
  const topPattern = summary.repeated_patterns[0]
  const topHotspot = summary.metric_hotspots[0]
  const maxPatternShare = Math.max(
    ...summary.repeated_patterns.map((r) => r.evidence_share_pct),
    1,
  )
  const maxHotspotRate = Math.max(
    ...summary.metric_hotspots.map((r) => r.metric_rate_pct),
    1,
  )
  const totalFlagged =
    summary.total_flagged_instances ??
    summary.metric_hotspots.reduce((sum, r) => sum + r.flagged_calls, 0)

  return (
    <article className="rounded-lg border border-gray-200 bg-[#faf7f2]/80 p-4 space-y-6">
      <div>
        <h4 className="text-base font-semibold text-gray-900">
          Executive summary — evaluation set
        </h4>
        <p className="text-xs text-gray-600 mt-1">
          Top metrics by clustered failure patterns and overall flagged rate across{' '}
          {summary.analysed_calls.toLocaleString()} analysed calls.
        </p>
      </div>

      {summary.repeated_patterns.length ? (
        <section className="space-y-2">
          <div className="border-b border-gray-200 pb-2 space-y-1">
            <h5 className="text-sm font-semibold text-gray-900">
              Repeated failure patterns
            </h5>
            <p className="text-[10px] text-gray-500 uppercase tracking-wide">
              Base: {summary.total_clusters} RCA clusters from{' '}
              {summary.total_clustered_instances.toLocaleString()} clustered instances ·{' '}
              {totalFlagged.toLocaleString()} flagged metric-call instances
            </p>
          </div>
          <div className="overflow-x-auto rounded-md border border-gray-100 bg-white max-w-full mx-auto">
            <table className="w-full table-fixed text-xs">
              <colgroup>
                <col className="w-[41%]" />
                <col className="w-[12%]" />
                <col className="w-[29%]" />
                <col className="w-[18%]" />
              </colgroup>
              <thead>
                <tr className="text-[10px] uppercase tracking-wide text-gray-500 border-b border-gray-100">
                  <th className="px-2 py-2 font-semibold text-left">Finding</th>
                  <th className="px-2 py-2 font-semibold text-center">
                    Evidence share
                  </th>
                  <th className="px-2 py-2 font-semibold text-center">Distribution</th>
                  <th className="px-2 py-2 font-semibold text-center">
                    Evidence calls
                  </th>
                </tr>
              </thead>
              <tbody>
                {summary.repeated_patterns.map((row) => (
                  <tr
                    key={row.metric_id}
                    className="border-b border-gray-50 align-top last:border-0"
                  >
                    <td className="px-2 py-2.5 text-left">
                      <p className="font-bold text-gray-900 uppercase tracking-tight text-[11px]">
                        {row.metric_name}
                      </p>
                      <p className="text-[10px] text-gray-500 mt-1 leading-snug break-words">
                        Top RCA patterns: {row.top_rca_patterns}
                      </p>
                    </td>
                    <td className="px-2 py-2.5 text-center tabular-nums font-semibold text-gray-900 align-top">
                      {row.evidence_share_pct.toFixed(1)}%
                    </td>
                    <td className="px-2 py-2.5 align-middle">
                      <RcaExecutiveBar
                        pct={row.evidence_share_pct}
                        scaleMax={maxPatternShare}
                      />
                    </td>
                    <td className="px-2 py-2.5 text-center tabular-nums text-gray-900 align-top">
                      <p className="font-semibold text-[11px]">
                        {row.evidence_calls.toLocaleString()}
                      </p>
                      <p className="text-[10px] text-gray-500 font-medium mt-0.5">
                        {row.evidence_share_pct.toFixed(1)}%
                      </p>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {topPattern ? (
            <RcaExecutiveInterpretation>
              These rows group repeated RCA failure patterns by metric so the same
              metric is not repeated across multiple rows. The largest group is{' '}
              <span className="font-semibold">{topPattern.metric_name}</span>; focus
              remediation there first using the example calls in each cluster below.
            </RcaExecutiveInterpretation>
          ) : null}
        </section>
      ) : null}

      {summary.metric_hotspots.length ? (
        <section className="space-y-2">
          <div className="flex flex-wrap items-baseline justify-between gap-2 border-b border-gray-200 pb-2">
            <h5 className="text-sm font-semibold text-gray-900">Metric hotspots</h5>
            <p className="text-[10px] text-gray-500 uppercase tracking-wide">
              Base: selected metric flags across{' '}
              {summary.analysed_calls.toLocaleString()} analysed calls
            </p>
          </div>
          <div className="overflow-x-auto rounded-md border border-gray-100 bg-white">
            <table className="w-full min-w-[520px] text-xs">
              <thead>
                <tr className="text-left text-[10px] uppercase tracking-wide text-gray-500 border-b border-gray-100">
                  <th className="px-3 py-2 font-semibold w-[42%]">Finding</th>
                  <th className="px-3 py-2 font-semibold text-right w-[14%]">
                    Metric rate
                  </th>
                  <th className="px-3 py-2 font-semibold w-[26%]">Distribution</th>
                  <th className="px-3 py-2 font-semibold text-right w-[18%]">
                    Flagged calls
                  </th>
                </tr>
              </thead>
              <tbody>
                {summary.metric_hotspots.map((row) => (
                  <tr
                    key={row.metric_id}
                    className="border-b border-gray-50 align-top last:border-0"
                  >
                    <td className="px-3 py-2.5">
                      <p className="font-bold text-gray-900 uppercase tracking-tight text-[11px]">
                        {row.metric_name}
                      </p>
                    </td>
                    <td className="px-3 py-2.5 text-right tabular-nums font-semibold text-gray-900">
                      {row.metric_rate_pct.toFixed(2)}%
                    </td>
                    <td className="px-3 py-2.5">
                      <RcaExecutiveBar
                        pct={row.metric_rate_pct}
                        scaleMax={maxHotspotRate}
                      />
                    </td>
                    <td className="px-3 py-2.5 text-right tabular-nums font-semibold text-gray-900">
                      {row.flagged_calls.toLocaleString()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {topHotspot ? (
            <RcaExecutiveInterpretation>
              Across {summary.analysed_calls.toLocaleString()} analysed calls,{' '}
              <span className="font-semibold">{topHotspot.metric_name}</span> has the
              highest metric rate at {topHotspot.metric_rate_pct.toFixed(2)}%.
            </RcaExecutiveInterpretation>
          ) : null}
        </section>
      ) : null}

      {summary.prompt_areas.length ? (
        <section className="space-y-2 pt-2 border-t border-gray-200">
          <h5 className="text-sm font-semibold text-gray-900">RCA data summary</h5>
          <p className="text-[10px] font-semibold uppercase tracking-wide text-gray-600">
            Prompt areas to inspect
          </p>
          <table className="w-full text-xs border border-gray-100 rounded-md overflow-hidden bg-white">
            <thead className="bg-gray-50 text-gray-500">
              <tr>
                <th className="text-left px-3 py-2 font-medium">Area</th>
                <th className="text-right px-3 py-2 font-medium">%</th>
              </tr>
            </thead>
            <tbody>
              {summary.prompt_areas.map((row) => (
                <tr key={row.label} className="border-t border-gray-100">
                  <td className="px-3 py-2 text-gray-800">{row.label}</td>
                  <td className="px-3 py-2 text-right tabular-nums text-gray-700">
                    {row.share_pct.toFixed(1)}%
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ) : null}

      <section className="pt-4 mt-2 border-t border-gray-200 space-y-1">
        <h5 className="text-sm font-semibold text-gray-900">Appendix: What is a cluster?</h5>
        <p className="text-xs text-gray-600 leading-relaxed">
          A cluster groups flagged calls that share the same underlying failure theme within
          a quality metric. Each cluster is labeled with an RCA pattern name and an
          engineering gap type (such as MISSING, LOGIC_GAP, UNDERSPEC, or
          EXISTS_NO_TRIGGER). Evidence share is the percentage of all clustered failure
          instances attributed to that metric&apos;s patterns; evidence calls is the raw
          count of those instances.
        </p>
      </section>
    </article>
  )
}

export function MetricClustersPanel({
  client,
  defaultProvider = '',
  defaultModel = '',
  state,
  isLoading,
  onGenerated,
}: MetricClustersPanelProps) {
  const [cancelling, setCancelling] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [pickerProvider, setPickerProvider] = useState('')
  const [pickerModel, setPickerModel] = useState('')
  const [llmPickerTouched, setLlmPickerTouched] = useState(false)
  const [clusterActionModalOpen, setClusterActionModalOpen] = useState(false)

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

  const selectedCountLabel = state?.selected_evaluation_row_ids?.length

  const clusterGenerationModal = (
    <MetricClusterGenerationModal
      open={clusterActionModalOpen}
      onClose={() => {
        setClusterActionModalOpen(false)
        setError(null)
      }}
      client={client}
      defaultProvider={defaultProvider}
      defaultModel={defaultModel}
      state={state}
      onGenerated={onGenerated}
      onError={setError}
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
    const completed = progress?.completed_llm_calls ?? 0
    const total = progress?.total_llm_calls ?? 0
    const pct = total > 0 ? Math.min(100, Math.round((completed / total) * 100)) : 0
    const providerLabel = state.provider
      ? PROVIDER_DISPLAY[state.provider] || state.provider
      : null
    const callsLabel = selectedCountLabel
      ? `${selectedCountLabel} selected call${selectedCountLabel === 1 ? '' : 's'}`
      : 'flagged calls'
    return (
      <>
        <section className="rounded-lg border border-amber-200 bg-amber-50/60 px-4 py-3">
          <div className="flex items-center justify-between gap-3 flex-wrap mb-2">
            <p className="text-xs font-semibold text-gray-900 inline-flex items-center gap-1.5">
              <Loader2 className="h-3.5 w-3.5 animate-spin text-amber-600" />
              Failure diagnostics — generating clusters
            </p>
            {total > 0 ? (
              <p className="text-[10px] text-gray-600 tabular-nums">
                {completed} / {total} LLM calls ({pct}%)
              </p>
            ) : null}
          </div>
          <p className="text-xs text-amber-800 mb-2">
            Clustering {callsLabel} for each enabled quality metric.
          </p>
          {total > 0 ? (
            <div className="mb-2">
              <div className="h-2.5 rounded-full bg-amber-100 overflow-hidden">
                <div
                  className="h-full bg-amber-600 transition-all duration-300"
                  style={{ width: `${pct}%` }}
                  role="progressbar"
                  aria-valuenow={completed}
                  aria-valuemin={0}
                  aria-valuemax={total}
                  aria-label="Cluster generation progress"
                />
              </div>
            </div>
          ) : (
            <div className="mb-2 h-2.5 rounded-full bg-amber-100 overflow-hidden">
              <div className="h-full w-1/3 bg-amber-400 animate-pulse rounded-full" />
            </div>
          )}
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
      </>
    )
  }

  if (state?.status === 'cancelled') {
    return (
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
        <div className="mt-3">
          <Button
            variant="primary"
            onClick={() => setClusterActionModalOpen(true)}
            disabled={cancelling}
          >
            Generate clusters
          </Button>
        </div>
        {clusterGenerationModal}
      </section>
    )
  }

  if (state?.status === 'failed') {
    return (
      <section className="rounded-lg border border-red-200 bg-red-50/50 px-4 py-3">
        <p className="text-sm font-semibold text-gray-900 mb-1">
          Failure diagnostics failed
        </p>
        <p className="text-sm text-red-700">
          {state.error_message || 'Cluster generation failed.'}
        </p>
        <div className="mt-3">
          <Button
            variant="outline"
            onClick={() => setClusterActionModalOpen(true)}
          >
            Retry
          </Button>
        </div>
        {clusterGenerationModal}
      </section>
    )
  }

  if (!state || state.status === 'idle' || !state.groups.length) {
    return (
      <section className="rounded-lg border border-dashed border-gray-200 bg-gray-50/60 p-4">
        <div className="mb-3">
          <h3 className="text-base font-semibold text-gray-900 mb-1">
            Failure diagnostics (internal)
          </h3>
          <p className="text-sm text-gray-600">
            Choose which flagged calls to include, then cluster per enabled
            quality metric (gap labels: LOGIC_GAP, UNDERSPEC, EXISTS_NO_TRIGGER,
            MISSING).
          </p>
        </div>
        <div className="flex items-center justify-end gap-2">
          <Button
            variant="primary"
            onClick={() => setClusterActionModalOpen(true)}
            disabled={cancelling}
          >
            Generate clusters
          </Button>
        </div>
        {clusterGenerationModal}
      </section>
    )
  }

  return (
    <section className="space-y-4">
      <article className="rounded-lg border border-gray-200 bg-gray-50/40 p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h3 className="text-base font-semibold text-gray-900">Generation</h3>
          <Button
            variant="primary"
            className="shrink-0"
            onClick={() => setClusterActionModalOpen(true)}
          >
            Generate clusters
          </Button>
        </div>
        <div className="mt-2 space-y-1 min-w-0">
          <p className="text-sm text-gray-600">
            Select the calls and model in a modal, then generate clusters.
            Run again after more rows complete or when you change the model.
          </p>
          {state.overview ? (
            <p className="text-sm text-gray-600 break-words">
              {clampProseToSentences(state.overview)}
            </p>
          ) : null}
          {state.is_stale ? (
            <p className="text-sm text-amber-700">
              More rows completed since clusters were generated. Generate again
              to refresh.
            </p>
          ) : null}
          {state.selected_evaluation_row_ids?.length ? (
            <p className="text-[10px] text-gray-500">
              Based on {state.selected_evaluation_row_ids.length} selected call
              {state.selected_evaluation_row_ids.length === 1 ? '' : 's'}.
            </p>
          ) : null}
        </div>
        {error ? <p className="text-sm text-red-600 mt-2">{error}</p> : null}
      </article>

      {clusterGenerationModal}

      <article className="rounded-lg border border-gray-200 bg-white p-4 space-y-4">
        <div>
          <h3 className="text-base font-semibold text-gray-900">Results</h3>
          <p className="text-sm text-gray-600 mt-1">
            Per-metric clusters of flagged calls with gap labels and Level-2
            sub-categories.
          </p>
        </div>
        {state.rca_summary ? (
          <MetricClustersRcaSummaryPanel summary={state.rca_summary} />
        ) : null}
        {state.groups.map((group) => {
          const topClusters = [...group.clusters]
            .sort((a, b) => b.count - a.count || a.label.localeCompare(b.label))
            .slice(0, 5)
          return (
          <article
            key={group.metric_id}
            className="rounded-lg border border-gray-200 bg-white overflow-hidden"
          >
            <div className="px-4 py-3 border-b border-gray-100 bg-gray-50/80">
              <h4 className="text-base font-semibold text-gray-900">
                {group.metric_name}
              </h4>
              <p className="text-xs text-gray-500">
                {group.flagged_count} flagged calls · {topClusters.length}
                {group.clusters.length > 5
                  ? ` of ${group.clusters.length}`
                  : ''}{' '}
                cluster(s) shown
                {state.failure_policies?.[group.metric_id] ? (
                  <>
                    {' '}
                    · failure:{' '}
                    {[
                      ...(state.failure_policies[group.metric_id]
                        .failure_values || []),
                      ...(state.failure_policies[group.metric_id]
                        .failure_child_names || []),
                    ].join(', ') || 'numeric rule'}
                  </>
                ) : null}
              </p>
              {group.failure_reason ? (
                <p className="text-xs text-gray-600 mt-1">
                  <span className="font-semibold text-gray-700">Why flagged:</span>{' '}
                  {group.failure_reason}
                </p>
              ) : null}
            </div>
            <div className="p-4 space-y-3">
              {(() => {
                const categorizedCalls = topClusters.reduce(
                  (sum, cluster) => sum + Math.max(0, cluster.count || 0),
                  0,
                )
                const totalFlagged = Math.max(0, group.flagged_count || 0)
                return (
                  <div className="rounded-md border border-gray-100 bg-gray-50/60 p-3">
                    <div className="flex items-center justify-between gap-2">
                      <p className="text-xs font-semibold text-gray-700 uppercase tracking-wide">
                        Cluster breakdown
                      </p>
                      <span className="text-xs font-semibold text-gray-700">
                        {categorizedCalls} / {totalFlagged}
                      </span>
                    </div>
                  </div>
                )
              })()}
              {topClusters.map((cluster) => {
                const exampleHref = client.buildEvidenceHref(cluster.evidence)
                return (
                <div
                  key={cluster.id}
                  className="rounded-md border border-gray-100 p-3"
                >
                  <div className="flex items-start justify-between gap-2">
                    <p className="text-sm font-semibold text-gray-900">
                      {cluster.label}
                    </p>
                    <span className="text-xs font-bold uppercase text-primary-700">
                      {cluster.gap_label.replace(/_/g, ' ')}
                    </span>
                  </div>
                  <p className="text-xs text-gray-600 mt-0.5">
                    {cluster.count} calls · {cluster.share_pct.toFixed(1)}% share
                  </p>
                  {cluster.failure_reason ? (
                    <p className="text-xs text-gray-600 mt-1">
                      <span className="font-semibold">Why flagged:</span>{' '}
                      {cluster.failure_reason}
                    </p>
                  ) : null}
                  {group.flagged_count > 0 ? (
                    <div className="mt-2">
                      <div className="h-2.5 w-full rounded bg-primary-100 overflow-hidden">
                        <div
                          className="h-full rounded bg-primary-500"
                          style={{
                            width: `${Math.min(
                              100,
                              (cluster.count / group.flagged_count) * 100,
                            ).toFixed(1)}%`,
                          }}
                        />
                      </div>
                    </div>
                  ) : null}
                  {cluster.observation ? (
                    <p className="text-sm text-gray-700 mt-2">
                      {cluster.observation}
                    </p>
                  ) : null}
                  {cluster.sub_clusters.length ? (
                    <ul className="mt-2 text-xs text-gray-600 list-disc pl-4">
                      {cluster.sub_clusters.map((sub) => (
                        <li key={sub.label}>
                          {sub.label} — {sub.count} ({sub.share_pct.toFixed(1)}%)
                        </li>
                      ))}
                    </ul>
                  ) : null}
                  {(cluster.evidence.quote ||
                    cluster.evidence.turns?.length ||
                    cluster.evidence.conversation_id) ? (
                    <div className="mt-2 rounded-md bg-gray-50 border border-gray-100 p-2 space-y-1">
                      <p className="text-[10px] font-semibold uppercase tracking-wide text-gray-600">
                        Example call
                      </p>
                      {cluster.evidence.turns?.length ? (
                        cluster.evidence.turns.map((turn, i) => (
                          <p key={i} className="text-xs text-gray-800">
                            <span className="font-semibold text-primary-700">
                              {turn.speaker}:
                            </span>{' '}
                            {turn.text}
                          </p>
                        ))
                      ) : cluster.evidence.quote ? (
                        <p className="text-xs text-gray-800">{cluster.evidence.quote}</p>
                      ) : null}
                      {exampleHref && cluster.evidence.conversation_id ? (
                        <Link
                          to={exampleHref}
                          className="inline-flex items-center gap-1 text-xs font-medium text-primary-700 hover:text-primary-800"
                        >
                          <ExternalLink className="h-3 w-3" />
                          {cluster.evidence.conversation_id}
                        </Link>
                      ) : cluster.evidence.conversation_id ? (
                        <p className="text-[10px] text-gray-500 font-mono">
                          {cluster.evidence.conversation_id}
                        </p>
                      ) : null}
                    </div>
                  ) : null}
                </div>
              )})}
            </div>
          </article>
        )})}
        {state.discovered_problems.length ? (
          <article className="rounded-lg border border-dashed border-primary-200 bg-primary-50/30 p-4">
            <h4 className="text-base font-semibold text-gray-900 mb-2">
              Proactive problem discovery
            </h4>
            <div className="space-y-2">
              {state.discovered_problems.map((item) => (
                <div key={item.id} className="text-sm text-gray-800">
                  <span className="font-semibold">{item.label}</span>
                  <span className="text-primary-700 ml-2 uppercase text-xs font-semibold">
                    {item.gap_label.replace(/_/g, ' ')}
                  </span>
                  <span className="text-gray-500 ml-2">
                    {item.count} · {item.share_pct.toFixed(1)}%
                  </span>
                  {item.observation ? (
                    <p className="mt-1 text-gray-600">{item.observation}</p>
                  ) : null}
                </div>
              ))}
            </div>
          </article>
        ) : null}
      </article>
    </section>
  )
}

export default MetricClustersPanel

export type { MetricClustersPanelProps }
