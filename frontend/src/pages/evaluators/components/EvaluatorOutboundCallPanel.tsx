import EvaluatorPhoneOutboundForm from './EvaluatorPhoneOutboundForm'
import EvaluatorTtsMismatchBanner from './EvaluatorTtsMismatchBanner'
import { EvaluatorSuite } from '../../../lib/api'
import { PhoneOutgoing } from 'lucide-react'
import { suiteHasTtsProviderMismatch } from '../utils/evaluatorTtsMismatch'

interface Props {
  evaluatorId: string
  agentId: string
  personaId: string
  scenarioId: string
  personaName?: string
  scenarioName?: string
  callMedium: string
  callType: string
  suite: EvaluatorSuite
  onEditPersonas?: () => void
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
  suite,
  onEditPersonas,
  showToast,
}: Props) {
  if (callMedium !== 'phone_call' || callType === 'inbound') return null

  const callBlocked = suiteHasTtsProviderMismatch(suite)

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
      <div className="p-6 space-y-4">
        {callBlocked && (
          <EvaluatorTtsMismatchBanner
            suite={suite}
            variant="block"
            onEditPersonas={onEditPersonas}
          />
        )}
        <EvaluatorPhoneOutboundForm
          agentId={agentId}
          evaluatorId={evaluatorId}
          personaId={personaId}
          scenarioId={scenarioId}
          personaName={personaName}
          scenarioName={scenarioName}
          disabled={callBlocked}
          showToast={showToast}
        />
      </div>
    </div>
  )
}
