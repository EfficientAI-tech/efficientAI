import { Link } from 'react-router-dom'
import { PhoneIncoming, ExternalLink } from 'lucide-react'

interface EvaluatorInboundCallPanelProps {
  agentPhoneNumber?: string | null
  personaName?: string
  scenarioName?: string
  callMedium: string
  callType: string
}

export default function EvaluatorInboundCallPanel({
  agentPhoneNumber,
  personaName,
  scenarioName,
  callMedium,
  callType,
}: EvaluatorInboundCallPanelProps) {
  if (callMedium !== 'phone_call' || callType !== 'inbound') {
    return null
  }

  return (
    <div className="bg-white rounded-lg shadow p-6 mb-6">
      <div className="flex items-center gap-2 mb-2">
        <PhoneIncoming className="h-5 w-5 text-primary-600" />
        <h3 className="text-lg font-semibold text-gray-900">Inbound call test</h3>
      </div>
      <p className="text-sm text-gray-600 mb-4">
        Inbound phone evaluators are tested by calling the agent number from your phone. Persona and scenario
        context is not attached automatically on inbound calls.
      </p>

      {(personaName || scenarioName) && (
        <div className="mb-4 flex flex-wrap gap-2 text-xs">
          {personaName && (
            <span className="inline-flex items-center px-2.5 py-1 rounded-full bg-purple-50 text-purple-800 border border-purple-200">
              Persona: {personaName}
            </span>
          )}
          {scenarioName && (
            <span className="inline-flex items-center px-2.5 py-1 rounded-full bg-blue-50 text-blue-800 border border-blue-200">
              Scenario: {scenarioName}
            </span>
          )}
        </div>
      )}

      <div className="rounded-lg border border-teal-200 bg-teal-50 px-4 py-3 mb-4">
        <p className="text-xs font-medium uppercase tracking-wide text-teal-800 mb-1">Agent inbound number</p>
        {agentPhoneNumber ? (
          <p className="text-lg font-mono font-semibold text-teal-900">{agentPhoneNumber}</p>
        ) : (
          <p className="text-sm text-amber-800">No inbound phone number configured on this agent.</p>
        )}
      </div>

      <ol className="list-decimal list-inside space-y-2 text-sm text-gray-700 mb-4">
        <li>Call the agent number above from your phone.</li>
        <li>Complete the conversation with the agent.</li>
        <li>Find the call under Observability → Call Recordings.</li>
        <li>Run evaluation against this evaluator from the call detail or Results page.</li>
      </ol>

      <div className="flex flex-wrap gap-3">
        <Link
          to="/observability/calls"
          className="inline-flex items-center gap-1.5 text-sm font-medium text-primary-600 hover:text-primary-800"
        >
          <ExternalLink className="h-4 w-4" />
          Open Call Recordings
        </Link>
        <Link
          to="/results"
          className="inline-flex items-center gap-1.5 text-sm font-medium text-primary-600 hover:text-primary-800"
        >
          <ExternalLink className="h-4 w-4" />
          Open Results
        </Link>
      </div>
    </div>
  )
}
