import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../../../lib/api'
import Button from '../../../components/Button'
import { Phone } from 'lucide-react'
import { MODERN_INPUT_CLASS, MODERN_SELECT_CLASS } from './evaluatorUi'

interface Props {
  agentId: string
  evaluatorId: string
  personaId: string
  scenarioId: string
  personaName?: string
  scenarioName?: string
  showToast: (message: string, type: 'success' | 'error') => void
}

export default function EvaluatorPhoneOutboundForm({
  agentId,
  evaluatorId,
  personaId,
  scenarioId,
  personaName,
  scenarioName,
  showToast,
}: Props) {
  const [toNumber, setToNumber] = useState('')
  const [fromNumber, setFromNumber] = useState('')

  const queryClient = useQueryClient()
  const { data: dialTargets = [] } = useQuery({
    queryKey: ['telephony-dial-targets'],
    queryFn: () => apiClient.listTelephonyDialTargets(),
  })

  const callMutation = useMutation({
    mutationFn: () =>
      apiClient.createVobizOutboundCall({
        agent_id: agentId,
        evaluator_id: evaluatorId,
        persona_id: personaId,
        scenario_id: scenarioId,
        to_number: toNumber,
        from_number: fromNumber || undefined,
      }),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['observability-traces'] })
      const traceHint = data?.call_short_id ? ` Trace id ${data.call_short_id}.` : ''
      const suffix = data?.result_id ? ` (result ${data.result_id})` : ''
      showToast(`Outbound call initiated${suffix}.${traceHint} Export STT/LLM/TTS with this id.`, 'success')
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
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1.5">To number *</label>
        <input
          type="tel"
          value={toNumber}
          onChange={(e) => setToNumber(e.target.value)}
          placeholder="+1234567890"
          className={MODERN_INPUT_CLASS}
        />
        {dialTargets.length > 0 && (
          <select
            className={`${MODERN_SELECT_CLASS} mt-2`}
            value=""
            onChange={(e) => e.target.value && setToNumber(e.target.value)}
          >
            <option value="">Contacts…</option>
            {dialTargets.map((t: any) => (
              <option key={t.id} value={t.phone_number}>{t.label || t.phone_number}</option>
            ))}
          </select>
        )}
      </div>
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1.5">From number (optional)</label>
        <input
          type="tel"
          value={fromNumber}
          onChange={(e) => setFromNumber(e.target.value)}
          className={MODERN_INPUT_CLASS}
        />
      </div>
      <Button
        variant="primary"
        onClick={() => callMutation.mutate()}
        isLoading={callMutation.isPending}
        disabled={!toNumber.trim()}
        leftIcon={<Phone className="h-4 w-4" />}
      >
        Place call
      </Button>
    </div>
  )
}
