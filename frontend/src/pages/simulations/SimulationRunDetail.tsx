import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Download, RotateCcw, Square } from 'lucide-react'
import { apiClient } from '../../lib/api'
import { getApiErrorDetail } from '../../lib/authSession'
import Button from '../../components/Button'
import { useToast } from '../../hooks/useToast'
import type { SimulationRun, SimulationTrial } from '../../types/api'
import ScenarioAttemptMatrix from './ScenarioAttemptMatrix'
import TrialTranscriptDrawer from './TrialTranscriptDrawer'
import { PassBadge, RunStatusChip } from './simulationUi'
import { REWARD_BAR_COLOR, formatDuration, formatPct, formatScore, isRunActive } from './simulationFormat'

function StatTile({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-lg border border-gray-200 bg-white px-4 py-3">
      <div className="text-xs font-medium text-gray-500">{label}</div>
      <div className="mt-1 text-2xl font-semibold tabular-nums text-gray-900">{value}</div>
      {hint ? <div className="mt-0.5 text-xs text-gray-500">{hint}</div> : null}
    </div>
  )
}

function MetricBreakdown({ run }: { run: SimulationRun }) {
  const metrics = run.summary?.metrics ?? []
  const usesCriteria =
    run.summary?.uses_success_criteria ?? Boolean(run.metric_success_criteria?.length)
  if (metrics.length === 0) {
    return <p className="text-sm text-gray-500">Metric stats appear once trials are scored.</p>
  }
  const threshold = run.pass_threshold
  return (
    <div className="space-y-2">
      {metrics.map((m) => {
        const value = usesCriteria ? (m.pass_rate ?? m.mean) : m.mean
        return (
          <div
            key={m.metric_id}
            className="grid grid-cols-[minmax(0,12rem)_1fr_3rem] items-center gap-3 text-sm"
            title={
              usesCriteria
                ? `${m.name}: ${formatPct(value)} pass rate over ${m.n} trials`
                : `${m.name}: ${formatScore(m.mean)} mean over ${m.n} trials`
            }
          >
            <span className="truncate text-gray-700">{m.name}</span>
            <div className="relative h-3 rounded-sm bg-gray-100">
              <div className="h-3 rounded-sm" style={{ width: `${value * 100}%`, background: REWARD_BAR_COLOR }} />
              {!usesCriteria ? (
                <div
                  className="absolute -top-1 h-5 w-px bg-gray-500"
                  style={{ left: `${threshold * 100}%` }}
                  aria-hidden
                />
              ) : null}
            </div>
            <span className="text-right tabular-nums text-gray-900">
              {usesCriteria ? formatPct(value) : formatScore(m.mean)}
            </span>
          </div>
        )
      })}
      <p className="pt-1 text-xs text-gray-500">
        {usesCriteria
          ? 'Share of trials where this metric met its success rule.'
          : `Mean normalized score (0–1). The vertical line marks the pass threshold (${threshold.toFixed(2)}).`}
      </p>
    </div>
  )
}

export default function SimulationRunDetail() {
  const { runId = '' } = useParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { showToast, ToastContainer } = useToast()
  const [selectedTrialId, setSelectedTrialId] = useState<string | null>(null)

  const { data: run, isLoading } = useQuery({
    queryKey: ['simulation-run', runId],
    queryFn: () => apiClient.getSimulationRun(runId),
    refetchInterval: (query) => (query.state.data && isRunActive(query.state.data.status) ? 4000 : false),
  })
  const { data: trials = [] } = useQuery({
    queryKey: ['simulation-trials', runId],
    queryFn: () => apiClient.listSimulationTrials(runId),
    enabled: Boolean(run),
    refetchInterval: run && isRunActive(run.status) ? 4000 : false,
  })

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['simulation-run', runId] })
    queryClient.invalidateQueries({ queryKey: ['simulation-runs'] })
  }
  const cancelMutation = useMutation({
    mutationFn: () => apiClient.cancelSimulationRun(runId),
    onSuccess: () => {
      showToast('Cancelling run…')
      invalidate()
    },
    onError: (err) => showToast(getApiErrorDetail(err) || 'Failed to cancel run', 'error'),
  })
  const rerunMutation = useMutation({
    mutationFn: (onlyFailed: boolean) => apiClient.rerunSimulationRun(runId, onlyFailed),
    onSuccess: (newRun) => {
      invalidate()
      navigate(`/simulations/${newRun.run_id}`)
    },
    onError: (err) => showToast(getApiErrorDetail(err) || 'Failed to start re-run', 'error'),
  })
  const downloadMutation = useMutation({
    mutationFn: () => apiClient.downloadSimulationArtifacts(runId),
    onSuccess: (blob) => {
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `simulation-run-${run?.run_id ?? runId}.tar.gz`
      a.click()
      URL.revokeObjectURL(url)
    },
    onError: (err) => showToast(getApiErrorDetail(err) || 'Download failed', 'error'),
  })

  if (isLoading) return <div className="p-6 text-sm text-gray-500">Loading run…</div>
  if (!run) return <div className="p-6 text-sm text-gray-500">Simulation run not found.</div>

  const summary = run.summary
  const active = isRunActive(run.status)
  const done = run.completed_trials + run.failed_trials
  const progress = run.expected_trials ? Math.min(100, (done / run.expected_trials) * 100) : 0
  const hasFailures = trials.some((t) => t.status === 'failed' || t.passed === false)

  return (
    <div className="space-y-6 p-6">
      <div>
        <Link
          to={`/agents/${run.agent_id}?tab=simulations`}
          className="mb-2 inline-flex items-center gap-1 text-sm text-gray-500 hover:text-gray-700"
        >
          <ArrowLeft className="h-4 w-4" /> Back to agent
        </Link>
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="flex items-center gap-3">
              <h1 className="text-xl font-semibold text-gray-900">{run.name || `Simulation run ${run.run_id}`}</h1>
              <RunStatusChip status={run.status} />
            </div>
            <p className="mt-1 text-sm text-gray-500">
              Run <span className="font-mono">{run.run_id}</span> · {run.scenario_ids.length} scenarios ×{' '}
              {run.persona_ids.length} personas × {run.n_attempts} attempts · production model{' '}
              {run.production_llm_model ? `${run.production_llm_provider}/${run.production_llm_model}` : 'agent default'} ·{' '}
              {formatDuration(run.started_at, run.finished_at)}
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            {active ? (
              <Button
                variant="outline"
                leftIcon={<Square className="h-4 w-4" />}
                onClick={() => cancelMutation.mutate()}
                isLoading={cancelMutation.isPending}
                disabled={run.cancel_requested}
              >
                {run.cancel_requested ? 'Cancelling…' : 'Cancel'}
              </Button>
            ) : (
              <>
                {hasFailures ? (
                  <Button
                    variant="outline"
                    leftIcon={<RotateCcw className="h-4 w-4" />}
                    onClick={() => rerunMutation.mutate(true)}
                    isLoading={rerunMutation.isPending}
                  >
                    Re-run failed
                  </Button>
                ) : null}
                <Button
                  variant="outline"
                  leftIcon={<RotateCcw className="h-4 w-4" />}
                  onClick={() => rerunMutation.mutate(false)}
                  isLoading={rerunMutation.isPending}
                >
                  Re-run
                </Button>
              </>
            )}
            {run.has_artifacts ? (
              <Button
                variant="outline"
                leftIcon={<Download className="h-4 w-4" />}
                onClick={() => downloadMutation.mutate()}
                isLoading={downloadMutation.isPending}
                title="Harbor job directory: tasks, ATIF trajectories, rewards. Open with `harbor view`."
              >
                Harbor artifacts
              </Button>
            ) : null}
          </div>
        </div>
        {active ? (
          <div className="mt-4">
            <div className="mb-1 flex justify-between text-xs text-gray-500">
              <span>
                {done}/{run.expected_trials} trials finished
              </span>
              <span>{Math.round(progress)}%</span>
            </div>
            <div className="h-2 rounded-full bg-gray-100">
              <div className="h-2 rounded-full bg-primary-500 transition-all" style={{ width: `${progress}%` }} />
            </div>
          </div>
        ) : null}
        {run.error_message ? (
          <pre className="mt-4 max-h-40 overflow-auto whitespace-pre-wrap rounded-lg bg-red-50 px-3 py-2 text-xs text-red-700">
            {run.error_message}
          </pre>
        ) : null}
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <StatTile
          label="Pass rate"
          value={formatPct(summary?.pass_rate)}
          hint={summary ? `${summary.n_passed} of ${summary.n_completed} scored` : undefined}
        />
        <StatTile
          label={summary?.uses_success_criteria || run.metric_success_criteria?.length ? 'Criteria met' : 'Mean score'}
          value={formatScore(summary?.mean_reward)}
          hint={
            summary?.uses_success_criteria || run.metric_success_criteria?.length
              ? 'average share of metrics passing per trial'
              : `threshold ${run.pass_threshold.toFixed(2)}`
          }
        />
        <StatTile
          label="Consistency (pass^k)"
          value={run.n_attempts > 1 ? formatPct(summary?.pass_all_rate) : '—'}
          hint={run.n_attempts > 1 ? 'scenarios passing every attempt' : 'needs >1 attempt'}
        />
        <StatTile
          label="Pass@k"
          value={run.n_attempts > 1 ? formatPct(summary?.pass_any_rate) : '—'}
          hint={run.n_attempts > 1 ? 'scenarios passing at least once' : 'needs >1 attempt'}
        />
        <StatTile label="Errored trials" value={String(summary?.n_failed ?? run.failed_trials)} hint="did not finish" />
        <StatTile label="Avg turns" value={summary?.avg_turns != null ? summary.avg_turns.toFixed(1) : '—'} />
      </div>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-[2fr_1fr]">
        <section className="rounded-lg border border-gray-200 bg-white p-4">
          <h2 className="mb-3 text-sm font-semibold text-gray-900">Scenario × attempt</h2>
          <ScenarioAttemptMatrix
            trials={trials}
            nAttempts={run.n_attempts}
            onSelect={(t) => setSelectedTrialId(t.id)}
            selectedTrialId={selectedTrialId}
          />
        </section>
        <section className="rounded-lg border border-gray-200 bg-white p-4">
          <h2 className="mb-3 text-sm font-semibold text-gray-900">Metric breakdown</h2>
          <MetricBreakdown run={run} />
        </section>
      </div>

      <section className="rounded-lg border border-gray-200 bg-white">
        <h2 className="border-b border-gray-200 px-4 py-3 text-sm font-semibold text-gray-900">All trials</h2>
        <TrialsTable trials={trials} onSelect={(t) => setSelectedTrialId(t.id)} />
      </section>

      <TrialTranscriptDrawer runId={runId} trialId={selectedTrialId} onClose={() => setSelectedTrialId(null)} />
      <ToastContainer />
    </div>
  )
}

/** Table view of every trial (also the accessible alternative to the matrix). */
function TrialsTable({ trials, onSelect }: { trials: SimulationTrial[]; onSelect: (t: SimulationTrial) => void }) {
  if (trials.length === 0) return <p className="px-4 py-3 text-sm text-gray-500">No trials yet.</p>
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full divide-y divide-gray-200 text-sm">
        <thead className="bg-gray-50 text-left text-xs font-medium uppercase tracking-wide text-gray-500">
          <tr>
            <th className="px-3 py-2">Scenario</th>
            <th className="px-3 py-2">Persona</th>
            <th className="px-3 py-2 text-right">Attempt</th>
            <th className="px-3 py-2">Result</th>
            <th className="px-3 py-2 text-right">Score</th>
            <th className="px-3 py-2 text-right">Turns</th>
            <th className="px-3 py-2">Error</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100">
          {trials.map((t) => (
            <tr key={t.id} className="cursor-pointer hover:bg-gray-50" onClick={() => onSelect(t)}>
              <td className="max-w-xs truncate px-3 py-2 text-gray-900">{t.scenario_name}</td>
              <td className="px-3 py-2 text-gray-700">{t.persona_name}</td>
              <td className="px-3 py-2 text-right tabular-nums">{t.attempt_index ?? '—'}</td>
              <td className="px-3 py-2">
                <PassBadge passed={t.passed} status={t.status} />
              </td>
              <td className="px-3 py-2 text-right tabular-nums">{formatScore(t.reward)}</td>
              <td className="px-3 py-2 text-right tabular-nums">{t.turns}</td>
              <td className="max-w-xs truncate px-3 py-2 text-xs text-red-700" title={t.error_message ?? undefined}>
                {t.error_message}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
