import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ExternalLink, X } from 'lucide-react'
import { apiClient } from '../../lib/api'
import type { SimulationTrialDetail } from '../../types/api'
import { PassBadge } from './simulationUi'
import { formatScore } from './simulationFormat'

interface Props {
  runId: string
  trialId: string | null
  onClose: () => void
}

function transcriptTurns(trial: SimulationTrialDetail) {
  const steps = trial.trajectory?.steps?.filter((s) => s.source !== 'system')
  if (steps?.length) {
    return steps.map((s) => ({ role: s.source, text: s.message, latencyMs: s.extra?.latency_ms }))
  }
  return (trial.speaker_segments ?? []).map((s) => ({
    role: s.speaker === 'Speaker 2' ? 'agent' : 'user',
    text: s.text,
    latencyMs: undefined as number | undefined,
  }))
}

function scoreLabel(score: { value: unknown; error?: string; skipped?: string }): string {
  if (score.error) return 'Error'
  if (score.skipped) return 'Skipped'
  if (typeof score.value === 'boolean') return score.value ? 'Yes' : 'No'
  if (typeof score.value === 'number') return formatScore(score.value)
  return score.value === null || score.value === undefined ? '—' : String(score.value)
}

export default function TrialTranscriptDrawer({ runId, trialId, onClose }: Props) {
  const { data: trial, isLoading } = useQuery({
    queryKey: ['simulation-trial', runId, trialId],
    queryFn: () => apiClient.getSimulationTrial(runId, trialId as string),
    enabled: Boolean(trialId),
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status === 'completed' || status === 'failed' ? false : 3000
    },
  })

  if (!trialId) return null

  return (
    <div className="fixed inset-y-0 right-0 z-[9000] flex w-full max-w-xl flex-col border-l border-gray-200 bg-white shadow-2xl">
      <div className="flex items-start justify-between border-b border-gray-200 px-5 py-4">
        <div className="min-w-0">
          <h3 className="truncate text-base font-semibold text-gray-900">{trial?.scenario_name ?? 'Trial'}</h3>
          <p className="text-xs text-gray-500">
            {trial?.persona_name} · attempt {trial?.attempt_index ?? '—'} · {trial?.turns ?? 0} turns
          </p>
        </div>
        <button onClick={onClose} className="text-gray-400 hover:text-gray-600" aria-label="Close trial">
          <X className="h-5 w-5" />
        </button>
      </div>

      {isLoading || !trial ? (
        <p className="p-5 text-sm text-gray-500">Loading trial…</p>
      ) : (
        <div className="flex-1 space-y-5 overflow-y-auto px-5 py-4">
          <div className="flex items-center gap-4">
            <div>
              <div className="text-xs text-gray-500">Score</div>
              <div className="text-2xl font-semibold tabular-nums text-gray-900">{formatScore(trial.reward)}</div>
            </div>
            <PassBadge passed={trial.passed} status={trial.status} />
            <Link
              to={`/results/${trial.result_id}`}
              className="ml-auto inline-flex items-center gap-1 text-xs font-medium text-primary-600 hover:underline"
            >
              Full result <ExternalLink className="h-3 w-3" />
            </Link>
          </div>

          {trial.error_message ? (
            <p className="whitespace-pre-wrap rounded-lg bg-red-50 px-3 py-2 text-xs text-red-700">{trial.error_message}</p>
          ) : null}

          {trial.metric_scores && Object.keys(trial.metric_scores).length > 0 ? (
            <section>
              <h4 className="mb-2 text-sm font-semibold text-gray-900">Metric scores</h4>
              <ul className="divide-y divide-gray-100 rounded-lg border border-gray-200">
                {Object.entries(trial.metric_scores).map(([id, score]) => (
                  <li key={id} className="px-3 py-2">
                    <div className="flex items-center justify-between gap-3 text-sm">
                      <span className="text-gray-900">{score.metric_name || id}</span>
                      <div className="flex items-center gap-2">
                        {score.passed !== undefined && score.passed !== null ? (
                          <span
                            className={`text-xs font-medium ${score.passed ? 'text-green-700' : 'text-red-700'}`}
                          >
                            {score.passed ? 'Pass' : 'Fail'}
                          </span>
                        ) : null}
                        <span className="tabular-nums font-medium text-gray-900">{scoreLabel(score)}</span>
                      </div>
                    </div>
                    {score.rationale ? <p className="mt-1 text-xs text-gray-500">{score.rationale}</p> : null}
                  </li>
                ))}
              </ul>
            </section>
          ) : null}

          {trial.call_analysis?.call_summary ? (
            <section>
              <h4 className="mb-1 text-sm font-semibold text-gray-900">Summary</h4>
              <p className="text-sm text-gray-700">{trial.call_analysis.call_summary}</p>
            </section>
          ) : null}

          <section>
            <h4 className="mb-2 text-sm font-semibold text-gray-900">Conversation</h4>
            <div className="space-y-2">
              {transcriptTurns(trial).map((turn, idx) => (
                <div key={idx} className={`flex ${turn.role === 'agent' ? 'justify-end' : 'justify-start'}`}>
                  <div
                    className={`max-w-[85%] rounded-lg px-3 py-2 text-sm ${
                      turn.role === 'agent' ? 'bg-primary-50 text-gray-900' : 'bg-gray-100 text-gray-900'
                    }`}
                  >
                    <div className="mb-0.5 text-[11px] font-medium text-gray-500">
                      {turn.role === 'agent' ? 'Production agent' : 'Test agent'}
                      {turn.latencyMs !== undefined ? ` · ${(turn.latencyMs / 1000).toFixed(1)}s` : ''}
                    </div>
                    <p className="whitespace-pre-wrap">{turn.text}</p>
                  </div>
                </div>
              ))}
            </div>
          </section>
        </div>
      )}
    </div>
  )
}
