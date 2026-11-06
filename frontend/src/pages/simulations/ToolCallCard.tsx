import { CheckCircle2, FlaskConical, Wrench, XCircle } from 'lucide-react'
import type { SimulationToolCall, SimulationToolCallStatus, SimulationToolEvaluation } from '../../types/api'
import { formatScore, hasToolEvaluation } from './simulationFormat'

const STATUS_STYLES: Record<SimulationToolCallStatus, { label: string; className: string }> = {
  ok: { label: 'Succeeded', className: 'bg-green-50 text-green-700' },
  error: { label: 'Failed', className: 'bg-red-50 text-red-700' },
  mocked: { label: 'Mocked', className: 'bg-amber-50 text-amber-700' },
}

/** Status always ships icon + label, never color alone. */
function ToolStatusChip({ status }: { status: SimulationToolCallStatus }) {
  const style = STATUS_STYLES[status] ?? STATUS_STYLES.ok
  const Icon = status === 'error' ? XCircle : status === 'mocked' ? FlaskConical : CheckCircle2
  return (
    <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium ${style.className}`}>
      <Icon className="h-3 w-3" />
      {style.label}
    </span>
  )
}

export function ToolCallCard({ call }: { call: SimulationToolCall }) {
  return (
    <details className="rounded-lg border border-gray-200 bg-white text-xs">
      <summary className="flex cursor-pointer list-none items-center gap-2 px-3 py-2">
        <Wrench className="h-3.5 w-3.5 shrink-0 text-gray-400" />
        <span className="truncate font-mono font-medium text-gray-900">{call.tool}</span>
        {call.hit_count !== undefined ? (
          <span className="text-gray-500">
            {call.hit_count} {call.hit_count === 1 ? 'passage' : 'passages'}
          </span>
        ) : null}
        <span className="ml-auto flex items-center gap-2">
          <span className="tabular-nums text-gray-500">{(call.latency_ms / 1000).toFixed(1)}s</span>
          <ToolStatusChip status={call.status} />
        </span>
      </summary>
      <div className="space-y-2 border-t border-gray-100 px-3 py-2">
        <div>
          <div className="mb-0.5 font-medium text-gray-500">Arguments</div>
          <pre className="whitespace-pre-wrap break-words rounded bg-gray-50 p-2 font-mono text-gray-800">
            {JSON.stringify(call.arguments, null, 2)}
          </pre>
        </div>
        <div>
          <div className="mb-0.5 font-medium text-gray-500">{call.status === 'error' ? 'Error' : 'Result'}</div>
          <pre className="max-h-48 overflow-y-auto whitespace-pre-wrap break-words rounded bg-gray-50 p-2 text-gray-800">
            {call.error || call.result_preview || '—'}
          </pre>
        </div>
      </div>
    </details>
  )
}

export function ToolEvaluationSection({
  evaluation,
  showHeading = true,
}: {
  evaluation: SimulationToolEvaluation
  showHeading?: boolean
}) {
  if (!hasToolEvaluation(evaluation)) return null
  return (
    <section>
      {showHeading ? <h4 className="mb-2 text-sm font-semibold text-gray-900">Tool use</h4> : null}
      <div className="mb-2 flex flex-wrap gap-x-5 gap-y-1 text-xs text-gray-600">
        <span>
          Calls <span className="font-medium tabular-nums text-gray-900">{evaluation.total_calls}</span>
        </span>
        <span>
          Succeeded <span className="font-medium tabular-nums text-gray-900">{formatScore(evaluation.success_rate)}</span>
        </span>
        {evaluation.kb_calls ? (
          <span>
            KB searches with results{' '}
            <span className="font-medium tabular-nums text-gray-900">{formatScore(evaluation.kb_hit_rate)}</span>
          </span>
        ) : null}
      </div>
      {evaluation.expectations.length ? (
        <ul className="divide-y divide-gray-100 rounded-lg border border-gray-200">
          {evaluation.expectations.map((exp, idx) => (
            <li key={idx} className="flex items-start gap-2 px-3 py-2 text-xs">
              {exp.satisfied ? (
                <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-green-600" aria-label="Met" />
              ) : (
                <XCircle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-red-600" aria-label="Not met" />
              )}
              <div className="min-w-0">
                <div className="text-gray-900">
                  {exp.forbidden ? 'Never call ' : exp.must_succeed ? 'Successfully call ' : 'Call '}
                  <span className="font-mono">{exp.tool}</span>
                  {exp.args_contains && Object.keys(exp.args_contains).length
                    ? ` with ${Object.entries(exp.args_contains)
                        .map(([k, v]) => `${k} ∋ "${v}"`)
                        .join(', ')}`
                    : ''}
                </div>
                {exp.reason ? <div className="text-red-700">{exp.reason}</div> : null}
              </div>
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  )
}
