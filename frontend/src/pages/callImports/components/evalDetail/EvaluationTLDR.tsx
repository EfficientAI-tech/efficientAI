import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertTriangle,
  CheckCircle2,
  Loader2,
  RefreshCw,
  Sparkles,
} from 'lucide-react'
import { apiClient } from '../../../../lib/api'
import type {
  CallImportEvaluation,
  CallImportMetricAggregate,
  EvaluationTldrSummary,
  EvaluationUserInsightsState,
} from '../../../../types/api'
import AIProviderModelPicker from '../../../../components/AIProviderModelPicker'
import { getActiveWorkspaceId } from '../../../../store/workspaceStore'
import { UserInsightsSampleSizeSelect } from './UserInsightsSampleSizeSelect'
import {
  DEFAULT_USER_INSIGHTS_SAMPLE_SIZE,
  USER_INSIGHTS_SAMPLE_SIZE_OPTIONS,
} from './userInsightsConstants'
import { clampProseToSentences, formatPct, PROVIDER_DISPLAY } from './evalDisplayUtils'

type TldrTone = 'good' | 'warn' | 'info'

function TldrStat({
  label,
  value,
  sub,
  tone = 'info',
}: {
  label: string
  value: number | string
  sub?: string | null
  tone?: TldrTone
}) {
  const valueClass =
    tone === 'good'
      ? 'text-green-700'
      : tone === 'warn'
      ? 'text-amber-700'
      : 'text-gray-900'
  return (
    <div className="rounded-lg border border-gray-100 bg-white/80 px-3 py-2 shadow-[0_1px_2px_rgba(15,23,42,0.04)]">
      <p className="text-[10px] uppercase tracking-wider text-gray-500 truncate">
        {label}
      </p>
      <p className={`text-lg font-semibold leading-tight ${valueClass}`}>
        {value}
      </p>
      {sub ? (
        <p className="text-[11px] text-gray-500 truncate">{sub}</p>
      ) : null}
    </div>
  )
}

/**
 * High-level TLDR card pinned above the Visualizations charts.
 *
 * Layout:
 *   1. Header pill - completion percent, status tone.
 *   2. Stat strip  - rows scored / top-level metrics / sub-labels / failed.
 *   3. Body        - LLM-generated narrative + bullet patterns. Hidden
 *                    behind an explicit "Generate summary" CTA so we
 *                    never auto-burn LLM tokens, with a Regenerate
 *                    affordance once a cached summary exists.
 */
function EvaluationTLDR({
  callImportId,
  evaluation,
  aggregate,
}: {
  callImportId: string
  evaluation: CallImportEvaluation
  aggregate: {
    total_rows: number
    completed_rows: number
    failed_rows: number
    metrics: CallImportMetricAggregate[]
  }
}) {
  const totalRows = aggregate.total_rows
  const completed = aggregate.completed_rows
  const failed = aggregate.failed_rows
  const completionRate =
    totalRows > 0 ? completed / totalRows : null
  const failureRate = totalRows > 0 ? failed / totalRows : null

  // Pick an overall mood for the headline pill - green when >=80% of
  // rows completed cleanly, amber when failures are non-trivial, gray
  // before any rows finish.
  let statusTone: TldrTone = 'info'
  if (completionRate != null && completionRate >= 0.8 && (failureRate ?? 0) < 0.1) {
    statusTone = 'good'
  } else if ((failureRate ?? 0) >= 0.1) {
    statusTone = 'warn'
  }

  const statusToneClass =
    statusTone === 'good'
      ? 'bg-green-100 text-green-800 border-green-200'
      : statusTone === 'warn'
      ? 'bg-amber-100 text-amber-800 border-amber-200'
      : 'bg-gray-100 text-gray-700 border-gray-200'

  // Split aggregate metrics into top-level vs sub-labels using
  // ``parent_metric_id`` from the evaluation summary. The aggregate
  // payload itself is flat (one row per metric_id, parents and
  // promoted children mixed together) so the previous "Metrics: N"
  // pill misled users by counting children as separate metrics.
  const childIdSet = new Set(
    (evaluation.metrics ?? [])
      .filter((m) => (m as any).parent_metric_id)
      .map((m) => m.id),
  )
  const topLevelCount = aggregate.metrics.filter(
    (m) => !childIdSet.has(m.metric_id),
  ).length
  const subLabelCount = Math.max(
    0,
    aggregate.metrics.length - topLevelCount,
  )

  const completionLabel =
    completionRate != null
      ? `${formatPct(completionRate)} completed`
      : 'In progress'

  return (
    <section
      aria-label="Evaluation summary (TLDR)"
      className="rounded-xl border border-primary-100 bg-gradient-to-br from-primary-50/60 via-white to-white p-4 shadow-sm"
    >
      <header className="flex items-center justify-between gap-3 flex-wrap mb-3">
        <div className="flex items-center gap-2 min-w-0">
          <span className="inline-flex items-center justify-center h-6 w-6 rounded-full bg-primary-600 text-white shadow-sm shrink-0">
            <Sparkles className="h-3.5 w-3.5" />
          </span>
          <div className="min-w-0">
            <p className="text-[10px] font-semibold uppercase tracking-wider text-primary-700">
              TLDR
            </p>
            <p className="text-sm font-semibold text-gray-900 truncate">
              At-a-glance summary
            </p>
          </div>
        </div>
        <span
          className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full border font-medium text-[11px] ${statusToneClass}`}
        >
          {statusTone === 'good' ? (
            <CheckCircle2 className="h-3 w-3" />
          ) : statusTone === 'warn' ? (
            <AlertTriangle className="h-3 w-3" />
          ) : (
            <Sparkles className="h-3 w-3" />
          )}
          {completionLabel}
        </span>
      </header>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mb-3">
        <TldrStat
          label="Rows scored"
          value={completed}
          sub={`of ${totalRows}`}
          tone={statusTone}
        />
        <TldrStat
          label="Top-level metrics"
          value={topLevelCount}
          sub={topLevelCount === 1 ? 'metric' : 'metrics'}
        />
        <TldrStat
          label="Sub-labels"
          value={subLabelCount}
          sub={subLabelCount === 1 ? 'discovered' : 'discovered'}
        />
        <TldrStat
          label="Failed"
          value={failed}
          tone={failed > 0 ? 'warn' : 'info'}
        />
      </div>

      {evaluation.status === 'pending' || evaluation.status === 'running' ? (
        <p className="text-xs text-gray-500 inline-flex items-center gap-1.5 mb-3">
          <RefreshCw className="h-3 w-3 animate-spin" />
          Results refresh automatically as workers finish each row.
        </p>
      ) : null}

      <EvaluationTLDRInsights
        callImportId={callImportId}
        evaluationId={evaluation.id}
        completedRows={completed}
        totalRows={totalRows}
      />
    </section>
  )
}

/**
 * LLM-driven body of the TLDR card. Owns the picker state + generate
 * mutation and renders one of three variants:
 *
 *   * empty -> "Get an AI-written summary..." CTA + provider/model
 *     picker + "Generate summary" button.
 *   * cached + fresh -> narrative paragraph, bulleted patterns,
 *     small footer with the model used + Regenerate text button.
 *   * cached + stale -> same as above plus an amber banner that
 *     explains how many newer rows have arrived since generation.
 */
function EvaluationTLDRInsights({
  callImportId,
  evaluationId,
  completedRows,
  totalRows,
}: {
  callImportId: string
  evaluationId: string
  completedRows: number
  totalRows: number
}) {
  const queryClient = useQueryClient()
  const [pickerProvider, setPickerProvider] = useState<string>('')
  const [pickerModel, setPickerModel] = useState<string>('')
  const [userInsightsSampleSize, setUserInsightsSampleSize] = useState<number>(
    DEFAULT_USER_INSIGHTS_SAMPLE_SIZE,
  )
  const [showPicker, setShowPicker] = useState<boolean>(false)
  const [error, setError] = useState<string | null>(null)

  const insightsQuery = useQuery<EvaluationTldrSummary | null>({
    queryKey: ['call-import-evaluation-insights', getActiveWorkspaceId(), callImportId, evaluationId],
    queryFn: () =>
      apiClient.callImports.getCallImportEvaluationInsights(callImportId, evaluationId),
    // Single shot per page-load. We refetch only after a successful
    // mutation; auto-refetching here would be misleading because the
    // backend never auto-generates the summary.
    refetchOnWindowFocus: false,
    refetchInterval: false,
  })

  const cached = insightsQuery.data ?? null

  const userInsightsStateQuery = useQuery<EvaluationUserInsightsState | null>({
    queryKey: ['call-import-evaluation-user-insights', getActiveWorkspaceId(), callImportId, evaluationId],
    queryFn: () =>
      apiClient.callImports.getCallImportEvaluationUserInsights(callImportId, evaluationId),
    refetchOnWindowFocus: false,
  })

  // Re-seed the picker with the previously-used provider/model so a
  // single click on Regenerate gives the user the same model again.
  useEffect(() => {
    if (cached?.provider && !pickerProvider) {
      setPickerProvider(cached.provider)
    }
    if (cached?.model && !pickerModel) {
      setPickerModel(cached.model)
    }
  }, [cached?.provider, cached?.model, pickerProvider, pickerModel])

  useEffect(() => {
    const sampleSize = userInsightsStateQuery.data?.max_llm_calls
    if (
      sampleSize != null &&
      USER_INSIGHTS_SAMPLE_SIZE_OPTIONS.includes(
        sampleSize as (typeof USER_INSIGHTS_SAMPLE_SIZE_OPTIONS)[number],
      )
    ) {
      setUserInsightsSampleSize(sampleSize)
    }
  }, [userInsightsStateQuery.data?.max_llm_calls])

  const generateMutation = useMutation({
    mutationFn: (regenerate: boolean) =>
      apiClient.callImports.generateCallImportEvaluationInsights(
        callImportId,
        evaluationId,
        {
          regenerate,
          provider: pickerProvider || undefined,
          model: pickerModel || undefined,
          max_llm_calls: userInsightsSampleSize,
        },
      ),
    onSuccess: (summary) => {
      queryClient.setQueryData(
        ['call-import-evaluation-insights', getActiveWorkspaceId(), callImportId, evaluationId],
        summary,
      )
      queryClient.invalidateQueries({
        queryKey: ['call-import-evaluation-user-insights', getActiveWorkspaceId(), callImportId, evaluationId],
      })
      setShowPicker(false)
      setError(null)
    },
    onError: (err: any) => {
      setError(err?.response?.data?.detail || 'Could not generate summary')
    },
  })

  const isLoading = insightsQuery.isLoading
  const isPending = generateMutation.isPending

  if (isLoading) {
    return (
      <p className="text-xs text-gray-500 inline-flex items-center gap-1.5">
        <Loader2 className="h-3 w-3 animate-spin" />
        Loading summary…
      </p>
    )
  }

  // Empty-state CTA: never-summarised yet OR an explicit "regenerate"
  // request landed us here without a cached value.
  if (!cached) {
    return (
      <div className="rounded-lg border border-dashed border-primary-200 bg-white/70 p-3">
        <div className="flex items-start gap-2 mb-2">
          <Sparkles className="h-4 w-4 text-primary-600 mt-0.5 shrink-0" />
          <div className="min-w-0">
            <p className="text-xs font-semibold text-gray-900">
              Get an AI-written summary and user insights
            </p>
            <p className="text-[11px] text-gray-500 leading-snug">
              We feed per-metric numbers + rationales to an LLM for a
              cross-call summary, and start a background job that
              analyzes rationales and diarized transcripts for External
              Audit user insights.
            </p>
          </div>
        </div>
        <div className="mt-2 mb-3 space-y-2">
          <AIProviderModelPicker
            provider={pickerProvider}
            model={pickerModel}
            onProviderChange={setPickerProvider}
            onModelChange={setPickerModel}
            disabled={isPending}
            size="sm"
          />
          <UserInsightsSampleSizeSelect
            value={userInsightsSampleSize}
            onChange={setUserInsightsSampleSize}
            disabled={isPending}
          />
        </div>
        <div className="flex items-center justify-between gap-2 flex-wrap">
          <p className="text-[10px] text-gray-400">
            Tokens are only spent when you click Generate.
          </p>
          <button
            type="button"
            onClick={() => generateMutation.mutate(false)}
            disabled={isPending}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-white bg-primary-600 rounded-md hover:bg-primary-700 disabled:opacity-60"
          >
            {isPending ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Sparkles className="h-3.5 w-3.5" />
            )}
            Generate summary
          </button>
        </div>
        {error && (
          <p className="mt-2 text-[11px] text-red-600">{error}</p>
        )}
      </div>
    )
  }

  // Cached summary - render narrative + bullets, plus a stale banner
  // and Regenerate affordance when more rows have completed since the
  // summary was written.
  const providerLabel = cached.provider
    ? PROVIDER_DISPLAY[cached.provider] || cached.provider
    : null

  return (
    <div className="rounded-lg border border-gray-100 bg-white/80 p-3 shadow-[0_1px_2px_rgba(15,23,42,0.04)]">
      {cached.is_stale && (
        <div className="mb-3 flex items-start gap-2 rounded-md border border-amber-200 bg-amber-50 px-2.5 py-1.5">
          <AlertTriangle className="h-3.5 w-3.5 text-amber-600 mt-0.5 shrink-0" />
          <div className="min-w-0 flex-1">
            <p className="text-[11px] text-amber-800">
              Generated when {cached.generated_at_completed_rows}/{totalRows}{' '}
              row{cached.generated_at_completed_rows === 1 ? '' : 's'} had
              finished. {completedRows - cached.generated_at_completed_rows}{' '}
              new row
              {completedRows - cached.generated_at_completed_rows === 1
                ? ' has'
                : 's have'}{' '}
              completed since.
            </p>
          </div>
          <button
            type="button"
            onClick={() => setShowPicker((v) => !v)}
            className="text-[11px] font-medium text-amber-800 hover:text-amber-900 underline underline-offset-2 shrink-0"
          >
            {showPicker ? 'Cancel' : 'Regenerate'}
          </button>
        </div>
      )}

      <p className="text-xs text-gray-700 leading-relaxed whitespace-pre-line">
        {clampProseToSentences(cached.narrative)}
      </p>

      <div className="mt-3 flex items-center justify-between gap-2 flex-wrap">
        <p className="text-[10px] text-gray-400 truncate">
          {providerLabel || cached.model
            ? `Generated by ${providerLabel ?? '—'}${
                cached.model ? ` · ${cached.model}` : ''
              }`
            : 'Generated by AI'}
        </p>
        {!cached.is_stale && (
          <button
            type="button"
            onClick={() => setShowPicker((v) => !v)}
            disabled={isPending}
            className="text-[11px] font-medium text-primary-700 hover:text-primary-800 underline underline-offset-2 disabled:opacity-50"
          >
            {showPicker ? 'Cancel' : 'Regenerate'}
          </button>
        )}
      </div>

      {showPicker && (
        <div className="mt-3 rounded-md border border-gray-200 bg-gray-50 p-2.5 space-y-2">
          <AIProviderModelPicker
            provider={pickerProvider}
            model={pickerModel}
            onProviderChange={setPickerProvider}
            onModelChange={setPickerModel}
            disabled={isPending}
            size="sm"
          />
          <UserInsightsSampleSizeSelect
            value={userInsightsSampleSize}
            onChange={setUserInsightsSampleSize}
            disabled={isPending}
          />
          <div className="flex items-center justify-end gap-2">
            <button
              type="button"
              onClick={() => generateMutation.mutate(true)}
              disabled={isPending}
              className="inline-flex items-center gap-1.5 px-2.5 py-1 text-[11px] font-medium text-white bg-primary-600 rounded-md hover:bg-primary-700 disabled:opacity-60"
            >
              {isPending ? (
                <Loader2 className="h-3 w-3 animate-spin" />
              ) : (
                <Sparkles className="h-3 w-3" />
              )}
              Regenerate
            </button>
          </div>
        </div>
      )}

      {error && (
        <p className="mt-2 text-[11px] text-red-600">{error}</p>
      )}
    </div>
  )
}

export { EvaluationTLDR, EvaluationTLDRInsights, TldrStat }
