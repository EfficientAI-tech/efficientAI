import { useMemo } from 'react'
import { MessagesSquare, Smartphone } from 'lucide-react'
import { useMutation } from '@tanstack/react-query'
import { apiClient } from '../../../lib/api'
import Button from '../../../components/Button'
import EvaluatorDialTargetFields from './EvaluatorDialTargetFields'
import EvaluatorMessagingTrialTemplateField from './EvaluatorMessagingTrialTemplateField'
import { useOrgTelephony } from '../../../hooks/useOrgTelephony'
import {
  messagingEvalProfile,
  smsCarrierFromTelephony,
} from '../../../lib/messagingEvalUi'

interface Props {
  agentId: string
  chatConnectionConfig?: Record<string, unknown> | null
  telephonyPhoneNumberId?: string | null
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
  chatConnectionConfig,
  telephonyPhoneNumberId,
  personaName,
  scenarioName,
  toNumber,
  onToNumberChange,
  trialSmsTemplate,
  onTrialSmsTemplateChange,
  showToast,
}: Props) {
  const { activeNumbers } = useOrgTelephony()

  const profile = useMemo(
    () =>
      messagingEvalProfile({
        chatConnectionConfig,
        telephonyPhoneNumberId,
        smsCarrier: smsCarrierFromTelephony(telephonyPhoneNumberId, activeNumbers),
      }),
    [chatConnectionConfig, telephonyPhoneNumberId, activeNumbers],
  )

  const testSmsMutation = useMutation({
    mutationFn: async () => {
      const recipient = toNumber.trim()
      const payload = recipient ? { messaging_recipient: recipient } : {}
      if (profile.testSend === 'meta_whatsapp') {
        return apiClient.testAgentMetaWhatsapp(agentId, payload)
      }
      if (profile.testSend === 'telnyx_sms') {
        return apiClient.testAgentTelnyxSms(agentId, payload)
      }
      if (profile.testSend === 'twilio_sms') {
        return apiClient.testAgentTwilioSms(agentId, {
          ...payload,
          twilio_sms_trial_body_template: trialSmsTemplate.trim(),
        })
      }
      throw new Error('Test send is not available for this channel')
    },
    onSuccess: (data) => {
      const sid =
        'message_sid' in data && data.message_sid
          ? ` · ${data.message_sid}`
          : 'message_id' in data && data.message_id
            ? ` · ${data.message_id}`
            : ''
      const template =
        'template_sent' in data && data.template_sent ? ` · ${data.template_sent}` : ''
      const bodyBit =
        'body_sent' in data && data.body_sent ? ` (${data.body_sent})` : template
      showToast(`Test ${profile.testSendSuccessPrefix} sent to ${data.to}${bodyBit}${sid}`, 'success')
    },
    onError: (err: unknown) => {
      const ax = err as { response?: { data?: { detail?: string } }; message?: string }
      const detail = ax.response?.data?.detail
      showToast(
        typeof detail === 'string' ? detail : ax.message || 'Test message failed',
        'error',
      )
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
            <p className="text-sm text-gray-500 mt-0.5">{profile.panelSubtitle}</p>
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
          label={profile.recipientLabel}
          value={toNumber}
          onChange={onToNumberChange}
          helperText={profile.recipientHelper}
        />
        {profile.showTrialTemplate ? (
          <EvaluatorMessagingTrialTemplateField
            value={trialSmsTemplate}
            onChange={onTrialSmsTemplateChange}
            helperText={profile.trialTemplateHelper}
          />
        ) : null}
        {profile.testSendButtonLabel ? (
          <Button
            variant="primary"
            onClick={() => testSmsMutation.mutate()}
            isLoading={testSmsMutation.isPending}
            disabled={!toNumber.trim()}
            leftIcon={<Smartphone className="h-4 w-4" />}
          >
            {profile.testSendButtonLabel}
          </Button>
        ) : null}
      </div>
    </div>
  )
}
