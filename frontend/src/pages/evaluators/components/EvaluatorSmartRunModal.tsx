import { useState, useEffect } from 'react'
import { createPortal } from 'react-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient, EvaluatorSuite } from '../../../lib/api'
import Button from '../../../components/Button'
import { X, Play } from 'lucide-react'
import { MODERN_INPUT_CLASS, MODERN_SELECT_CLASS } from './evaluatorUi'
import EvaluatorTtsMismatchBanner from './EvaluatorTtsMismatchBanner'
import EvaluatorMessagingTrialTemplateField from './EvaluatorMessagingTrialTemplateField'
import { suiteHasTtsProviderMismatch } from '../utils/evaluatorTtsMismatch'
import { trialSmsTemplateFromAgentConfig } from '../../../lib/twilioSmsTrialTemplates'

interface Props {
  open: boolean
  onClose: () => void
  suites: EvaluatorSuite[]
  showToast: (message: string, type: 'success' | 'error') => void
  /** When provided with onToNumberChange, syncs with the evaluator detail page. */
  toNumber?: string
  onToNumberChange?: (value: string) => void
  trialSmsTemplate?: string
  onTrialSmsTemplateChange?: (value: string) => void
  fromNumber?: string
  onFromNumberChange?: (value: string) => void
}

export default function EvaluatorSmartRunModal({
  open,
  onClose,
  suites,
  showToast,
  toNumber: controlledToNumber,
  onToNumberChange,
  trialSmsTemplate: controlledTrialSmsTemplate,
  onTrialSmsTemplateChange,
  fromNumber: controlledFromNumber,
  onFromNumberChange,
}: Props) {
  const queryClient = useQueryClient()
  const [runsPerCombination, setRunsPerCombination] = useState(1)
  const [internalToNumber, setInternalToNumber] = useState('')
  const [internalTrialSmsTemplate, setInternalTrialSmsTemplate] = useState('')
  const [internalFromNumber, setInternalFromNumber] = useState('')
  const isControlled = onToNumberChange !== undefined
  const toNumber = isControlled ? (controlledToNumber ?? '') : internalToNumber
  const setToNumber = isControlled ? onToNumberChange : setInternalToNumber
  const fromControlled = onFromNumberChange !== undefined
  const fromNumber = fromControlled ? (controlledFromNumber ?? '') : internalFromNumber
  const setFromNumber = fromControlled ? onFromNumberChange : setInternalFromNumber
  const trialTemplateControlled = onTrialSmsTemplateChange !== undefined
  const trialSmsTemplate = trialTemplateControlled
    ? (controlledTrialSmsTemplate ?? '')
    : internalTrialSmsTemplate
  const setTrialSmsTemplate = trialTemplateControlled
    ? onTrialSmsTemplateChange
    : setInternalTrialSmsTemplate

  const singleSuite = suites.length === 1 ? suites[0] : null
  const isInbound = singleSuite?.agent_call_type === 'inbound'
  const isPhoneOutbound =
    singleSuite?.agent_call_medium === 'phone_call' && singleSuite?.agent_call_type !== 'inbound'
  const isWeb = singleSuite?.agent_call_medium === 'web_call'
  const isChat = singleSuite?.agent_call_medium === 'chat'
  const runBlocked = singleSuite ? suiteHasTtsProviderMismatch(singleSuite) && !isInbound : false

  const { data: runAgent, isFetching: runAgentLoading } = useQuery({
    queryKey: ['agent', singleSuite?.agent_id],
    queryFn: () => apiClient.getAgent(singleSuite!.agent_id),
    enabled: open && !!singleSuite?.agent_id && isChat,
  })

  const isMessagingChat = isChat && runAgent?.chat_connection_type === 'messaging_channels'
  const needsRecipientNumber = isPhoneOutbound || isMessagingChat
  const chatRunContextLoading = isChat && !isInbound && runAgentLoading

  useEffect(() => {
    if (!open) return
    if (!isControlled) {
      setInternalToNumber('')
      setInternalFromNumber('')
      setInternalTrialSmsTemplate('')
    }
  }, [open, singleSuite?.id, isControlled])

  useEffect(() => {
    if (!open || trialTemplateControlled || !runAgent) return
    if (runAgent.chat_connection_type !== 'messaging_channels') return
    setInternalTrialSmsTemplate(
      trialSmsTemplateFromAgentConfig(runAgent.chat_connection_config ?? null),
    )
  }, [open, trialTemplateControlled, singleSuite?.id, runAgent?.id])

  const { data: dialTargets = [] } = useQuery({
    queryKey: ['telephony-dial-targets'],
    queryFn: () => apiClient.listTelephonyDialTargets(),
    enabled: open && needsRecipientNumber,
  })

  const runMutation = useMutation({
    mutationFn: ({ suiteId, runs }: { suiteId: string; runs: number }) =>
      apiClient.runEvaluatorSuite(suiteId, {
        runs_per_combination: runs,
        to_number: toNumber || undefined,
        from_number: fromNumber.trim() || undefined,
        ...(isMessagingChat
          ? { twilio_sms_trial_body_template: trialSmsTemplate.trim() }
          : {}),
      }),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['evaluator-suites'] })
      queryClient.invalidateQueries({ queryKey: ['evaluator-results'] })
      showToast(`Queued ${data.total_runs} run${data.total_runs !== 1 ? 's' : ''}`, 'success')
      onClose()
    },
    onError: (err: any) => {
      const detail = err?.response?.data?.detail
      showToast(typeof detail === 'string' ? detail : 'Failed to run suite', 'error')
    },
  })

  if (!open || suites.length === 0) return null

  const totalRuns = singleSuite ? singleSuite.combination_count * runsPerCombination : 0
  const nextIdx = singleSuite
    ? singleSuite.round_robin_index % Math.max(singleSuite.combination_count, 1)
    : 0
  const nextCombo = singleSuite?.combinations[nextIdx]
  const nextRotationLabel = nextCombo
    ? [nextCombo.persona_name, nextCombo.scenario_name].filter(Boolean).join(' · ')
    : undefined

  const runActionBlocked =
    runBlocked ||
    chatRunContextLoading ||
    (isPhoneOutbound && !toNumber.trim()) ||
    (isMessagingChat && !toNumber.trim())

  const modal = (
    <div className="fixed inset-0 z-[9999] overflow-y-auto">
      <div className="flex min-h-screen items-center justify-center p-4">
        <div className="fixed inset-0 bg-gray-500 bg-opacity-75 transition-opacity" onClick={onClose} />
        <div className="relative bg-white rounded-lg shadow-xl w-full max-w-lg flex flex-col">
          <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200">
            <div>
              <h2 className="text-lg font-semibold text-gray-900">
                Run Evaluator Suite{suites.length > 1 ? 's' : ''}
              </h2>
              {singleSuite && !isInbound && (
                <p className="text-sm text-gray-500 mt-0.5">
                  Queue batch evaluation runs across all combinations
                </p>
              )}
            </div>
            <button type="button" onClick={onClose} className="text-gray-400 hover:text-gray-600 p-1 rounded-lg hover:bg-gray-100">
              <X className="h-5 w-5" />
            </button>
          </div>

          <div className="px-6 py-5 space-y-4">
            {suites.length > 1 && (
              <p className="text-sm text-gray-600 rounded-lg bg-gray-50 border border-gray-100 p-3">
                {suites.length} suites selected — run each individually from the list.
              </p>
            )}

            {singleSuite && isInbound && (
              <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm space-y-2">
                <p className="font-medium text-amber-900">Inbound agent — manual runs disabled</p>
                <p className="text-amber-800">
                  Scenarios rotate automatically when callers reach the agent.
                </p>
                <p className="text-amber-800">
                  Next in rotation: <strong>{nextRotationLabel || '—'}</strong> ({nextIdx + 1} of {singleSuite.combination_count})
                </p>
              </div>
            )}

            {singleSuite && !isInbound && runBlocked && (
              <EvaluatorTtsMismatchBanner suite={singleSuite} variant="block" />
            )}

            {singleSuite && !isInbound && (
              <>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1.5">Runs per combination</label>
                  <input
                    type="number"
                    min={1}
                    value={runsPerCombination}
                    onChange={(e) => setRunsPerCombination(Math.max(1, parseInt(e.target.value, 10) || 1))}
                    className={`${MODERN_INPUT_CLASS} w-28`}
                  />
                  <div className="mt-3 rounded-lg bg-indigo-50 border border-indigo-100 px-4 py-3 text-sm text-indigo-800">
                    <strong>{singleSuite.combination_count}</strong> combinations × <strong>{runsPerCombination}</strong> ={' '}
                    <strong>{totalRuns} total runs</strong>
                  </div>
                </div>

                {chatRunContextLoading && (
                  <p className="text-sm text-gray-500">Loading agent connection details…</p>
                )}

                {needsRecipientNumber && !chatRunContextLoading && (
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1.5">
                      {isMessagingChat ? 'Recipient number *' : 'To number *'}
                    </label>
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
                )}

                {isPhoneOutbound && !chatRunContextLoading && (
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1.5">
                      From number (optional)
                    </label>
                    <input
                      type="tel"
                      value={fromNumber}
                      onChange={(e) => setFromNumber(e.target.value)}
                      placeholder="Org caller ID (defaults to agent number)"
                      className={MODERN_INPUT_CLASS}
                    />
                  </div>
                )}

                {isMessagingChat && !chatRunContextLoading && (
                  <EvaluatorMessagingTrialTemplateField
                    value={trialSmsTemplate}
                    onChange={setTrialSmsTemplate}
                  />
                )}

                {isWeb && (
                  <p className="text-sm text-gray-600 rounded-lg bg-gray-50 border border-gray-100 p-3">
                    Web bridge runs will be queued via Celery workers.
                  </p>
                )}
              </>
            )}
          </div>

          <div className="flex justify-end gap-2 px-6 py-4 border-t border-gray-200 bg-gray-50 rounded-b-lg">
            <Button variant="outline" onClick={onClose}>Close</Button>
            {singleSuite && !isInbound && (
              <Button
                variant="primary"
                onClick={() => runMutation.mutate({ suiteId: singleSuite.id, runs: runsPerCombination })}
                isLoading={runMutation.isPending}
                disabled={runActionBlocked}
                leftIcon={<Play className="h-4 w-4" />}
              >
                Queue {totalRuns} runs
              </Button>
            )}
          </div>
        </div>
      </div>
    </div>
  )

  if (typeof document === 'undefined') return null
  return createPortal(modal, document.body)
}
