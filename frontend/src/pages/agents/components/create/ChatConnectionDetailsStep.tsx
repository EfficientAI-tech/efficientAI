import { useState, type ReactNode } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import {
  ChevronDown,
  Cable,
  Copy,
  Globe,
  Loader2,
  MessageCircle,
  MessagesSquare,
  RefreshCw,
  Smartphone,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { Integration, IntegrationPlatform } from '../../../../types/api'
import { apiClient } from '../../../../lib/api'
import { CHAT_CONFIG_SECRET_MASK, isStoredChatSecret } from '../../../../lib/chatConnectionSecrets'
import { CREATE_WIZARD_FIELD_CLASS, CREATE_WIZARD_LABEL_CLASS } from './createWizardUi'
import type { ChatIntegrationOptionId } from './ChatIntegrationTypeStep'
import type { CreateAgentFormData } from './createAgentTypes'
import { useOrgTelephony } from '../../../../hooks/useOrgTelephony'
import { buildPlatformTwilioSmsInboundWebhookUrl } from '../../../../lib/chatMessagingWebhookUrl'
import { useAgentPhoneAssignmentCheck } from '../useAgentPhoneAssignmentCheck'
import { formatAgentPhoneConflictMessage } from '../agentPhoneValidation'

const TWILIO_SMS_TRIAL_BODY_TEMPLATES = [
  { value: '', label: 'Custom body (paid Twilio account)' },
  { value: 'sms_appointment_reminders', label: 'Appointment reminders (trial)' },
  { value: 'sms_customer_support', label: 'Customer support (trial)' },
  { value: 'sms_2fa', label: '2FA (trial)' },
  { value: 'sms_order_confirmation', label: 'Order confirmation (trial)' },
  { value: 'sms_delivery_updates', label: 'Delivery updates (trial)' },
  { value: 'sms_marketing_promotions', label: 'Marketing (trial)' },
  { value: 'sms_event_notifications', label: 'Event notifications (trial)' },
  { value: 'sms_account_alerts', label: 'Account alerts (trial)' },
  { value: 'sms_feedback_surveys', label: 'Feedback surveys (trial)' },
  { value: 'sms_internal_alerts', label: 'Internal alerts (trial)' },
] as const

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
  websocketUrl: string
  websocketAuthHeader: string
  websocketAuthValue: string
  messagingTelephonyIntegrationId: string
  twilioInboundWebhookToken: string
  twilioSmsTrialBodyTemplate: string
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
  websocketUrl: '',
  websocketAuthHeader: 'Authorization',
  websocketAuthValue: '',
  messagingTelephonyIntegrationId: '',
  twilioInboundWebhookToken: '',
  twilioSmsTrialBodyTemplate: 'sms_appointment_reminders',
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
  variant?: 'wizard' | 'workspace'
  agentId?: string
}

function ConfigPanel({
  icon: Icon,
  title,
  children,
  variant = 'wizard',
}: {
  icon: LucideIcon
  title: string
  children: ReactNode
  variant?: 'wizard' | 'workspace'
}) {
  if (variant === 'workspace') {
    return <div className="space-y-4">{children}</div>
  }
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
  if (integrationType === 'customer_websocket') {
    return Boolean(config.websocketUrl.trim() && (!requirePrompt || productionPrompt.trim()))
  }
  if (integrationType === 'messaging_channels') {
    const hasProviderSmsLine = Boolean(formData.telephony_phone_number_id?.trim())
    const hasSmsBasics = config.messagingChannel === 'sms' && hasProviderSmsLine
    const hasWhatsappMeta =
      config.messagingChannel === 'whatsapp' &&
      Boolean(config.metaWhatsappPhoneNumberId.trim() && config.metaWhatsappAccessToken.trim())
    return Boolean(
      config.messagingChannel &&
        (hasSmsBasics || hasWhatsappMeta) &&
        (!requirePrompt || productionPrompt.trim()),
    )
  }
  return true
}

export default function ChatConnectionDetailsStep({
  integrationType,
  formData,
  onFormChange,
  integrations: _integrations,
  selectedPlatform: _selectedPlatform,
  onSelectPlatform: _onSelectPlatform,
  config,
  onConfigChange,
  productionPrompt: _productionPrompt,
  onProductionPromptChange: _onProductionPromptChange,
  onPromptFetched: _onPromptFetched,
  showToast,
  embedded = false,
  variant = 'wizard',
  agentId,
}: ChatConnectionDetailsStepProps) {
  const { activeNumbers: telephonyNumbers } = useOrgTelephony()
  const twilioSmsNumbers = telephonyNumbers.filter(
    (n) =>
      n.is_active &&
      (n.provider || '').toLowerCase() === 'twilio' &&
      n.outbound_enabled !== false,
  )
  const { conflict: smsPhoneConflict, hasConflict: hasSmsPhoneConflict } =
    useAgentPhoneAssignmentCheck({
      enabled: integrationType === 'messaging_channels' && (config.messagingChannel || 'sms') === 'sms',
      callMedium: 'chat',
      telephonyPhoneNumberId: formData.telephony_phone_number_id || undefined,
      excludeAgentId: agentId,
    })
  const { data: messagingPublicBase } = useQuery({
    queryKey: ['chat-messaging-public-base-url'],
    queryFn: () => apiClient.getMessagingPublicBaseUrl(),
    staleTime: 60_000,
  })
  const twilioWebhookPublicBase = messagingPublicBase?.public_base_url || null

  const sectionClass = embedded ? 'w-full' : 'space-y-4'
  const fieldClass =
    variant === 'workspace'
      ? 'w-full px-3 py-2.5 border border-gray-200 rounded-lg bg-white text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-primary-500/30 focus:border-primary-400'
      : CREATE_WIZARD_FIELD_CLASS
  const labelClass =
    variant === 'workspace'
      ? 'block text-sm font-medium text-gray-700 mb-1.5'
      : CREATE_WIZARD_LABEL_CLASS

  if (integrationType === 'internal_llm') {
    return null
  }

  if (integrationType === 'provider_chat') {
    return null
  }

  if (integrationType === 'customer_api') {
    return (
      <div className={sectionClass}>
        <ConfigPanel icon={Globe} title="HTTP API" variant={variant}>
          <div>
            <label className={labelClass}>Base URL *</label>
            <input
              className={fieldClass}
              value={config.apiBaseUrl}
              onChange={(e) => onConfigChange({ apiBaseUrl: e.target.value })}
              placeholder="https://api.example.com"
            />
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label className={labelClass}>Message path</label>
              <input
                className={fieldClass}
                value={config.apiMessagePath}
                onChange={(e) => onConfigChange({ apiMessagePath: e.target.value })}
                placeholder="/chat"
              />
            </div>
            <div>
              <label className={labelClass}>Auth header</label>
              <input
                className={fieldClass}
                value={config.apiAuthHeader}
                onChange={(e) => onConfigChange({ apiAuthHeader: e.target.value })}
                placeholder="Authorization"
              />
            </div>
          </div>
          <div>
            <label className={labelClass}>Auth value</label>
            <input
              type="password"
              className={fieldClass}
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

  if (integrationType === 'customer_websocket') {
    return (
      <div className={sectionClass}>
        <ConfigPanel icon={Cable} title="WebSocket" variant={variant}>
          <div>
            <label className={labelClass}>WebSocket URL *</label>
            <input
              className={fieldClass}
              value={config.websocketUrl}
              onChange={(e) => onConfigChange({ websocketUrl: e.target.value })}
              placeholder="wss://your-agent.example.com/chat"
            />
            <p className="text-xs text-gray-500 mt-1">
              One persistent session per eval run. Each turn sends the same JSON body as the HTTP API
              integration; reply is parsed from the next message.
            </p>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label className={labelClass}>Auth header</label>
              <input
                className={fieldClass}
                value={config.websocketAuthHeader}
                onChange={(e) => onConfigChange({ websocketAuthHeader: e.target.value })}
                placeholder="Authorization"
              />
            </div>
            <div>
              <label className={labelClass}>Auth value</label>
              <input
                type="password"
                className={fieldClass}
                value={config.websocketAuthValue}
                onChange={(e) => onConfigChange({ websocketAuthValue: e.target.value })}
                placeholder={
                  isStoredChatSecret(config.websocketAuthValue)
                    ? `${CHAT_CONFIG_SECRET_MASK} (stored — enter new value to replace)`
                    : 'Optional bearer token'
                }
              />
            </div>
          </div>
        </ConfigPanel>
      </div>
    )
  }

  if (integrationType === 'messaging_channels') {
    const channel = config.messagingChannel || 'sms'
    const platformWebhookUrl = buildPlatformTwilioSmsInboundWebhookUrl(twilioWebhookPublicBase)

    const copyWebhook = async () => {
      if (!platformWebhookUrl) return
      try {
        await navigator.clipboard.writeText(platformWebhookUrl)
        showToast('Webhook URL copied', 'success')
      } catch {
        showToast('Could not copy URL', 'error')
      }
    }

    return (
      <div className={sectionClass}>
        <ConfigPanel icon={MessagesSquare} title="Messaging" variant={variant}>
          <div>
            <label className={labelClass}>Channel *</label>
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

          {channel === 'whatsapp' ? (
            <div className="rounded-lg border border-emerald-100 bg-emerald-50/40 p-3 space-y-3">
              <p className="text-xs font-medium text-emerald-900">Meta WhatsApp Cloud</p>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div>
                  <label className={labelClass}>Phone number ID</label>
                  <input
                    className={fieldClass}
                    value={config.metaWhatsappPhoneNumberId}
                    onChange={(e) => onConfigChange({ metaWhatsappPhoneNumberId: e.target.value })}
                    placeholder="From Meta developer console"
                  />
                </div>
                <div>
                  <label className={labelClass}>Access token</label>
                  <input
                    type="password"
                    className={fieldClass}
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

          {channel === 'sms' ? (
            <div className="space-y-4">
              {twilioSmsNumbers.length === 0 ? (
                <p className="text-xs text-amber-800 bg-amber-50 border border-amber-200 rounded-md px-3 py-2">
                  Import a Twilio number under Telephony Numbers.
                </p>
              ) : (
                <div>
                  <label className={labelClass}>Phone number *</label>
                  <select
                    className={fieldClass}
                    value={formData.telephony_phone_number_id}
                    onChange={(e) => {
                      const id = e.target.value
                      const row = twilioSmsNumbers.find((n) => n.id === id)
                      onFormChange({
                        telephony_phone_number_id: id,
                        phone_number: row?.phone_number || '',
                      })
                    }}
                  >
                    <option value="">Select number</option>
                    {twilioSmsNumbers.map((n) => {
                      const taken =
                        n.agent_id && n.agent_id !== agentId && n.id !== formData.telephony_phone_number_id
                      return (
                        <option key={n.id} value={n.id} disabled={Boolean(taken)}>
                          {n.phone_number}
                          {taken && n.linked_agent_name ? ` · ${n.linked_agent_name}` : ''}
                        </option>
                      )
                    })}
                  </select>
                  {hasSmsPhoneConflict && smsPhoneConflict ? (
                    <p className="text-xs text-red-700 mt-1">
                      {formatAgentPhoneConflictMessage(smsPhoneConflict)}
                    </p>
                  ) : null}
                </div>
              )}

              <div>
                <label className={labelClass}>Trial SMS template</label>
                <select
                  className={fieldClass}
                  value={config.twilioSmsTrialBodyTemplate}
                  onChange={(e) =>
                    onConfigChange({ twilioSmsTrialBodyTemplate: e.target.value })
                  }
                >
                  {TWILIO_SMS_TRIAL_BODY_TEMPLATES.map((opt) => (
                    <option key={opt.value || 'custom'} value={opt.value}>
                      {opt.label}
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label className={labelClass}>Inbound webhook URL</label>
                <div className="flex gap-2">
                  <input className={fieldClass} readOnly value={platformWebhookUrl} />
                  <button
                    type="button"
                    onClick={() => void copyWebhook()}
                    className="shrink-0 inline-flex items-center gap-1 rounded-lg border border-gray-200 bg-white px-2.5 py-2 text-xs font-medium text-gray-800 hover:bg-gray-50"
                  >
                    <Copy className="h-3.5 w-3.5" />
                    Copy
                  </button>
                </div>
              </div>

              <p className="text-xs text-gray-500">
                Choose the eval recipient when you run an evaluator suite (same as voice outbound tests).
              </p>
            </div>
          ) : null}

          {channel === 'whatsapp' ? (
            <AdvancedFields label="Optional">
              <div>
                <label className={labelClass}>Sync reply URL</label>
                <input
                  className={fieldClass}
                  value={config.messagingSyncReplyUrl}
                  onChange={(e) => onConfigChange({ messagingSyncReplyUrl: e.target.value })}
                />
              </div>
            </AdvancedFields>
          ) : null}
        </ConfigPanel>
      </div>
    )
  }

  return null
}
