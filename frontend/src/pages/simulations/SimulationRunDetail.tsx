import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Check, Download, Pencil, RotateCcw, Square, Trash2, X } from 'lucide-react'
import { apiClient } from '../../lib/api'
import { getApiErrorDetail } from '../../lib/authSession'
import Button from '../../components/Button'
import { useToast } from '../../hooks/useToast'
import type { SimulationRun, SimulationRunToolSummary, SimulationTrial } from '../../types/api'
import ScenarioAttemptMatrix from './ScenarioAttemptMatrix'
import TrialTranscriptDrawer from './TrialTranscriptDrawer'
import { PassBadge, RunStatusChip } from './simulationUi'
import { REWARD_BAR_COLOR, formatDuration, formatPct, formatScore, isRunActive, runLlmLabel } from './simulationFormat'

function StatTile({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-lg border border-gray-200 bg-white px-4 py-3">
      <div className="text-xs font-medium text-gray-500">{label}</div>
      <div className="mt-1 text-2xl font-semibold tabular-nums text-gray-900">{value}</div>
      {hint ? <div className="mt-0.5 text-xs text-gray-500">{hint}</div> : null}
    </div>
  )
}

/** Which model answered on each side; the source says where it came from (agent config, run override, …). */
function RunLlms({ run }: { run: SimulationRun }) {
  const sides = [
    { side: 'production' as const, label: 'Production agent LLM', hint: 'Answers as the agent under test' },
    { side: 'test' as const, label: 'Test agent LLM', hint: 'Plays the simulated customer' },
  ]
  return (
    <dl className="mt-3 grid gap-2 sm:grid-cols-2">
      {sides.map(({ side, label, hint }) => {
        const resolved = run.resolved_llms?.[side]
        return (
          <div key={side} className="rounded-lg border border-gray-200 bg-gray-50 px-3 py-2">
            <dt className="text-xs font-medium text-gray-500">{label}</dt>
            <dd className="mt-0.5 font-mono text-sm text-gray-900">{runLlmLabel(run, side)}</dd>
            <dd className="text-[11px] text-gray-500">{resolved?.source_label || hint}</dd>
          </div>
        )
      })}
    </dl>
  )
}

function MetricBreakdown({
  run,
  scenarioNameById,
}: {
  run: SimulationRun
  scenarioNameById: Map<string, string>
}) {
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
        const agentPart =
          m.agent_ids?.length
            ? `Agents: ${m.agent_ids.map((id) => id.slice(0, 8)).join(', ')}`
            : 'All agents'
        const scenarioPart =
          m.scenario_ids?.length
            ? m.scenario_ids.map((id) => scenarioNameById.get(id) || id.slice(0, 8)).join(', ')
            : 'All scenarios'
        const scopeLabel =
          !m.agent_ids?.length && !m.scenario_ids?.length
            ? 'All agents & scenarios'
            : `${agentPart} · ${scenarioPart}`
        return (
          <div
            key={m.metric_id}
            className="grid grid-cols-[minmax(0,12rem)_1fr_3rem] items-center gap-3 text-sm"
            title={
              usesCriteria
                ? `${m.name} (${scopeLabel}): ${formatPct(value)} pass rate over ${m.n} trials`
                : `${m.name} (${scopeLabel}): ${formatScore(m.mean)} mean over ${m.n} trials`
            }
          >
            <span className="min-w-0 truncate text-gray-700">
              <span className="block truncate">{m.name}</span>
              <span className="block truncate text-[11px] text-gray-400">{scopeLabel}</span>
            </span>
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
  const [editingName, setEditingName] = useState(false)
  const [nameDraft, setNameDraft] = useState('')

  const { data: run, isLoading } = useQuery({
    queryKey: ['simulation-run', runId],
    queryFn: () => apiClient.getSimulationRun(runId),
    refetchInterval: (query) => (query.state.data && isRunActive(query.state.data.status) ? 4000 : false),
  })
  useEffect(() => {
    if (!editingName) setNameDraft(run?.name ?? '')
  }, [run?.name, editingName])
  const { data: scenarioRows = [] } = useQuery({
    queryKey: ['scenarios', 'agent', run?.agent_id],
    queryFn: () => apiClient.listScenarios(0, 500, run!.agent_id),
    enabled: Boolean(run?.agent_id),
  })
  const scenarioNameById = useMemo(
    () => new Map(scenarioRows.map((s: { id: string; name: string }) => [s.id, s.name])),
    [scenarioRows],
  )
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
  const deleteMutation = useMutation({
    mutationFn: () => apiClient.deleteSimulationRun(runId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['simulation-runs'] })
      showToast('Simulation run deleted', 'success')
      navigate(`/agents/${run?.agent_id}?tab=simulations`)
    },
    onError: (err) => showToast(getApiErrorDetail(err) || 'Failed to delete run', 'error'),
  })
  const rerunMutation = useMutation({
    mutationFn: (onlyFailed: boolean) => apiClient.rerunSimulationRun(runId, onlyFailed),
    onSuccess: (newRun) => {
      invalidate()
      navigate(`/simulations/${newRun.run_id}`)
    },
    onError: (err) => showToast(getApiErrorDetail(err) || 'Failed to start re-run', 'error'),
  })
  const renameMutation = useMutation({
    mutationFn: (name: string) => apiClient.renameSimulationRun(runId, name.trim() || null),
    onSuccess: () => {
      setEditingName(false)
      showToast('Run name updated', 'success')
      invalidate()
    },
    onError: (err) => showToast(getApiErrorDetail(err) || 'Failed to rename run', 'error'),
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
              {editingName ? (
                <form
                  className="flex items-center gap-2"
                  onSubmit={(event) => {
                    event.preventDefault()
                    renameMutation.mutate(nameDraft)
                  }}
                >
                  <input
                    autoFocus
                    value={nameDraft}
                    maxLength={200}
                    placeholder={`Simulation run ${run.run_id}`}
                    onChange={(event) => setNameDraft(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key === 'Escape') {
                        setNameDraft(run.name ?? '')
                        setEditingName(false)
                      }
                    }}
                    className="w-72 rounded-lg border border-gray-300 px-2 py-1 text-base font-semibold text-gray-900"
                    aria-label="Simulation run name"
                  />
                  <button
                    type="submit"
                    disabled={renameMutation.isPending}
                    className="rounded p-1 text-gray-500 hover:bg-gray-100 hover:text-gray-800"
                    aria-label="Save run name"
                  >
                    <Check className="h-4 w-4" />
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setNameDraft(run.name ?? '')
                      setEditingName(false)
                    }}
                    className="rounded p-1 text-gray-500 hover:bg-gray-100 hover:text-gray-800"
                    aria-label="Cancel rename"
                  >
                    <X className="h-4 w-4" />
                  </button>
                </form>
              ) : (
                <>
                  <h1 className="text-xl font-semibold text-gray-900">
                    {run.name || `Simulation run ${run.run_id}`}
                  </h1>
                  <button
                    type="button"
                    onClick={() => setEditingName(true)}
                    className="rounded p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-700"
                    aria-label="Rename simulation run"
                    title="Rename"
                  >
                    <Pencil className="h-4 w-4" />
                  </button>
                </>
              )}
              <RunStatusChip status={run.status} />
            </div>
            <p className="mt-1 text-sm text-gray-500">
              Run <span className="font-mono">{run.run_id}</span> · {run.scenario_ids.length} scenarios ×{' '}
              {run.persona_ids.length} personas × {run.n_attempts} attempts ·{' '}
              {formatDuration(run.started_at, run.finished_at)}
            </p>
            <RunLlms run={run} />
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
            ) : null}
            <Button
              variant="outline"
              leftIcon={<Trash2 className="h-4 w-4" />}
              onClick={() => {
                const stuck = active || run.cancel_requested
                const msg = stuck
                  ? 'This run may still be active or stuck cancelling. Delete it from the list anyway?'
                  : 'Delete this simulation run and all its trials?'
                if (window.confirm(msg)) deleteMutation.mutate()
              }}
              isLoading={deleteMutation.isPending}
              className="text-red-700 hover:border-red-300 hover:bg-red-50"
            >
              Delete
            </Button>
            {!active ? (
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
            ) : null}
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
        ) : summary?.failed_trial_errors?.length ? (
          <div className="mt-4 space-y-2 rounded-lg bg-red-50 px-3 py-2 text-xs text-red-700">
            <p className="font-medium">Trial errors</p>
            {summary.failed_trial_errors.map((e) => (
              <pre key={e.result_id} className="whitespace-pre-wrap">
                {[e.scenario_name, e.persona_name].filter(Boolean).join(' · ')}
                {e.scenario_name || e.persona_name ? ': ' : ''}
                {e.error_message}
              </pre>
            ))}
          </div>
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
          label="Golden score"
          value={formatScore(summary?.golden_mean_reward)}
          hint="mean of golden metrics only, per trial"
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
        {summary?.tools ? (
          <>
            <StatTile
              label="Tool calls succeeded"
              value={formatPct(summary.tools.success_rate)}
              hint={`${summary.tools.total_calls} calls in ${summary.tools.trials_with_calls} trials`}
            />
            <StatTile
              label="Tool expectations met"
              value={formatPct(summary.tools.expectations_met_rate)}
              hint={
                summary.tools.expectations_checked
                  ? `${summary.tools.expectations_checked} trials checked`
                  : 'no scenario sets expected tool calls'
              }
            />
          </>
        ) : null}
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
          <MetricBreakdown run={run} scenarioNameById={scenarioNameById} />
        </section>
      </div>

      {summary?.tools?.tools.length ? (
        <section className="rounded-lg border border-gray-200 bg-white">
          <h2 className="border-b border-gray-200 px-4 py-3 text-sm font-semibold text-gray-900">Tool calls</h2>
          <ToolsTable tools={summary.tools} />
        </section>
      ) : null}

      <section className="rounded-lg border border-gray-200 bg-white">
        <h2 className="border-b border-gray-200 px-4 py-3 text-sm font-semibold text-gray-900">All trials</h2>
        <TrialsTable trials={trials} onSelect={(t) => setSelectedTrialId(t.id)} />
      </section>

      <TrialTranscriptDrawer
        runId={runId}
        trialId={selectedTrialId}
        fallbackLlms={run.resolved_llms}
        onClose={() => setSelectedTrialId(null)}
      />
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
            <th className="px-3 py-2">Tools</th>
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
              <td className="whitespace-nowrap px-3 py-2 text-xs text-gray-700">
                {t.tool_call_count ? `${t.tool_call_count} calls` : '—'}
                {t.tool_error_count ? <span className="text-red-700"> · {t.tool_error_count} failed</span> : null}
                {t.tool_expectations_met === false ? (
                  <span className="text-red-700"> · expectations not met</span>
                ) : null}
              </td>
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

/** Per-tool reliability across the run, worst error rate first. */
function ToolsTable({ tools }: { tools: SimulationRunToolSummary }) {
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full divide-y divide-gray-200 text-sm">
        <thead className="bg-gray-50 text-left text-xs font-medium uppercase tracking-wide text-gray-500">
          <tr>
            <th className="px-3 py-2">Tool</th>
            <th className="px-3 py-2">Source</th>
            <th className="px-3 py-2 text-right">Calls</th>
            <th className="px-3 py-2 text-right">Failed</th>
            <th className="px-3 py-2 text-right">Mocked</th>
            <th className="px-3 py-2 text-right">Avg latency</th>
            <th className="px-3 py-2 text-right">Trials</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100">
          {tools.tools.map((row) => (
            <tr key={row.tool}>
              <td className="px-3 py-2 font-mono text-gray-900">{row.tool}</td>
              <td className="px-3 py-2 text-gray-700">{row.provider ?? '—'}</td>
              <td className="px-3 py-2 text-right tabular-nums">{row.calls}</td>
              <td className={`px-3 py-2 text-right tabular-nums ${row.errors ? 'text-red-700' : ''}`}>
                {row.errors} ({formatPct(row.error_rate)})
              </td>
              <td className="px-3 py-2 text-right tabular-nums">{row.mocked}</td>
              <td className="px-3 py-2 text-right tabular-nums">
                {row.avg_latency_ms != null ? `${(row.avg_latency_ms / 1000).toFixed(1)}s` : '—'}
              </td>
              <td className="px-3 py-2 text-right tabular-nums">{row.trials}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
