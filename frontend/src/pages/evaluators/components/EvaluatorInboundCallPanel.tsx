import { useMutation } from '@tanstack/react-query'
import { apiClient, EvaluatorSuite } from '../../../lib/api'
import Button from '../../../components/Button'
import { RotateCcw, PhoneIncoming, SkipForward, AlertTriangle } from 'lucide-react'

interface Props {
  suite: EvaluatorSuite
  agentPhoneNumber?: string | null
  onSuiteUpdated?: () => void
  showToast?: (message: string, type: 'success' | 'error') => void
}

export default function EvaluatorInboundCallPanel({
  suite,
  agentPhoneNumber,
  onSuiteUpdated,
  showToast,
}: Props) {
  const isActive = suite.is_active
  const nextIdx = suite.round_robin_index % Math.max(suite.combination_count, 1)
  const nextCombo = suite.combinations[nextIdx]
  const nextRotationLabel = nextCombo
    ? [nextCombo.persona_name, nextCombo.scenario_name].filter(Boolean).join(' · ')
    : undefined

  const chooseNextMutation = useMutation({
    mutationFn: () => apiClient.chooseNextCombination(suite.id),
    onSuccess: (data) => {
      onSuiteUpdated?.()
      showToast?.(`Next: ${[data.persona_name, data.scenario_name].filter(Boolean).join(' · ') || data.scenario_name}`, 'success')
    },
    onError: (err: any) => {
      const detail = err?.response?.data?.detail
      showToast?.(typeof detail === 'string' ? detail : 'Could not advance rotation', 'error')
    },
  })

  return (
    <div className="bg-white shadow rounded-lg overflow-hidden">
      <div className="px-6 py-4 border-b border-gray-200 bg-gradient-to-r from-amber-50/80 to-white">
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-amber-100 flex items-center justify-center">
              <PhoneIncoming className="h-5 w-5 text-amber-600" />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-gray-900">Inbound Round-Robin</h2>
              <p className="text-sm text-gray-500 mt-0.5">
                {isActive
                  ? 'This is the active suite — incoming calls use this persona and scenario rotation'
                  : 'Inactive — activate this suite to use it for incoming calls'}
              </p>
            </div>
          </div>
          <Button
            size="sm"
            variant="primary"
            onClick={() => chooseNextMutation.mutate()}
            isLoading={chooseNextMutation.isPending}
            disabled={!isActive}
            title={!isActive ? 'Set this suite as active first' : undefined}
            leftIcon={<SkipForward className="h-4 w-4" />}
          >
            Choose next
          </Button>
        </div>
      </div>
      <div className="p-6 space-y-4">
        {!isActive && (
          <div className="flex items-start gap-2 rounded-xl border border-amber-200 bg-amber-50/80 p-4 text-sm text-amber-900">
            <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5" />
            <p>
              Another suite may be active for <strong>{suite.agent_name || 'this agent'}</strong>. Use{' '}
              <strong>Set as active</strong> on this page when you want inbound calls to use this persona and
              scenarios.
            </p>
          </div>
        )}
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
          <p className="mt-2 text-amber-900 font-semibold">{nextRotationLabel || '—'}</p>
          <p className="text-xs text-amber-700 mt-1">
            Position {nextIdx + 1} of {suite.combination_count}
          </p>
        </div>
        <p className="text-sm text-gray-600 leading-relaxed">
          When a caller dials the agent&apos;s inbound number, the active suite&apos;s current scenario is used for
          evaluation and the pointer advances. <strong className="font-medium">Choose next</strong> moves the pointer
          only (no call is placed).
        </p>
      </div>
    </div>
  )
}
