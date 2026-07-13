import { EvaluatorSuite } from '../../../lib/api'
import { RotateCcw, PhoneIncoming } from 'lucide-react'

interface Props {
  suite: EvaluatorSuite
  agentPhoneNumber?: string | null
}

export default function EvaluatorInboundCallPanel({ suite, agentPhoneNumber }: Props) {
  const nextIdx = suite.round_robin_index % Math.max(suite.combination_count, 1)
  const nextScenario = suite.combinations[nextIdx]?.scenario_name

  const content = (
    <div className="bg-white shadow rounded-lg overflow-hidden">
      <div className="px-6 py-4 border-b border-gray-200 bg-gradient-to-r from-amber-50/80 to-white">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-lg bg-amber-100 flex items-center justify-center">
            <PhoneIncoming className="h-5 w-5 text-amber-600" />
          </div>
          <div>
            <h2 className="text-lg font-semibold text-gray-900">Inbound Round-Robin</h2>
            <p className="text-sm text-gray-500 mt-0.5">
              Scenarios rotate automatically on incoming calls — no manual test calls
            </p>
          </div>
        </div>
      </div>
      <div className="p-6 space-y-4">
        {agentPhoneNumber && (
          <div className="rounded-xl border border-gray-100 bg-gray-50/50 p-4">
            <p className="text-xs font-medium text-gray-500 uppercase tracking-wider mb-1">Agent inbound number</p>
            <p className="font-mono text-lg font-semibold text-gray-900">{agentPhoneNumber}</p>
          </div>
        )}
        <div className="rounded-xl border border-amber-200 bg-amber-50/60 p-4">
          <div className="flex items-center gap-2 text-amber-900 font-medium text-sm">
            <RotateCcw className="h-4 w-4" />
            Next in rotation
          </div>
          <p className="mt-2 text-amber-900 font-semibold">{nextScenario || '—'}</p>
          <p className="text-xs text-amber-700 mt-1">
            Position {nextIdx + 1} of {suite.combination_count}
          </p>
        </div>
        <p className="text-sm text-gray-600 leading-relaxed">
          Callers dial the agent&apos;s inbound number. Each call advances the round-robin to the next scenario for post-call evaluation.
        </p>
      </div>
    </div>
  )

  return content
}
