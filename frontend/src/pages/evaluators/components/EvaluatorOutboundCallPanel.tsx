import EvaluatorPhoneOutboundForm from './EvaluatorPhoneOutboundForm'
import { PhoneOutgoing } from 'lucide-react'

interface Props {
  evaluatorId: string
  agentId: string
  personaId: string
  scenarioId: string
  personaName?: string
  scenarioName?: string
  callMedium: string
  callType: string
  showToast: (message: string, type: 'success' | 'error') => void
}

export default function EvaluatorOutboundCallPanel({
  evaluatorId,
  agentId,
  personaId,
  scenarioId,
  personaName,
  scenarioName,
  callMedium,
  callType,
  showToast,
}: Props) {
  if (callMedium !== 'phone_call' || callType === 'inbound') return null

  return (
    <div className="bg-white shadow rounded-lg overflow-hidden">
      <div className="px-6 py-4 border-b border-gray-200 bg-gradient-to-r from-emerald-50/80 to-white">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-lg bg-emerald-100 flex items-center justify-center">
            <PhoneOutgoing className="h-5 w-5 text-emerald-600" />
          </div>
          <div>
            <h2 className="text-lg font-semibold text-gray-900">Outbound Phone Test</h2>
            <p className="text-sm text-gray-500 mt-0.5">Place a single outbound call for the first combination</p>
          </div>
        </div>
      </div>
      <div className="p-6">
        <EvaluatorPhoneOutboundForm
          agentId={agentId}
          evaluatorId={evaluatorId}
          personaId={personaId}
          scenarioId={scenarioId}
          personaName={personaName}
          scenarioName={scenarioName}
          showToast={showToast}
        />
      </div>
    </div>
  )
}
