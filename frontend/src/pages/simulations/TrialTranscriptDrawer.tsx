import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { Bot, ChevronRight, ExternalLink, MessageSquare, Wrench, X } from 'lucide-react'
import { apiClient } from '../../lib/api'
import type { SimulationLlms, SimulationToolCall, SimulationTrialDetail } from '../../types/api'
import { PassBadge } from './simulationUi'
import { ToolEvaluationSection } from './ToolCallCard'
import { formatScore, hasToolEvaluation } from './simulationFormat'
import ChatSimulationTranscript from './ChatSimulationTranscript'

interface Props {
  runId: string
  trialId: string | null
  /** Run-level models when this trial did not store its own. */
  fallbackLlms?: SimulationLlms | null
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

/** Production tool calls keyed by the transcript index of the reply they fed. */
function toolCallsByTurn(trial: SimulationTrialDetail) {
  const byTurn = new Map<number, SimulationToolCall[]>()
  for (const call of trial.tool_calls ?? []) {
    if (call.turn_index === null || call.turn_index === undefined) continue
    byTurn.set(call.turn_index, [...(byTurn.get(call.turn_index) ?? []), call])
  }
  return byTurn
}

/** Closed by default; the summary line stays visible so the transcript is reachable without scrolling. */
function CollapsibleSection({
  icon,
  title,
  summary,
  children,
}: {
  icon: ReactNode
  title: string
  summary?: ReactNode
  children: ReactNode
}) {
  return (
    <details className="group rounded-lg border border-gray-200 bg-white">
      <summary className="flex cursor-pointer list-none items-center gap-2 px-3 py-2 text-sm [&::-webkit-details-marker]:hidden">
        <ChevronRight className="h-4 w-4 shrink-0 text-gray-400 transition-transform group-open:rotate-90" />
        {icon}
        <span className="font-semibold text-gray-900">{title}</span>
        {summary ? <span className="ml-auto truncate text-xs text-gray-500">{summary}</span> : null}
      </summary>
      <div className="border-t border-gray-100 px-3 py-3">{children}</div>
    </details>
  )
}

function toolUseSummary(evaluation: NonNullable<SimulationTrialDetail['tool_evaluation']>): string {
  const parts = [`${evaluation.total_calls} ${evaluation.total_calls === 1 ? 'call' : 'calls'}`]
  if (evaluation.errored_calls) parts.push(`${evaluation.errored_calls} failed`)
  if (evaluation.expectations.length) {
    const met = evaluation.expectations.filter((e) => e.satisfied).length
    parts.push(`${met}/${evaluation.expectations.length} expectations met`)
  }
  return parts.join(' · ')
}

function LlmSides({ llms }: { llms?: SimulationLlms | null }) {
  const sides = [
    { key: 'production' as const, label: 'Production agent LLM', hint: 'Answers as the agent under test' },
    { key: 'test' as const, label: 'Test agent LLM', hint: 'Plays the simulated customer' },
  ]
  return (
    <dl className="grid gap-2 sm:grid-cols-2">
      {sides.map(({ key, label, hint }) => {
        const side = llms?.[key]
        return (
          <div key={key} className="rounded-lg border border-gray-200 bg-white px-3 py-2">
            <dt className="text-[11px] font-medium text-gray-500">{label}</dt>
            <dd className="mt-0.5 font-mono text-xs text-gray-900">{side?.label || 'Not recorded'}</dd>
            <dd className="text-[11px] text-gray-500">{side?.source_label || hint}</dd>
          </div>
        )
      })}
    </dl>
  )
}

function scoreLabel(score: { value: unknown; error?: string; skipped?: string }): string {
  if (score.error) return 'Error'
  if (score.skipped) return 'Skipped'
  if (typeof score.value === 'boolean') return score.value ? 'Yes' : 'No'
  if (typeof score.value === 'number') return formatScore(score.value)
  return score.value === null || score.value === undefined ? '—' : String(score.value)
}

export default function TrialTranscriptDrawer({ runId, trialId, fallbackLlms, onClose }: Props) {
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
  const toolCalls = trial ? toolCallsByTurn(trial) : new Map<number, SimulationToolCall[]>()

  return (
    <div className="fixed inset-y-0 right-0 z-[9000] flex w-full max-w-xl flex-col border-l border-gray-200 bg-gray-50 shadow-2xl">
      <div className="shrink-0 border-b border-gray-200 bg-white px-5 py-4">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 className="text-lg font-semibold text-gray-900">Chat transcript</h2>
            <p className="mt-0.5 truncate text-xs text-gray-500">
              {trial?.scenario_name ?? 'Trial'}
              {trial?.persona_name ? (
                <>
                  {' '}
                  · <span className="text-gray-700">{trial.persona_name}</span>
                </>
              ) : null}
              {trial ? (
                <>
                  {' '}
                  · attempt {trial.attempt_index ?? '—'} · {trial.turns ?? 0} turns
                </>
              ) : null}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close trial"
            className="rounded-lg p-2 text-gray-500 hover:bg-gray-100 hover:text-gray-800"
          >
            <X className="h-5 w-5" />
          </button>
        </div>
      </div>

      {isLoading || !trial ? (
        <p className="p-5 text-sm text-gray-500">Loading trial…</p>
      ) : (
        <div className="min-h-0 flex-1 space-y-5 overflow-y-auto overscroll-contain px-5 py-4">
          <div className="flex flex-wrap items-center gap-4">
            <div>
              <div className="text-xs font-medium text-gray-500">Score</div>
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

          <CollapsibleSection
            icon={<Bot className="h-4 w-4 text-gray-500" />}
            title="Agents"
            summary={[trial.llms ?? fallbackLlms]
              .flatMap((llms) => [llms?.production?.label, llms?.test?.label])
              .filter(Boolean)
              .join(' vs ')}
          >
            <LlmSides llms={trial.llms ?? fallbackLlms} />
          </CollapsibleSection>

          {trial.error_message ? (
            <p className="whitespace-pre-wrap rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
              {trial.error_message}
            </p>
          ) : null}

          {trial.metric_scores && Object.keys(trial.metric_scores).length > 0 ? (
            <section>
              <h4 className="mb-2 text-sm font-semibold text-gray-900">Metric scores</h4>
              <ul className="divide-y divide-gray-100 rounded-lg border border-gray-200 bg-white">
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

          {trial.tool_evaluation && hasToolEvaluation(trial.tool_evaluation) ? (
            <CollapsibleSection
              icon={<Wrench className="h-4 w-4 text-gray-500" />}
              title="Tool use"
              summary={toolUseSummary(trial.tool_evaluation)}
            >
              <ToolEvaluationSection evaluation={trial.tool_evaluation} showHeading={false} />
            </CollapsibleSection>
          ) : null}

          {trial.call_analysis?.call_summary ? (
            <div className="rounded-lg border border-indigo-100 bg-indigo-50 p-4">
              <p className="mb-1 text-xs font-semibold uppercase tracking-wider text-indigo-900">Summary</p>
              <p className="text-sm leading-relaxed text-indigo-800">{trial.call_analysis.call_summary}</p>
            </div>
          ) : null}

          <section>
            <h4 className="mb-2 flex items-center gap-2 text-sm font-semibold text-gray-900">
              <MessageSquare className="h-4 w-4 text-gray-500" />
              Transcript
            </h4>
            <ChatSimulationTranscript
              turns={transcriptTurns(trial)}
              personaName={trial.persona_name ?? 'Test agent'}
              toolCallsByTurn={toolCalls}
            />
          </section>
        </div>
      )}
    </div>
  )
}
