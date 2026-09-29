import { useState, type ReactNode } from 'react'
import { useMutation } from '@tanstack/react-query'
import {
  ChevronDown,
  Globe,
  Loader2,
  MessageCircle,
  MessagesSquare,
  RefreshCw,
  Smartphone,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { Integration, type IntegrationPlatform } from '../../../../types/api'
import { apiClient } from '../../../../lib/api'
import { CHAT_CONFIG_SECRET_MASK, isStoredChatSecret } from '../../../../lib/chatConnectionSecrets'
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

function ConfigPanel({
  icon: Icon,
  title,
  children,
}: {
  icon: LucideIcon
  title: string
  children: ReactNode
}) {
  return (
    <div className="rounded-xl border border-gray-200 bg-white shadow-sm overflow-hidden">
      <div className="flex items-center gap-2.5 px-4 py-3 border-b border-gray-100 bg-gray-50/80">
        <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary-50 text-primary-700">
          <Icon className="h-5 w-5" strokeWidth={1.75} />
        </span>
        <h3 className="text-sm font-semibold text-gray-900">{title}</h3>
      </div>
      <div className="p-4 space-y-4">{children}</div>
    </div>
  )
}

function AdvancedFields({
  label,
  children,
}: {
  label?: string
  children: ReactNode
}) {
  const [open, setOpen] = useState(false)
  return (
    <div className="border-t border-gray-100 pt-3">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between text-xs font-medium text-gray-600 hover:text-gray-900"
      >
        {label ?? 'Advanced'}
        <ChevronDown className={`h-4 w-4 transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>
      {open ? <div className="mt-3 space-y-3">{children}</div> : null}
    </div>
  )
}

function ChannelOption({
  label,
  icon: Icon,
  selected,
  onSelect,
}: {
  label: string
  icon: LucideIcon
  selected: boolean
  onSelect: () => void
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      className={`flex flex-1 items-center justify-center gap-2 rounded-lg border-2 px-3 py-2.5 text-sm font-medium transition-colors ${
        selected
          ? 'border-primary-600 bg-primary-50 text-primary-900'
          : 'border-gray-200 text-gray-700 hover:border-gray-300 bg-white'
      }`}
    >
      <Icon className="h-4 w-4" strokeWidth={1.75} />
      {label}
    </button>
  )
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
        { agentChannel: 'chat' },
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
  _selectedPlatform?: IntegrationPlatform | null,
  options?: { requireProductionPrompt?: boolean },
): boolean {
  const requirePrompt = options?.requireProductionPrompt ?? true
  if (integrationType === 'provider_chat') {
    const linked = Boolean(
      formData.voice_ai_integration_id?.trim() && formData.voice_ai_agent_id?.trim(),
    )
    return linked && (!requirePrompt || Boolean(productionPrompt.trim()))
  }
  if (integrationType === 'customer_api') {
    return Boolean(config.apiBaseUrl.trim() && (!requirePrompt || productionPrompt.trim()))
  }
  if (integrationType === 'messaging_channels') {
    return Boolean(config.messagingChannel && (!requirePrompt || productionPrompt.trim()))
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
  const sectionClass = embedded ? 'w-full' : 'space-y-4'
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
        <ConfigPanel icon={Globe} title="HTTP API">
          <div>
            <label className={CREATE_WIZARD_LABEL_CLASS}>Base URL *</label>
            <input
              className={CREATE_WIZARD_FIELD_CLASS}
              value={config.apiBaseUrl}
              onChange={(e) => onConfigChange({ apiBaseUrl: e.target.value })}
              placeholder="https://api.example.com"
            />
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label className={CREATE_WIZARD_LABEL_CLASS}>Message path</label>
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
              placeholder={
                isStoredChatSecret(config.apiAuthValue)
                  ? `${CHAT_CONFIG_SECRET_MASK} (stored — enter new value to replace)`
                  : 'Bearer token or API key'
              }
            />
          </div>
        </ConfigPanel>
      </div>
    )
  }

  if (integrationType === 'messaging_channels') {
    const channel = config.messagingChannel
    return (
      <div className={sectionClass}>
        <ConfigPanel icon={MessagesSquare} title="Messaging">
          <div>
            <label className={CREATE_WIZARD_LABEL_CLASS}>Channel *</label>
            <div className="flex gap-2">
              <ChannelOption
                label="WhatsApp"
                icon={MessageCircle}
                selected={channel === 'whatsapp'}
                onSelect={() => onConfigChange({ messagingChannel: 'whatsapp' })}
              />
              <ChannelOption
                label="SMS"
                icon={Smartphone}
                selected={channel === 'sms'}
                onSelect={() => onConfigChange({ messagingChannel: 'sms' })}
              />
            </div>
          </div>
          <div>
            <label className={CREATE_WIZARD_LABEL_CLASS}>Eval recipient</label>
            <input
              className={CREATE_WIZARD_FIELD_CLASS}
              value={config.messagingRecipient}
              onChange={(e) => onConfigChange({ messagingRecipient: e.target.value })}
              placeholder="+14155551234"
            />
          </div>

          {channel === 'whatsapp' ? (
            <div className="rounded-lg border border-emerald-100 bg-emerald-50/40 p-3 space-y-3">
              <p className="text-xs font-medium text-emerald-900">Meta WhatsApp Cloud</p>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div>
                  <label className={CREATE_WIZARD_LABEL_CLASS}>Phone number ID</label>
                  <input
                    className={CREATE_WIZARD_FIELD_CLASS}
                    value={config.metaWhatsappPhoneNumberId}
                    onChange={(e) => onConfigChange({ metaWhatsappPhoneNumberId: e.target.value })}
                    placeholder="From Meta developer console"
                  />
                </div>
                <div>
                  <label className={CREATE_WIZARD_LABEL_CLASS}>Access token</label>
                  <input
                    type="password"
                    className={CREATE_WIZARD_FIELD_CLASS}
                    value={config.metaWhatsappAccessToken}
                    onChange={(e) => onConfigChange({ metaWhatsappAccessToken: e.target.value })}
                    placeholder={
                      isStoredChatSecret(config.metaWhatsappAccessToken)
                        ? `${CHAT_CONFIG_SECRET_MASK} (stored — enter new value to replace)`
                        : 'Access token'
                    }
                  />
                </div>
              </div>
            </div>
          ) : null}

          <div className="rounded-lg border border-gray-100 bg-gray-50/50 p-3 space-y-3">
            <p className="text-xs font-medium text-gray-800">
              {channel === 'sms' ? 'Twilio SMS' : 'Or Twilio WhatsApp'}
            </p>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
              <div className="sm:col-span-3 sm:grid sm:grid-cols-3 sm:gap-3 space-y-3 sm:space-y-0">
                <div>
                  <label className={CREATE_WIZARD_LABEL_CLASS}>Account SID</label>
                  <input
                    className={CREATE_WIZARD_FIELD_CLASS}
                    value={config.twilioAccountSid}
                    onChange={(e) => onConfigChange({ twilioAccountSid: e.target.value })}
                  />
                </div>
                <div>
                  <label className={CREATE_WIZARD_LABEL_CLASS}>Auth token</label>
                  <input
                    type="password"
                    className={CREATE_WIZARD_FIELD_CLASS}
                    value={config.twilioAuthToken}
                    onChange={(e) => onConfigChange({ twilioAuthToken: e.target.value })}
                    placeholder={
                      isStoredChatSecret(config.twilioAuthToken)
                        ? `${CHAT_CONFIG_SECRET_MASK} (stored — enter new value to replace)`
                        : 'Auth token'
                    }
                  />
                </div>
                <div>
                  <label className={CREATE_WIZARD_LABEL_CLASS}>From number</label>
                  <input
                    className={CREATE_WIZARD_FIELD_CLASS}
                    value={config.twilioFrom}
                    onChange={(e) => onConfigChange({ twilioFrom: e.target.value })}
                    placeholder={channel === 'whatsapp' ? 'whatsapp:+…' : '+1…'}
                  />
                </div>
              </div>
            </div>
          </div>

          <AdvancedFields label="Webhooks & integrations">
            {activeIntegrations.length > 0 ? (
              <div>
                <label className={CREATE_WIZARD_LABEL_CLASS}>Saved integration</label>
                <select
                  className={CREATE_WIZARD_FIELD_CLASS}
                  value={config.messagingIntegrationId}
                  onChange={(e) => onConfigChange({ messagingIntegrationId: e.target.value })}
                >
                  <option value="">None</option>
                  {activeIntegrations.map((i) => (
                    <option key={i.id} value={i.id}>
                      {i.name || i.platform}
                    </option>
                  ))}
                </select>
              </div>
            ) : null}
            <div>
              <label className={CREATE_WIZARD_LABEL_CLASS}>Sender ID</label>
              <input
                className={CREATE_WIZARD_FIELD_CLASS}
                value={config.messagingSenderId}
                onChange={(e) => onConfigChange({ messagingSenderId: e.target.value })}
                placeholder="Plivo / custom sender"
              />
            </div>
            <div>
              <label className={CREATE_WIZARD_LABEL_CLASS}>Sync reply URL</label>
              <input
                className={CREATE_WIZARD_FIELD_CLASS}
                value={config.messagingSyncReplyUrl}
                onChange={(e) => onConfigChange({ messagingSyncReplyUrl: e.target.value })}
                placeholder="POST — returns agent reply JSON"
              />
            </div>
            <div>
              <label className={CREATE_WIZARD_LABEL_CLASS}>Outbound webhook</label>
              <input
                className={CREATE_WIZARD_FIELD_CLASS}
                value={config.outboundWebhookUrl}
                onChange={(e) => onConfigChange({ outboundWebhookUrl: e.target.value })}
                placeholder="Optional notify URL"
              />
            </div>
          </AdvancedFields>
        </ConfigPanel>
      </div>
    )
  }

  return null
}
