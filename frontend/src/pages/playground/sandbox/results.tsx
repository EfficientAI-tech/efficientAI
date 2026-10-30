import { CheckCircle2, CircleSlash, Scale } from 'lucide-react'
import Button from '../../../components/Button'
import type { Session } from '../../../lib/sandbox'
import { DbDiffViewer } from './environmentView'

export function ScoreHeader({ accuracy, experience }: { accuracy: number; experience: number }) {
  const card = (label: string, value: number, hint: string) => (
    <div className="flex-1 rounded-xl border border-gray-200 bg-white p-4">
      <p className="text-xs font-medium uppercase tracking-wide text-gray-500">{label}</p>
      <p className="mt-1 text-3xl font-semibold text-gray-900">{Math.round(value * 100)}</p>
      <p className="text-xs text-gray-500">{hint}</p>
    </div>
  )
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      {card('Accuracy', accuracy, 'Task completion, faithfulness')}
      {card('Experience', experience, 'Progression, conciseness')}
    </div>
  )
}

export function MetricResultsGrid({ session }: { session: Session }) {
  const metrics = session.results?.metrics ?? []
  if (!metrics.length) return null
  return (
    <div className="mt-4 overflow-hidden rounded-lg border border-gray-200">
      <table className="w-full text-left text-sm">
        <thead className="bg-gray-50 text-xs uppercase text-gray-500">
          <tr>
            <th className="px-3 py-2">Metric</th>
            <th className="px-3 py-2">Axis</th>
            <th className="px-3 py-2">Kind</th>
            <th className="px-3 py-2">Score</th>
            <th className="px-3 py-2">Result</th>
          </tr>
        </thead>
        <tbody>
          {metrics.map((metric) => (
            <tr key={metric.name} className="border-t border-gray-100">
              <td className="px-3 py-2">
                <p className="font-medium text-gray-900">{metric.name}</p>
                {metric.rationale && <p className="text-xs text-gray-500">{metric.rationale}</p>}
              </td>
              <td className="px-3 py-2 capitalize text-gray-600">{metric.axis}</td>
              <td className="px-3 py-2 text-gray-600">
                {metric.kind === 'deterministic' ? 'Deterministic' : 'LLM judge'}
              </td>
              <td className="px-3 py-2">{metric.score}</td>
              <td className="px-3 py-2">
                {metric.passed == null ? (
                  '—'
                ) : metric.passed ? (
                  <span className="inline-flex items-center gap-1 text-emerald-700">
                    <CheckCircle2 className="h-4 w-4" /> Pass
                  </span>
                ) : (
                  <span className="inline-flex items-center gap-1 text-rose-700">
                    <CircleSlash className="h-4 w-4" /> Fail
                  </span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function OutcomeCheckPanel({ session }: { session: Session }) {
  const outcome = session.results?.outcome
  if (!outcome) return null
  return (
    <section className="mt-6 rounded-lg border border-gray-200 p-4">
      <h3 className="flex items-center gap-2 text-sm font-semibold text-gray-900">
        <Scale className="h-4 w-4" /> Outcome check
      </h3>
      <p className="mt-1 text-sm text-gray-600">
        Database {outcome.dbMatch ? 'matches' : 'does not match'} the expected goal state.
      </p>
      <ul className="mt-3 space-y-1 text-sm">
        {outcome.communicateChecks.map((check) => (
          <li key={check.text} className={check.passed ? 'text-emerald-700' : 'text-rose-700'}>
            {check.passed ? 'Pass' : 'Fail'} — {check.text}
          </li>
        ))}
      </ul>
      <div className="mt-4">
        <DbDiffViewer diff={outcome.dbDiff} />
      </div>
    </section>
  )
}

function agentSummary(session: Session, role: 'A' | 'B') {
  const turns = session.turns.filter((t) => t.speaker === role && !t.divider).length
  const events = session.events.filter((e) => e.agent === role)
  const tools = events.filter((e) => e.type === 'tool')
  const skills = events.filter((e) => e.type === 'skill')
  const apis = events.filter((e) => e.type === 'api')
  return {
    turns,
    tools: tools.length,
    failedTools: tools.filter((e) => e.status !== 'ok').length,
    skillErrors: skills.filter((e) => e.status !== 'ok').length,
    apiFailures: apis.filter((e) => e.status !== 'ok').length,
  }
}

export function ResultsTab({
  session,
  onRunMetrics,
  onReEvaluate,
  running,
}: {
  session: Session
  onRunMetrics?: () => void
  onReEvaluate?: () => void
  running?: boolean
}) {
  if (session.status === 'evaluating' || running) {
    return (
      <div className="animate-pulse space-y-3">
        <div className="h-24 rounded-xl bg-gray-100" />
        <div className="h-40 rounded-xl bg-gray-100" />
        <p className="text-sm text-gray-500">Evaluating…</p>
      </div>
    )
  }

  if (!session.results) {
    return (
      <div className="rounded-lg border border-dashed border-gray-300 p-8 text-center">
        <p className="text-sm text-gray-600">
          {session.kind === 'manual'
            ? 'Metrics are not run automatically for manual chats.'
            : 'No metrics yet for this session.'}
        </p>
        {onRunMetrics && (
          <Button className="mt-3" onClick={onRunMetrics}>
            Run metrics on this chat
          </Button>
        )}
      </div>
    )
  }

  const a = agentSummary(session, 'A')
  const b = session.agentB ? agentSummary(session, 'B') : null

  return (
    <div>
      <ScoreHeader accuracy={session.results.accuracy} experience={session.results.experience} />
      <MetricResultsGrid session={session} />
      <OutcomeCheckPanel session={session} />
      <div className="mt-6 grid gap-3 sm:grid-cols-2">
        {[
          { label: session.agentA.name, stats: a },
          b ? { label: session.agentB!.name, stats: b } : null,
        ]
          .filter(Boolean)
          .map((block) => (
            <div key={block!.label} className="rounded-lg border border-gray-200 p-3 text-sm">
              <p className="font-medium text-gray-900">{block!.label}</p>
              <ul className="mt-2 space-y-1 text-gray-600">
                <li>Turns: {block!.stats.turns}</li>
                <li>Tool calls: {block!.stats.tools}</li>
                <li>Failed tool calls: {block!.stats.failedTools}</li>
                <li>Skill errors: {block!.stats.skillErrors}</li>
                <li>API failures: {block!.stats.apiFailures}</li>
              </ul>
            </div>
          ))}
      </div>
      {onReEvaluate && (
        <Button className="mt-4" variant="outline" onClick={onReEvaluate}>
          Re-evaluate
        </Button>
      )}
    </div>
  )
}
