import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { EyeOff, ExternalLink, MessageSquare, Wrench, X } from 'lucide-react'
import { apiClient } from '../../lib/api'
import CallWaveformPlayer from '../../components/call-recordings/CallWaveformPlayer'
import { transcriptBubbleClass, transcriptMetaClass } from '../../components/call-recordings/transcriptBubbleStyles'
import type { RedTeamAttackDetail, RedTeamTranscriptTurn } from '../../types/redTeam'
import { AttackOutcomeChip } from './redTeamUi'
import { attackCategoryLabel, humanizeId } from './redTeamFormat'

interface Props {
  runRef: string
  attackId: string | null
  familyNames?: Map<string, string>
  onClose: () => void
}

function isAttackSettled(attack?: RedTeamAttackDetail): boolean {
  return Boolean(attack && ['completed', 'failed', 'cancelled'].includes(attack.status))
}

function TextBlock({ label, text }: { label: string; text?: string | null }) {
  if (!text) return null
  return (
    <div>
      <div className="text-xs font-medium text-gray-500">{label}</div>
      <p className="mt-0.5 whitespace-pre-wrap text-sm text-gray-800">{text}</p>
    </div>
  )
}

function Pills({ label, items, tone }: { label: string; items?: string[]; tone: string }) {
  if (!items?.length) return null
  return (
    <div>
      <div className="text-xs font-medium text-gray-500">{label}</div>
      <div className="mt-1 flex flex-wrap gap-1">
        {items.map((item) => (
          <span key={item} className={`rounded-md px-2 py-0.5 text-xs ${tone}`}>
            {item}
          </span>
        ))}
      </div>
    </div>
  )
}

function SubScore({ label, value }: { label: string; value?: number | null }) {
  if (value === null || value === undefined) return null
  return (
    <div className="rounded-lg border border-gray-200 bg-white px-3 py-2">
      <div className="text-[11px] font-medium text-gray-500">{label}</div>
      <div className="text-lg font-semibold tabular-nums text-gray-900">{Number.isInteger(value) ? value : value.toFixed(1)}</div>
    </div>
  )
}

function toolCallLine(call: NonNullable<RedTeamTranscriptTurn['tool_calls']>[number]): string {
  const name = call.name || call.tool || 'tool'
  if (call.arguments === undefined || call.arguments === null) return `${name}()`
  const args = typeof call.arguments === 'string' ? call.arguments : JSON.stringify(call.arguments)
  return `${name}(${args.length > 120 ? `${args.slice(0, 120)}…` : args})`
}

function AttackTranscript({ turns, evidence }: { turns: RedTeamTranscriptTurn[]; evidence: Set<number> }) {
  if (turns.length === 0) return <p className="py-8 text-center text-sm text-gray-500">No conversation recorded.</p>
  return (
    <div className="rounded-xl border border-gray-200 bg-white p-4">
      <div className="space-y-3">
        {turns.map((turn, idx) => {
          const isAttacker = turn.role === 'attacker'
          const flagged = evidence.has(idx)
          return (
            <div key={idx} className="space-y-1">
              {turn.tool_calls?.length ? (
                <div className={`flex ${isAttacker ? 'justify-end' : 'justify-start'}`}>
                  <div className="max-w-[85%] space-y-0.5 rounded-lg border border-dashed border-gray-300 bg-gray-50 px-2.5 py-1.5">
                    {turn.tool_calls.map((call, i) => (
                      <div key={i} className="flex items-center gap-1.5 font-mono text-[11px] text-gray-600">
                        <Wrench className="h-3 w-3 shrink-0 text-gray-400" />
                        <span className="truncate">{toolCallLine(call)}</span>
                      </div>
                    ))}
                  </div>
                </div>
              ) : null}
              <div className={`flex ${isAttacker ? 'justify-end' : 'justify-start'}`}>
                <div
                  className={`${transcriptBubbleClass(isAttacker)} ${
                    flagged ? 'ring-2 ring-red-400 ring-offset-1' : ''
                  }`}
                >
                  <div className={transcriptMetaClass(isAttacker)}>
                    <span>{isAttacker ? 'Attacker' : 'Agent'}</span>
                    {flagged ? (
                      <span className={`rounded px-1 ${isAttacker ? 'bg-white/20' : 'bg-red-100 text-red-700'}`}>
                        Evidence
                      </span>
                    ) : null}
                  </div>
                  <p className="whitespace-pre-wrap text-sm leading-relaxed">{turn.text}</p>
                </div>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

export default function RedTeamAttackDrawer({ runRef, attackId, familyNames, onClose }: Props) {
  const { data: attack, isLoading } = useQuery({
    queryKey: ['red-team-attack', runRef, attackId],
    queryFn: () => apiClient.redTeam.getAttack(runRef, attackId as string),
    enabled: Boolean(attackId),
    refetchInterval: (query) => (isAttackSettled(query.state.data) ? false : 4000),
  })

  if (!attackId) return null
  const judge = attack?.judge
  const evidence = new Set(judge?.evidence_turns ?? [])
  const title =
    attack?.kind === 'recon' ? `Recon probe ${attack.sequence}` : attack?.technique_name || humanizeId(attack?.technique_id)
  const subtitle = attack
    ? [
        attack.family ? (familyNames?.get(attack.family) ?? humanizeId(attack.family)) : null,
        attackCategoryLabel(attack),
        attack.kind === 'attack' ? `level ${attack.level}` : null,
      ]
        .filter(Boolean)
        .join(' · ')
    : ''

  return (
    <div className="fixed inset-y-0 right-0 z-[9000] flex w-full max-w-xl flex-col border-l border-gray-200 bg-gray-50 shadow-2xl">
      <div className="shrink-0 border-b border-gray-200 bg-white px-5 py-4">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 className="truncate text-lg font-semibold text-gray-900">{attack ? title : 'Attack'}</h2>
            <p className="mt-0.5 truncate text-xs text-gray-500">{subtitle}</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close attack"
            className="rounded-lg p-2 text-gray-500 hover:bg-gray-100 hover:text-gray-800"
          >
            <X className="h-5 w-5" />
          </button>
        </div>
      </div>

      {isLoading || !attack ? (
        <p className="p-5 text-sm text-gray-500">Loading attack…</p>
      ) : (
        <div className="min-h-0 flex-1 space-y-5 overflow-y-auto overscroll-contain px-5 py-4">
          <div className="flex flex-wrap items-center gap-4">
            <div>
              <div className="text-xs font-medium text-gray-500">Judge score</div>
              <div className="text-2xl font-semibold tabular-nums text-gray-900">
                {judge?.score ?? attack.score ?? '—'}
                <span className="text-sm font-normal text-gray-400"> / 10</span>
              </div>
            </div>
            <AttackOutcomeChip attack={{ status: attack.status, outcome: judge?.outcome ?? attack.outcome }} />
            {attack.evaluator_result_ref ? (
              <Link
                to={`/results/${attack.evaluator_result_ref}`}
                className="ml-auto inline-flex items-center gap-1 text-xs font-medium text-primary-600 hover:underline"
              >
                Full result <ExternalLink className="h-3 w-3" />
              </Link>
            ) : null}
          </div>

          {attack.redacted ? (
            <p className="flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
              <EyeOff className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              Harmful content in this transcript has been redacted.
            </p>
          ) : null}

          {attack.error_message ? (
            <p className="whitespace-pre-wrap rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
              {attack.error_message}
            </p>
          ) : null}

          <section className="space-y-3 rounded-lg border border-gray-200 bg-white p-4">
            <TextBlock label="Goal" text={attack.goal} />
            <TextBlock label="Strategy" text={attack.strategy} />
            <TextBlock label="Judge rationale" text={judge?.rationale ?? attack.rationale} />
            <Pills label="Leaked data" items={judge?.leaked_data} tone="bg-red-50 text-red-700" />
            <Pills label="Gated actions performed" items={judge?.gated_actions} tone="bg-red-50 text-red-700" />
          </section>

          {judge &&
          [judge.non_refusal, judge.specificity, judge.actionability, judge.success_score].some((v) => v != null) ? (
            <section>
              <h4 className="mb-2 text-sm font-semibold text-gray-900">Harm scores</h4>
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                <SubScore label="Non-refusal" value={judge.non_refusal} />
                <SubScore label="Specificity" value={judge.specificity} />
                <SubScore label="Actionability" value={judge.actionability} />
                <SubScore label="Success (0–100)" value={judge.success_score ?? attack.success_score} />
              </div>
            </section>
          ) : null}

          {attack.has_recording && attack.evaluator_result_id ? (
            <section>
              <h4 className="mb-2 text-sm font-semibold text-gray-900">Recording</h4>
              <CallWaveformPlayer evaluatorResultId={attack.evaluator_result_id} />
            </section>
          ) : null}

          <section>
            <h4 className="mb-2 flex items-center gap-2 text-sm font-semibold text-gray-900">
              <MessageSquare className="h-4 w-4 text-gray-500" />
              Transcript
              {evidence.size ? (
                <span className="text-xs font-normal text-gray-500">· outlined turns are the judge's evidence</span>
              ) : null}
            </h4>
            <AttackTranscript turns={attack.transcript ?? []} evidence={evidence} />
          </section>
        </div>
      )}
    </div>
  )
}
