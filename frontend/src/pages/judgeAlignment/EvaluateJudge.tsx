import { useState, type ReactNode } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { Play, RefreshCw, AlertCircle, HelpCircle } from 'lucide-react'
import { format } from 'date-fns'
import { apiClient } from '../../lib/api'
import type { JudgeRun } from '../../lib/api'
import Button from '../../components/Button'

const METRIC_HELP: Record<string, { title: string; body: ReactNode }> = {
  N: {
    title: 'N (sample size)',
    body: 'Number of labeled samples the judge was scored against in this run.',
  },
  F1: {
    title: 'F1 score',
    body: (
      <>
        Harmonic mean of precision and recall, ranging 0 – 1. A balanced
        single-number summary of how well the judge agrees with the human
        labels. Higher is better; ~0.8+ usually means the judge is good
        enough to ship.
      </>
    ),
  },
  Precision: {
    title: 'Precision',
    body: (
      <>
        Of the samples the judge marked <b>fail</b>, what fraction were
        actually labeled <b>fail</b> by humans. Low precision = the judge
        cries wolf (false alarms).
        <br />
        <span className="text-gray-300">precision = TP / (TP + FP)</span>
      </>
    ),
  },
  Recall: {
    title: 'Recall',
    body: (
      <>
        Of all the samples humans labeled <b>fail</b>, what fraction the
        judge caught. Low recall = the judge misses real failures.
        <br />
        <span className="text-gray-300">recall = TP / (TP + FN)</span>
      </>
    ),
  },
  Kappa: {
    title: "Cohen's κ (kappa)",
    body: (
      <>
        Inter-rater agreement between the judge and humans, corrected for
        agreement that would happen by chance. Ranges −1 to 1; 0 = chance,
        1 = perfect. Useful when the dataset is class-imbalanced and F1
        alone can be misleading.
      </>
    ),
  },
  TP: {
    title: 'True Positive',
    body: (
      <>
        Human label = <b>fail</b> AND judge predicted <b>fail</b>. The
        judge correctly caught a failure.
      </>
    ),
  },
  FP: {
    title: 'False Positive',
    body: (
      <>
        Human label = <b>pass</b> BUT judge predicted <b>fail</b>. False
        alarm — the judge is too strict.
      </>
    ),
  },
  FN: {
    title: 'False Negative',
    body: (
      <>
        Human label = <b>fail</b> BUT judge predicted <b>pass</b>. The
        judge missed a real failure.
      </>
    ),
  },
  TN: {
    title: 'True Negative',
    body: (
      <>
        Human label = <b>pass</b> AND judge predicted <b>pass</b>. The
        judge correctly let a good response through.
      </>
    ),
  },
}

function InfoTooltip({
  title,
  children,
  className = '',
}: {
  title: string
  children: ReactNode
  className?: string
}) {
  return (
    <span className={`relative inline-flex group ${className}`}>
      <HelpCircle
        className="h-3.5 w-3.5 text-gray-400 group-hover:text-gray-600 cursor-help"
        aria-label={title}
      />
      <span
        role="tooltip"
        className="pointer-events-none absolute bottom-full left-1/2 z-30 mb-2 w-64 -translate-x-1/2 rounded-md bg-gray-900 px-3 py-2 text-xs font-normal leading-snug text-white opacity-0 shadow-lg transition-opacity duration-150 group-hover:opacity-100 group-focus-within:opacity-100"
      >
        <span className="block text-[11px] font-semibold uppercase tracking-wide text-yellow-300">
          {title}
        </span>
        <span className="mt-1 block text-gray-100">{children}</span>
      </span>
    </span>
  )
}

export default function EvaluateJudge({ datasetId }: { datasetId: string }) {
  const queryClient = useQueryClient()
  const [evaluatorId, setEvaluatorId] = useState<string>('')
  const [error, setError] = useState<string | null>(null)

  const { data: evaluators = [] } = useQuery({
    queryKey: ['evaluators'],
    queryFn: () => apiClient.listEvaluators(),
  })

  const { data: models = [] } = useQuery({
    queryKey: ['judge-alignment', 'available-models'],
    queryFn: () => apiClient.listJudgeCapableModels(),
  })

  const { data: runs = [] } = useQuery({
    queryKey: ['judge-runs', datasetId],
    queryFn: () => apiClient.listJudgeRuns(datasetId),
    refetchInterval: 3000,
  })

  // Surface only custom-prompt evaluators (the only kind that can act as a judge).
  const judgeReady = evaluators.filter(
    (e: any) => e.custom_prompt && e.llm_provider && e.llm_model
  )

  const triggerMutation = useMutation({
    mutationFn: () =>
      apiClient.triggerJudgeRun(datasetId, {
        evaluator_id: evaluatorId,
        split: 'all',
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['judge-runs', datasetId] })
      setError(null)
    },
    onError: (e: any) => {
      setError(e?.response?.data?.detail || e?.message || 'Failed to start run')
    },
  })

  return (
    <div className="space-y-6">
      <div className="bg-white border border-gray-200 rounded-lg p-5">
        <h2 className="text-lg font-semibold text-gray-900 inline-flex items-center gap-2">
          Run a judge
          <InfoTooltip title="Evaluating a judge">
            Sends every labeled sample to the chosen LLM judge with your
            evaluator's <code>custom_prompt</code> as the criteria, then
            compares the judge's pass/fail predictions against your human
            labels. The result is one row in <i>Runs</i> below with
            alignment metrics (F1, precision, recall, Cohen's κ).
          </InfoTooltip>
        </h2>
        <p className="mt-1 text-sm text-gray-600">
          Pick a custom-prompt evaluator. Its <code>custom_prompt</code> is the
          criteria the judge uses; its <code>llm_provider</code> /{' '}
          <code>llm_model</code> determines which API key gets called.
        </p>

        {models.length === 0 && (
          <div className="mt-4 p-3 bg-amber-50 border border-amber-200 rounded text-sm text-amber-800 flex items-start gap-2">
            <AlertCircle className="h-4 w-4 mt-0.5 flex-shrink-0" />
            <div>
              No LLM-capable AI providers configured.{' '}
              <Link
                to="/integrations"
                className="font-medium underline hover:text-amber-900"
              >
                Add one in Integrations
              </Link>{' '}
              to populate the judge model dropdown on your evaluators.
            </div>
          </div>
        )}

        {judgeReady.length === 0 ? (
          <div className="mt-4 p-3 bg-gray-50 border border-gray-200 rounded text-sm text-gray-700">
            No custom-prompt evaluators with a model configured. Create one
            from the{' '}
            <Link
              to="/evaluate-test-agents"
              className="font-medium text-yellow-700 underline hover:text-yellow-900"
            >
              Evaluators page
            </Link>{' '}
            (set <code>custom_prompt</code>, <code>llm_provider</code>, and{' '}
            <code>llm_model</code>).
          </div>
        ) : (
          <div className="mt-4 grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="text-sm font-medium text-gray-900">
                Evaluator (judge)
              </label>
              <select
                value={evaluatorId}
                onChange={(e) => setEvaluatorId(e.target.value)}
                className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-yellow-400"
              >
                <option value="">Select an evaluator</option>
                {judgeReady.map((e: any) => (
                  <option key={e.id} value={e.id}>
                    {e.name || e.evaluator_id} - {e.llm_provider}/{e.llm_model}
                  </option>
                ))}
              </select>
            </div>
            <div className="flex items-end">
              <Button
                variant="primary"
                leftIcon={<Play className="h-4 w-4" />}
                onClick={() => triggerMutation.mutate()}
                isLoading={triggerMutation.isPending}
                disabled={!evaluatorId}
              >
                Run judge
              </Button>
            </div>
          </div>
        )}

        {error && (
          <div className="mt-3 p-3 bg-red-50 border border-red-200 rounded text-sm text-red-700">
            {error}
          </div>
        )}
      </div>

      <RunsList runs={runs} datasetId={datasetId} />
    </div>
  )
}

function RunsList({ runs, datasetId }: { runs: JudgeRun[]; datasetId: string }) {
  const queryClient = useQueryClient()

  const recompute = useMutation({
    mutationFn: (runId: string) => apiClient.recomputeJudgeRunMetrics(runId),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ['judge-runs', datasetId] }),
  })

  if (runs.length === 0) {
    return (
      <div className="bg-white border border-gray-200 rounded-lg p-6 text-sm text-gray-500 text-center">
        No runs yet. Pick an evaluator above and click "Run judge".
      </div>
    )
  }

  return (
    <div className="space-y-3">
      <h3 className="text-sm font-semibold text-gray-700 inline-flex items-center gap-1.5">
        Runs
        <InfoTooltip title="Runs">
          Each run executes the selected judge against your labeled
          samples and stores predictions + alignment metrics. Re-running
          after editing the judge prompt or switching models lets you
          A/B compare alignment.
        </InfoTooltip>
      </h3>
      {runs.map((run) => (
        <div
          key={run.id}
          className="bg-white border border-gray-200 rounded-lg p-4"
        >
          <div className="flex items-start justify-between">
            <div>
              <div className="flex items-center gap-2">
                <StatusPill status={run.status} />
                <span className="text-sm font-mono text-gray-700">
                  {run.llm_provider}/{run.llm_model}
                </span>
                <span className="text-xs text-gray-400">split: {run.split}</span>
              </div>
              {run.created_at && (
                <div className="text-xs text-gray-500 mt-1">
                  {format(new Date(run.created_at), 'MMM d, yyyy HH:mm:ss')}
                </div>
              )}
            </div>
            <Button
              variant="ghost"
              size="sm"
              leftIcon={<RefreshCw className="h-3.5 w-3.5" />}
              onClick={() => recompute.mutate(run.id)}
              disabled={!run.predictions || Object.keys(run.predictions).length === 0}
              title="Recompute metrics from existing predictions (no LLM calls)"
            >
              Recompute
            </Button>
          </div>

          {run.error_message && (
            <div className="mt-2 p-2 bg-red-50 border border-red-200 rounded text-xs text-red-700">
              {run.error_message}
            </div>
          )}

          {run.metrics && <MetricsCard metrics={run.metrics} />}
        </div>
      ))}
    </div>
  )
}

function StatusPill({ status }: { status: string }) {
  const map: Record<string, string> = {
    completed: 'bg-green-100 text-green-700',
    running: 'bg-blue-100 text-blue-700 animate-pulse',
    queued: 'bg-gray-100 text-gray-700',
    pending: 'bg-gray-100 text-gray-700',
    failed: 'bg-red-100 text-red-700',
  }
  return (
    <span
      className={`px-2 py-0.5 rounded text-xs font-medium ${map[status] || 'bg-gray-100 text-gray-700'}`}
    >
      {status}
    </span>
  )
}

function MetricsCard({ metrics }: { metrics: NonNullable<JudgeRun['metrics']> }) {
  return (
    <div className="mt-3 grid grid-cols-2 md:grid-cols-5 gap-3">
      <Stat label="F1" helpKey="F1" value={metrics.f1.toFixed(3)} highlight />
      <Stat label="Precision" helpKey="Precision" value={metrics.precision.toFixed(3)} />
      <Stat label="Recall" helpKey="Recall" value={metrics.recall.toFixed(3)} />
      <Stat label="Cohen's κ" helpKey="Kappa" value={metrics.kappa.toFixed(3)} />
      <Stat label="N" helpKey="N" value={String(metrics.n)} />
      <ConfusionCell label="TP" value={metrics.tp} good />
      <ConfusionCell label="FP" value={metrics.fp} />
      <ConfusionCell label="FN" value={metrics.fn} />
      <ConfusionCell label="TN" value={metrics.tn} good />
      <div />
    </div>
  )
}

function MetricLabel({ label, helpKey }: { label: string; helpKey: string }) {
  const help = METRIC_HELP[helpKey]
  return (
    <div className="flex items-center gap-1 text-xs text-gray-500">
      <span>{label}</span>
      {help && (
        <InfoTooltip title={help.title}>{help.body}</InfoTooltip>
      )}
    </div>
  )
}

function Stat({
  label,
  helpKey,
  value,
  highlight,
}: {
  label: string
  helpKey: string
  value: string
  highlight?: boolean
}) {
  return (
    <div
      className={`rounded-lg px-3 py-2 ${
        highlight ? 'bg-yellow-50 border border-yellow-300' : 'bg-gray-50 border border-gray-200'
      }`}
    >
      <MetricLabel label={label} helpKey={helpKey} />
      <div className="text-lg font-semibold text-gray-900">{value}</div>
    </div>
  )
}

function ConfusionCell({
  label,
  value,
  good,
}: {
  label: string
  value: number
  good?: boolean
}) {
  return (
    <div
      className={`rounded-lg px-3 py-2 ${
        good ? 'bg-green-50 border border-green-200' : 'bg-red-50 border border-red-200'
      }`}
    >
      <MetricLabel label={label} helpKey={label} />
      <div className={`text-lg font-semibold ${good ? 'text-green-800' : 'text-red-800'}`}>
        {value}
      </div>
    </div>
  )
}
