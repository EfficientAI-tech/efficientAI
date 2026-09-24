import { useMutation } from '@tanstack/react-query'
import { Loader2, RefreshCw } from 'lucide-react'
import { Integration, type IntegrationPlatform } from '../../../../types/api'
import { apiClient } from '../../../../lib/api'
import { CREATE_WIZARD_FIELD_CLASS, CREATE_WIZARD_LABEL_CLASS } from './createWizardUi'
import type { ChatIntegrationOptionId } from './ChatIntegrationTypeStep'
import type { CreateAgentFormData } from './createAgentTypes'

export type ChatConnectionConfigForm = {
  apiBaseUrl: string
  apiMessagePath: string
  apiAuthHeader: string
  apiAuthValue: string
  messagingChannel: 'whatsapp' | 'sms' | ''
  messagingIntegrationId: string
  messagingSenderId: string
  outboundWebhookUrl: string
  messagingRecipient: string
  messagingSyncReplyUrl: string
  metaWhatsappPhoneNumberId: string
  metaWhatsappAccessToken: string
  twilioAccountSid: string
  twilioAuthToken: string
  twilioFrom: string
}

export const DEFAULT_CHAT_CONNECTION_CONFIG: ChatConnectionConfigForm = {
  apiBaseUrl: '',
  apiMessagePath: '/chat',
  apiAuthHeader: 'Authorization',
  apiAuthValue: '',
  messagingChannel: '',
  messagingIntegrationId: '',
  messagingSenderId: '',
  outboundWebhookUrl: '',
  messagingRecipient: '',
  messagingSyncReplyUrl: '',
  metaWhatsappPhoneNumberId: '',
  metaWhatsappAccessToken: '',
  twilioAccountSid: '',
  twilioAuthToken: '',
  twilioFrom: '',
}

interface ChatConnectionDetailsStepProps {
  integrationType: ChatIntegrationOptionId
  formData: CreateAgentFormData
  onFormChange: (patch: Partial<CreateAgentFormData>) => void
  integrations: Integration[]
  selectedPlatform: IntegrationPlatform | null
  onSelectPlatform: (platform: IntegrationPlatform | null) => void
  config: ChatConnectionConfigForm
  onConfigChange: (patch: Partial<ChatConnectionConfigForm>) => void
  productionPrompt: string
  onProductionPromptChange: (value: string) => void
  onPromptFetched: (prompt: string) => void
  showToast: (message: string, type: 'success' | 'error') => void
  embedded?: boolean
}

export function ChatProviderPromptBlock({
  formData,
  productionPrompt,
  onProductionPromptChange,
  onPromptFetched,
  showToast,
}: {
  formData: CreateAgentFormData
  productionPrompt: string
  onProductionPromptChange: (value: string) => void
  onPromptFetched: (prompt: string) => void
  showToast: (message: string, type: 'success' | 'error') => void
}) {
  const fetchPromptMutation = useMutation({
    mutationFn: () => {
      if (!formData.voice_ai_integration_id || !formData.voice_ai_agent_id?.trim()) {
        throw new Error('Select integration and provider agent ID first')
      }
      return apiClient.previewIntegrationAgentPrompt(
        formData.voice_ai_integration_id,
        formData.voice_ai_agent_id.trim(),
      )
    },
    onSuccess: (data: { provider_prompt?: string }) => {
      onProductionPromptChange(data.provider_prompt || '')
      onPromptFetched(data.provider_prompt || '')
      showToast('Production prompt imported from provider', 'success')
    },
    onError: (err: unknown) => {
      const message =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        (err as Error)?.message ||
        'Failed to fetch prompt'
      showToast(String(message), 'error')
    },
  })

  return (
    <div className="space-y-2 pt-2 border-t border-gray-100">
      <div className="flex items-center justify-between gap-2">
        <label className={CREATE_WIZARD_LABEL_CLASS}>Production prompt *</label>
        <button
          type="button"
          disabled={fetchPromptMutation.isPending}
          onClick={() => fetchPromptMutation.mutate()}
          className="inline-flex items-center gap-1 rounded-lg border border-gray-200 bg-white px-2.5 py-1.5 text-xs font-medium text-gray-800 hover:bg-gray-50"
        >
          {fetchPromptMutation.isPending ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <RefreshCw className="h-3.5 w-3.5" />
          )}
          Import from provider
        </button>
      </div>
      <textarea
        className={`${CREATE_WIZARD_FIELD_CLASS} min-h-[120px] font-mono text-xs resize-y`}
        value={productionPrompt}
        onChange={(e) => onProductionPromptChange(e.target.value)}
        placeholder="Production system prompt used for evaluation"
        rows={5}
      />
    </div>
  )
}

export function validateChatConnectionDetails(
  integrationType: ChatIntegrationOptionId,
  formData: CreateAgentFormData,
  config: ChatConnectionConfigForm,
  productionPrompt: string,
  selectedPlatform?: IntegrationPlatform | null,
): boolean {
  if (integrationType === 'provider_chat') {
    return Boolean(
      selectedPlatform &&
        formData.voice_ai_integration_id?.trim() &&
        formData.voice_ai_agent_id?.trim() &&
        productionPrompt.trim(),
    )
  }
  if (integrationType === 'customer_api') {
    return Boolean(config.apiBaseUrl.trim() && productionPrompt.trim())
  }
  if (integrationType === 'messaging_channels') {
    return Boolean(config.messagingChannel && productionPrompt.trim())
  }
  return true
}

export default function ChatConnectionDetailsStep({
  integrationType,
  formData: _formData,
  onFormChange: _onFormChange,
  integrations,
  selectedPlatform: _selectedPlatform,
  onSelectPlatform: _onSelectPlatform,
  config,
  onConfigChange,
  productionPrompt: _productionPrompt,
  onProductionPromptChange: _onProductionPromptChange,
  onPromptFetched: _onPromptFetched,
  showToast: _showToast,
  embedded = false,
}: ChatConnectionDetailsStepProps) {
  const sectionClass = embedded
    ? 'space-y-3 pt-3 border-t border-gray-100'
    : 'space-y-4'
  const activeIntegrations = integrations.filter((i) => i.is_active)

  if (integrationType === 'internal_llm') {
    return null
  }

  if (integrationType === 'provider_chat') {
    return null
  }

  if (integrationType === 'customer_api') {
    return (
      <div className={sectionClass}>
        <p className="text-xs font-medium text-gray-700">HTTP API</p>
        <div>
          <label className={CREATE_WIZARD_LABEL_CLASS}>Base URL *</label>
          <input
            className={CREATE_WIZARD_FIELD_CLASS}
            value={config.apiBaseUrl}
            onChange={(e) => onConfigChange({ apiBaseUrl: e.target.value })}
            placeholder="https://api.example.com/agent"
          />
        </div>
        <div className="grid grid-cols-2 gap-2">
          <div>
            <label className={CREATE_WIZARD_LABEL_CLASS}>Path</label>
            <input
              className={CREATE_WIZARD_FIELD_CLASS}
              value={config.apiMessagePath}
              onChange={(e) => onConfigChange({ apiMessagePath: e.target.value })}
              placeholder="/chat"
            />
          </div>
          <div>
            <label className={CREATE_WIZARD_LABEL_CLASS}>Auth header</label>
            <input
              className={CREATE_WIZARD_FIELD_CLASS}
              value={config.apiAuthHeader}
              onChange={(e) => onConfigChange({ apiAuthHeader: e.target.value })}
              placeholder="Authorization"
            />
          </div>
        </div>
        <div>
          <label className={CREATE_WIZARD_LABEL_CLASS}>Auth value</label>
          <input
            type="password"
            className={CREATE_WIZARD_FIELD_CLASS}
            value={config.apiAuthValue}
            onChange={(e) => onConfigChange({ apiAuthValue: e.target.value })}
            placeholder="Optional"
          />
        </div>
      </div>
    )
  }

  if (integrationType === 'messaging_channels') {
    return (
      <div className={sectionClass}>
        <p className="text-xs font-medium text-gray-700">Channel</p>
        <div className="grid grid-cols-2 gap-2">
          {(['whatsapp', 'sms'] as const).map((ch) => (
            <button
              key={ch}
              type="button"
              onClick={() => onConfigChange({ messagingChannel: ch })}
              className={`rounded-lg border-2 px-3 py-2 text-sm font-medium capitalize ${
                config.messagingChannel === ch
                  ? 'border-primary-600 bg-primary-50 text-primary-900'
                  : 'border-gray-200 text-gray-700 hover:border-gray-300'
              }`}
            >
              {ch}
            </button>
          ))}
        </div>
        {activeIntegrations.length > 0 ? (
          <div>
            <label className={CREATE_WIZARD_LABEL_CLASS}>Integration</label>
            <select
              className={CREATE_WIZARD_FIELD_CLASS}
              value={config.messagingIntegrationId}
              onChange={(e) => onConfigChange({ messagingIntegrationId: e.target.value })}
            >
              <option value="">Optional</option>
              {activeIntegrations.map((i) => (
                <option key={i.id} value={i.id}>
                  {i.name || i.platform}
                </option>
              ))}
            </select>
          </div>
        ) : null}
        <div>
          <label className={CREATE_WIZARD_LABEL_CLASS}>Sender</label>
          <input
            className={CREATE_WIZARD_FIELD_CLASS}
            value={config.messagingSenderId}
            onChange={(e) => onConfigChange({ messagingSenderId: e.target.value })}
            placeholder="Optional"
          />
        </div>
        <div>
          <label className={CREATE_WIZARD_LABEL_CLASS}>Post-prod webhook URL</label>
          <input
            className={CREATE_WIZARD_FIELD_CLASS}
            value={config.outboundWebhookUrl}
            onChange={(e) => onConfigChange({ outboundWebhookUrl: e.target.value })}
            placeholder="Optional — live eval replies"
          />
        </div>
        <div>
          <label className={CREATE_WIZARD_LABEL_CLASS}>Eval recipient</label>
          <input
            className={CREATE_WIZARD_FIELD_CLASS}
            value={config.messagingRecipient}
            onChange={(e) => onConfigChange({ messagingRecipient: e.target.value })}
            placeholder="E.164 — outbound send target for live eval"
          />
        </div>
        <div>
          <label className={CREATE_WIZARD_LABEL_CLASS}>Sync reply URL</label>
          <input
            className={CREATE_WIZARD_FIELD_CLASS}
            value={config.messagingSyncReplyUrl}
            onChange={(e) => onConfigChange({ messagingSyncReplyUrl: e.target.value })}
            placeholder="Optional POST — agent reply after carrier send"
          />
        </div>
        {config.messagingChannel === 'whatsapp' ? (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            <div>
              <label className={CREATE_WIZARD_LABEL_CLASS}>Meta phone number ID</label>
              <input
                className={CREATE_WIZARD_FIELD_CLASS}
                value={config.metaWhatsappPhoneNumberId}
                onChange={(e) => onConfigChange({ metaWhatsappPhoneNumberId: e.target.value })}
              />
            </div>
            <div>
              <label className={CREATE_WIZARD_LABEL_CLASS}>Meta access token</label>
              <input
                type="password"
                className={CREATE_WIZARD_FIELD_CLASS}
                value={config.metaWhatsappAccessToken}
                onChange={(e) => onConfigChange({ metaWhatsappAccessToken: e.target.value })}
              />
            </div>
          </div>
        ) : null}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
          <div>
            <label className={CREATE_WIZARD_LABEL_CLASS}>Twilio SID</label>
            <input
              className={CREATE_WIZARD_FIELD_CLASS}
              value={config.twilioAccountSid}
              onChange={(e) => onConfigChange({ twilioAccountSid: e.target.value })}
            />
          </div>
          <div>
            <label className={CREATE_WIZARD_LABEL_CLASS}>Twilio token</label>
            <input
              type="password"
              className={CREATE_WIZARD_FIELD_CLASS}
              value={config.twilioAuthToken}
              onChange={(e) => onConfigChange({ twilioAuthToken: e.target.value })}
            />
          </div>
          <div>
            <label className={CREATE_WIZARD_LABEL_CLASS}>Twilio from</label>
            <input
              className={CREATE_WIZARD_FIELD_CLASS}
              value={config.twilioFrom}
              onChange={(e) => onConfigChange({ twilioFrom: e.target.value })}
            />
          </div>
        </div>
      </div>
    )
  }

  return null
}
