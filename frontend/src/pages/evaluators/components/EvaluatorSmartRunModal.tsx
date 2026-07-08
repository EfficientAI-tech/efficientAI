import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { X, PhoneOutgoing, PhoneIncoming, Globe, AlertTriangle } from 'lucide-react'
import Button from '../../../components/Button'
import EvaluatorPhoneOutboundForm from './EvaluatorPhoneOutboundForm'
import {
  PartitionedEvaluatorsForRun,
  EvaluatorForRun,
  AgentForRun,
} from '../utils/evaluatorRunStrategy'

interface EvaluatorListItem extends EvaluatorForRun {
  evaluator_id: string
  name?: string | null
  persona_id?: string | null
  scenario_id?: string | null
}

interface EvaluatorSmartRunModalProps {
  partition: PartitionedEvaluatorsForRun
  evaluators: EvaluatorListItem[]
  agentsById: Record<string, AgentForRun>
  personasById: Record<string, { id: string; name: string }>
  scenariosById: Record<string, { id: string; name: string }>
  runCount: number
  onRunCountChange: (count: number) => void
  onClose: () => void
  onExecuteWebRuns: () => void
  isExecutingWebRuns: boolean
  showToast: (message: string, type: 'success' | 'error') => void
}

function evaluatorLabel(evaluator: EvaluatorListItem): string {
  return evaluator.name || evaluator.evaluator_id
}

export default function EvaluatorSmartRunModal({
  partition,
  evaluators,
  agentsById,
  personasById,
  scenariosById,
  runCount,
  onRunCountChange,
  onClose,
  onExecuteWebRuns,
  isExecutingWebRuns,
  showToast,
}: EvaluatorSmartRunModalProps) {
  const evaluatorsById = useMemo(
    () => Object.fromEntries(evaluators.map((e) => [e.id, e])),
    [evaluators]
  )

  const [selectedPhoneOutboundId, setSelectedPhoneOutboundId] = useState<string>(
    partition.phoneOutbound[0]?.id ?? ''
  )

  useEffect(() => {
    if (partition.phoneOutbound.length > 0 && !partition.phoneOutbound.some((e) => e.id === selectedPhoneOutboundId)) {
      setSelectedPhoneOutboundId(partition.phoneOutbound[0].id)
    }
  }, [partition.phoneOutbound, selectedPhoneOutboundId])

  const selectedPhoneOutbound = evaluatorsById[selectedPhoneOutboundId]
  const selectedPhoneAgent = selectedPhoneOutbound?.agent_id
    ? agentsById[selectedPhoneOutbound.agent_id]
    : undefined

  const hasWeb = partition.webBridge.length > 0
  const hasPhoneOutbound = partition.phoneOutbound.length > 0
  const hasPhoneInbound = partition.phoneInbound.length > 0
  const hasUnsupported = partition.unsupported.length > 0
  const isMixed =
    [hasWeb, hasPhoneOutbound, hasPhoneInbound].filter(Boolean).length > 1 || hasUnsupported

  const title = isMixed
    ? 'Run selected evaluators'
    : hasPhoneOutbound && !hasWeb && !hasPhoneInbound
      ? 'Place outbound call'
      : hasPhoneInbound && !hasWeb && !hasPhoneOutbound
        ? 'Inbound evaluators selected'
        : 'Run Evaluators'

  const canExecuteWeb = hasWeb && !isExecutingWebRuns

  return (
    <div className="fixed inset-0 z-50 overflow-y-auto">
      <div className="flex min-h-screen items-center justify-center p-4">
        <div className="fixed inset-0 bg-gray-500 bg-opacity-75 transition-opacity" onClick={onClose} />
        <div className="relative bg-white rounded-lg shadow-xl max-w-lg w-full p-6 max-h-[90vh] overflow-y-auto">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-lg font-semibold text-gray-900">{title}</h2>
            <button onClick={onClose} className="text-gray-400 hover:text-gray-500" type="button">
              <X className="h-5 w-5" />
            </button>
          </div>

          {hasPhoneInbound && (
            <div className="mb-4 rounded-lg border border-amber-200 bg-amber-50 p-4">
              <div className="flex items-start gap-2">
                <PhoneIncoming className="h-5 w-5 text-amber-700 mt-0.5 shrink-0" />
                <div>
                  <p className="text-sm font-medium text-amber-900">Manual inbound test required</p>
                  <p className="text-sm text-amber-800 mt-1">
                    Inbound phone evaluators must be tested by calling the agent number manually. Open evaluator
                    detail for step-by-step instructions.
                  </p>
                  <ul className="mt-2 space-y-1">
                    {partition.phoneInbound.map((e) => (
                      <li key={e.id}>
                        <Link
                          to={`/evaluate-test-agents/${e.id}`}
                          className="text-sm font-medium text-primary-700 hover:text-primary-900 underline"
                          onClick={onClose}
                        >
                          {evaluatorLabel(evaluatorsById[e.id] ?? (e as EvaluatorListItem))}
                        </Link>
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
            </div>
          )}

          {hasUnsupported && (
            <div className="mb-4 rounded-lg border border-red-200 bg-red-50 p-4">
              <div className="flex items-start gap-2">
                <AlertTriangle className="h-5 w-5 text-red-700 mt-0.5 shrink-0" />
                <div>
                  <p className="text-sm font-medium text-red-900">Cannot run automatically</p>
                  <ul className="mt-2 space-y-1 text-sm text-red-800">
                    {partition.unsupported.map((e) => (
                      <li key={e.id}>{evaluatorLabel(evaluatorsById[e.id] ?? (e as EvaluatorListItem))}</li>
                    ))}
                  </ul>
                </div>
              </div>
            </div>
          )}

          {hasWeb && (
            <div className="mb-4 rounded-lg border border-gray-200 p-4">
              <div className="flex items-center gap-2 mb-2">
                <Globe className="h-4 w-4 text-gray-600" />
                <p className="text-sm font-medium text-gray-900">
                  Web bridge ({partition.webBridge.length} evaluator{partition.webBridge.length > 1 ? 's' : ''})
                </p>
              </div>
              <ul className="mb-3 text-sm text-gray-600 list-disc list-inside">
                {partition.webBridge.map((e) => (
                  <li key={e.id}>{evaluatorLabel(evaluatorsById[e.id] ?? (e as EvaluatorListItem))}</li>
                ))}
              </ul>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                How many times to run each?
              </label>
              <div className="flex items-center space-x-3">
                <button
                  type="button"
                  onClick={() => onRunCountChange(Math.max(1, runCount - 1))}
                  className="w-10 h-10 rounded-lg border border-gray-300 flex items-center justify-center text-gray-600 hover:bg-gray-50"
                >
                  -
                </button>
                <input
                  type="number"
                  min="1"
                  max="50"
                  value={runCount}
                  onChange={(e) => {
                    const val = parseInt(e.target.value, 10)
                    if (!Number.isNaN(val) && val >= 1 && val <= 50) onRunCountChange(val)
                  }}
                  className="w-20 text-center px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500"
                />
                <button
                  type="button"
                  onClick={() => onRunCountChange(Math.min(50, runCount + 1))}
                  className="w-10 h-10 rounded-lg border border-gray-300 flex items-center justify-center text-gray-600 hover:bg-gray-50"
                >
                  +
                </button>
              </div>
              <p className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-md px-3 py-2 mt-3">
                First-time web runs may take longer while audio evaluation models are downloaded and cached.
              </p>
            </div>
          )}

          {hasPhoneOutbound && selectedPhoneOutbound && selectedPhoneAgent && (
            <div className="mb-4 rounded-lg border border-gray-200 p-4">
              <div className="flex items-center gap-2 mb-2">
                <PhoneOutgoing className="h-4 w-4 text-primary-600" />
                <p className="text-sm font-medium text-gray-900">
                  Phone outbound ({partition.phoneOutbound.length} evaluator
                  {partition.phoneOutbound.length > 1 ? 's' : ''})
                </p>
              </div>
              {partition.phoneOutbound.length > 1 && (
                <div className="mb-3">
                  <label className="block text-sm font-medium text-gray-700 mb-1">Select evaluator</label>
                  <select
                    value={selectedPhoneOutboundId}
                    onChange={(e) => setSelectedPhoneOutboundId(e.target.value)}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg bg-white text-sm"
                  >
                    {partition.phoneOutbound.map((e) => (
                      <option key={e.id} value={e.id}>
                        {evaluatorLabel(evaluatorsById[e.id] ?? (e as EvaluatorListItem))}
                      </option>
                    ))}
                  </select>
                  <p className="text-xs text-gray-500 mt-1">
                    Place one call at a time. Switch evaluator to call the next one.
                  </p>
                </div>
              )}
              <EvaluatorPhoneOutboundForm
                key={selectedPhoneOutboundId}
                evaluatorId={selectedPhoneOutbound.id}
                agentId={selectedPhoneOutbound.agent_id!}
                personaId={selectedPhoneOutbound.persona_id!}
                scenarioId={selectedPhoneOutbound.scenario_id!}
                personaName={
                  selectedPhoneOutbound.persona_id
                    ? personasById[selectedPhoneOutbound.persona_id]?.name
                    : undefined
                }
                scenarioName={
                  selectedPhoneOutbound.scenario_id
                    ? scenariosById[selectedPhoneOutbound.scenario_id]?.name
                    : undefined
                }
                agentPhoneNumber={selectedPhoneAgent.phone_number as string | null | undefined}
                showToast={showToast}
                compact
              />
            </div>
          )}

          <div className="flex justify-end gap-2 pt-2 border-t border-gray-100">
            <Button variant="ghost" onClick={onClose}>
              {hasWeb ? 'Cancel' : 'Close'}
            </Button>
            {hasWeb && (
              <Button onClick={onExecuteWebRuns} isLoading={isExecutingWebRuns} disabled={!canExecuteWeb}>
                Run {partition.webBridge.length * runCount} evaluation
                {partition.webBridge.length * runCount > 1 ? 's' : ''}
              </Button>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
