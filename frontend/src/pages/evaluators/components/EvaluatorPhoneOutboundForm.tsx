import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { apiClient } from '../../../lib/api'
import Button from '../../../components/Button'
import { Phone } from 'lucide-react'
import EvaluatorDialTargetFields from './EvaluatorDialTargetFields'
import { MODERN_INPUT_CLASS } from './evaluatorUi'

interface Props {
  agentId: string
  evaluatorId: string
  personaId: string
  scenarioId: string
  personaName?: string
  scenarioName?: string
  toNumber: string
  onToNumberChange: (value: string) => void
  fromNumber?: string
  onFromNumberChange?: (value: string) => void
  disabled?: boolean
  showToast: (message: string, type: 'success' | 'error') => void
}

export default function EvaluatorPhoneOutboundForm({
  agentId,
  evaluatorId,
  personaId,
  scenarioId,
  personaName,
  scenarioName,
  toNumber,
  onToNumberChange,
  fromNumber = '',
  onFromNumberChange,
  disabled = false,
  showToast,
}: Props) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const callMutation = useMutation({
    mutationFn: () =>
      apiClient.createVobizOutboundCall({
        agent_id: agentId,
        evaluator_id: evaluatorId,
        persona_id: personaId,
        scenario_id: scenarioId,
        to_number: toNumber,
        ...(fromNumber.trim() ? { from_number: fromNumber.trim() } : {}),
      }),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['evaluator-results'] })
      queryClient.invalidateQueries({ queryKey: ['observability-traces'] })
      const traceHint = data?.call_short_id ? ` Trace id ${data.call_short_id}.` : ''
      const suffix = data?.result_id ? ` (result ${data.result_id})` : ''
      showToast(`Outbound call initiated${suffix}.${traceHint} Export STT/LLM/TTS with this id.`, 'success')
      if (data.result_id) {
        navigate(`/results/${data.result_id}`)
      }
    },
    onError: (err: any) => {
      const detail = err?.response?.data?.detail
      showToast(typeof detail === 'string' ? detail : 'Call failed', 'error')
    },
  })

  return (
    <div className="space-y-4">
      {(personaName || scenarioName) && (
        <div className="flex flex-wrap gap-2">
          {personaName && (
            <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-purple-50 text-purple-700 border border-purple-100">
              {personaName}
            </span>
          )}
          {scenarioName && (
            <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-green-50 text-green-700 border border-green-100">
              {scenarioName}
            </span>
          )}
        </div>
      )}
      <EvaluatorDialTargetFields
        label="To number *"
        value={toNumber}
        onChange={onToNumberChange}
        helperText="Also used when you queue suite runs from the header."
      />
      {onFromNumberChange ? (
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1.5">From number (optional)</label>
          <input
            type="tel"
            value={fromNumber}
            onChange={(e) => onFromNumberChange(e.target.value)}
            placeholder="Org caller ID (defaults to agent number)"
            className={MODERN_INPUT_CLASS}
          />
        </div>
      ) : null}
      <Button
        variant="primary"
        onClick={() => callMutation.mutate()}
        isLoading={callMutation.isPending}
        disabled={disabled || !toNumber.trim()}
        leftIcon={<Phone className="h-4 w-4" />}
      >
        Place call
      </Button>
    </div>
  )
}
