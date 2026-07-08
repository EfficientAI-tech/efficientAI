import { PhoneOutgoing } from 'lucide-react'
import EvaluatorPhoneOutboundForm from './EvaluatorPhoneOutboundForm'

interface EvaluatorOutboundCallPanelProps {
  evaluatorId: string
  agentId: string
  personaId: string
  scenarioId: string
  personaName?: string
  scenarioName?: string
  agentPhoneNumber?: string | null
  callMedium: string
  callType: string
  showToast: (message: string, type: 'success' | 'error') => void
}

export default function EvaluatorOutboundCallPanel({
  callMedium,
  callType,
  ...formProps
}: EvaluatorOutboundCallPanelProps) {
  if (callMedium !== 'phone_call' || callType !== 'outbound') {
    return null
  }

  return (
    <div className="bg-white rounded-lg shadow p-6 mb-6">
      <div className="flex items-center gap-2 mb-2">
        <PhoneOutgoing className="h-5 w-5 text-primary-600" />
        <h3 className="text-lg font-semibold text-gray-900">Outbound call</h3>
      </div>
      <p className="text-sm text-gray-600 mb-4">
        Place a test outbound call using this evaluator&apos;s mapped agent, persona, and scenario.
      </p>
      <EvaluatorPhoneOutboundForm {...formProps} />
    </div>
  )
}
