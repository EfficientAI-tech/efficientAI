import { MessagesSquare, Smartphone } from 'lucide-react'
import { useMutation } from '@tanstack/react-query'
import { apiClient } from '../../../lib/api'
import Button from '../../../components/Button'
import EvaluatorDialTargetFields from './EvaluatorDialTargetFields'
import EvaluatorMessagingTrialTemplateField from './EvaluatorMessagingTrialTemplateField'

interface Props {
  agentId: string
  personaName?: string
  scenarioName?: string
  toNumber: string
  onToNumberChange: (value: string) => void
  trialSmsTemplate: string
  onTrialSmsTemplateChange: (value: string) => void
  showToast: (message: string, type: 'success' | 'error') => void
}

export default function EvaluatorMessagingRunPanel({
  agentId,
  personaName,
  scenarioName,
  toNumber,
  onToNumberChange,
  trialSmsTemplate,
  onTrialSmsTemplateChange,
  showToast,
}: Props) {
  const testSmsMutation = useMutation({
    mutationFn: () =>
      apiClient.testAgentTwilioSms(agentId, {
        ...(toNumber.trim() ? { messaging_recipient: toNumber.trim() } : {}),
        twilio_sms_trial_body_template: trialSmsTemplate.trim(),
      }),
    onSuccess: (data) => {
      const sid = data.message_sid ? ` · ${data.message_sid}` : ''
      showToast(`Test SMS sent to ${data.to} (${data.body_sent})${sid}`, 'success')
    },
    onError: (err: unknown) => {
      const ax = err as { response?: { data?: { detail?: string } }; message?: string }
      const detail = ax.response?.data?.detail
      showToast(typeof detail === 'string' ? detail : ax.message || 'Test SMS failed', 'error')
    },
  })

  return (
    <div className="bg-white shadow rounded-lg overflow-hidden">
      <div className="px-6 py-4 border-b border-gray-200 bg-gradient-to-r from-sky-50/80 to-white">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-lg bg-sky-100 flex items-center justify-center">
            <MessagesSquare className="h-5 w-5 text-sky-600" />
          </div>
          <div>
            <h2 className="text-lg font-semibold text-gray-900">Messaging test</h2>
            <p className="text-sm text-gray-500 mt-0.5">
              Test SMS and eval runs for the first combination below
            </p>
          </div>
        </div>
      </div>
      <div className="p-6 space-y-4">
        {(personaName || scenarioName) && (
          <div className="flex flex-wrap gap-2">
            {personaName ? (
              <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-purple-50 text-purple-700 border border-purple-100">
                {personaName}
              </span>
            ) : null}
            {scenarioName ? (
              <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-green-50 text-green-700 border border-green-100">
                {scenarioName}
              </span>
            ) : null}
          </div>
        )}
        <EvaluatorDialTargetFields
          label="Recipient number *"
          value={toNumber}
          onChange={onToNumberChange}
          helperText="Same number is used for Test send SMS and when you queue suite runs."
        />
        <EvaluatorMessagingTrialTemplateField
          value={trialSmsTemplate}
          onChange={onTrialSmsTemplateChange}
          helperText="Required on Twilio trial accounts. Also used when you queue suite runs."
        />
        <Button
          variant="primary"
          onClick={() => testSmsMutation.mutate()}
          isLoading={testSmsMutation.isPending}
          disabled={!toNumber.trim()}
          leftIcon={<Smartphone className="h-4 w-4" />}
        >
          Test send SMS
        </Button>
      </div>
    </div>
  )
}
